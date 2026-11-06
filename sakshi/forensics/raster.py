"""v1.0 raster sensors (scans and photos).

* erasure patches and JPEG ghosts on value boxes: wraps compression.py
* intra-token font consistency: digits inside ONE printed number share one font, weight and ink.
  A number whose last two digits are thinner or lighter than its first ones was partly retyped.
* scan-clone detection across documents: two different physical scans never share sensor noise.
  If, after aligning page B onto page A, their paper grain correlates, one page was made by
  digitally editing the other. The pixels where the two pages then differ are the edits.
"""
from __future__ import annotations

import cv2
import numpy as np
from skimage.morphology import skeletonize

from ..models import Document, Evidence, Finding
from . import compression

# Below this digit height (pixels) ink-level sensors are blind: forwarded/downscaled images alias
# thin strokes. SAKSHI says "blind" rather than guess.
MIN_GLYPH_PX = 16
# Optics: an edit is a handful of tokens. If many words are "sharper than the page", the page has
# two rendering layers (mixed-raster PDF, scanner-app text enhancement) and the sensor is vetoed.
OPTICS_BIMODAL_FRAC = 0.08
OPTICS_MAX_HITS = 5


def _overlay_boxes(doc: Document, page_index: int) -> list:
    """Regions the PDF draws OVER a scan. Those pixels never passed through the scanner, so scan-physics
    sensors must not judge them; the overlay-peel sensor owns them (G9 genuine e-sign stamp)."""
    return [o["bbox"] for L in doc.structure.get("scan_overlays", []) if L["page"] == page_index for o in L["objects"]]


def _in_any(b, boxes) -> bool:
    for o in boxes:
        ix = min(b[2], o[2]) - max(b[0], o[0])
        iy = min(b[3], o[3]) - max(b[1], o[1])
        if ix > 0 and iy > 0 and ix * iy >= 0.3 * max(1.0, (b[2] - b[0]) * (b[3] - b[1])):
            return True
    return False


def _value_boxes(doc: Document, P):
    boxes = []
    for f in doc.fields.values():
        if f.page == P.index and f.kind in ("amount", "date", "id", "int", "text") and len(str(f.raw)) <= 40:
            boxes.append((tuple(int(v) for v in f.bbox), f))
    for w in P.words:
        if sum(c.isdigit() for c in w.text) >= 3 and not any(abs(w.bbox[0] - b[0][0]) < 3 and abs(w.bbox[1] - b[0][1]) < 3 for b in boxes):
            boxes.append((tuple(int(v) for v in w.bbox), None))
    return boxes


def erasure_and_ghosts(doc: Document, new_id) -> list[Finding]:
    out = []
    if doc.modality == "digital_pdf":
        doc.capabilities["compression"] = "n/a (born-digital)"
        return out
    for P in doc.pages:
        gray = cv2.cvtColor(cv2.imread(P.image_path), cv2.COLOR_BGR2GRAY)
        vb = _value_boxes(doc, P)
        if not vb:
            continue
        boxes = [b for b, _ in vb]
        for z in compression.zero_variance_patches(gray, boxes):
            f = next((ff for b, ff in vb if b == tuple(z["bbox"])), None)
            x0, y0, x1, y1 = z["bbox"]
            inner = gray[max(0, y0):y1, max(0, x0):x1]
            ring = gray[max(0, y0 - 16):y1 + 16, max(0, x0 - 16):x1 + 16]
            tone_in = float(np.median(inner[inner > 150])) if (inner > 150).any() else 0.0
            tone_out = float(np.median(ring[ring > 150])) if (ring > 150).any() else 0.0
            label = f"'{f.raw}'" if f else "this value"
            out.append(Finding(
                id=new_id(), check="zero_variance_patch", family="visual", sensor="compression",
                title=f"Paper behind {label} has no scanner grain (noise {z['inner_std']:.1f} vs {z['ring_std']:.1f} around it)",
                detail=(f"Between the glyphs of {label} the paper is flat: robust noise {z['inner_std']:.2f} against "
                        f"{z['ring_std']:.2f} in a ring just outside the box. Paper tone {tone_in:.0f} inside vs "
                        f"{tone_out:.0f} outside. A scanner cannot produce a noise-free rectangle; a paint or white-out "
                        "tool can."),
                confidence=0.9 if z["inner_std"] < 0.15 * z["ring_std"] else 0.8, localized=True,
                evidence=[Evidence(doc.doc_id, P.index, tuple(float(v) for v in z["bbox"]), z["note"], kind="field",
                                   value=f.raw if f else "")],
                fields=[f.key()] if f else [], docs=[doc.doc_id]))
        try:
            ghosts = compression.jpeg_ghosts(gray, boxes)
        except Exception:
            ghosts = []
        for g in ghosts:
            f = next((ff for b, ff in vb if b == tuple(g["bbox"])), None)
            out.append(Finding(
                id=new_id(), check="compression_ghost", family="visual", sensor="compression",
                title=f"Compression history of {('%r' % f.raw) if f else 'this region'} differs from the page "
                      f"(JPEG ghost at Q{g['q_star_box']} vs page Q{g['q_star_page']})",
                detail=("Re-compressing the page at a range of JPEG qualities, this box reaches its minimum error at a "
                        "different quality than the rest of the page (robust z = %.1f). Content pasted from another JPEG "
                        "keeps its own compression history." % g["z"]),
                confidence=0.65, localized=True,
                evidence=[Evidence(doc.doc_id, P.index, tuple(float(v) for v in g["bbox"]), g["note"], kind="field",
                                   value=f.raw if f else "")],
                fields=[f.key()] if f else [], docs=[doc.doc_id]))
        doc.capabilities["compression"] = f"ok ({len(boxes)} value boxes)"
    return out


def _glyph_stats(gray, word):
    x0, y0, x1, y1 = (int(v) for v in word.bbox)
    H, W = gray.shape
    x0, y0, x1, y1 = max(0, x0 - 1), max(0, y0 - 1), min(W, x1 + 1), min(H, y1 + 1)
    crop = gray[y0:y1, x0:x1]
    if crop.size < 80:
        return []
    _, ink = cv2.threshold(crop, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    ink = ink > 0
    n, lab, st, _ = cv2.connectedComponentsWithStats(ink.astype(np.uint8), connectivity=8)
    comps = [i for i in range(1, n) if st[i][4] >= 10]
    if not comps:
        return []
    hmax = max(st[i][3] for i in comps)
    out = []
    for i in comps:
        cx, cy, cw, ch, area = st[i]
        if ch < 0.6 * hmax:
            continue
        m = lab[cy:cy + ch, cx:cx + cw] == i
        sk = skeletonize(m).sum()
        if sk < 4:
            continue
        core = crop[cy:cy + ch, cx:cx + cw][m]
        out.append({"x": x0 + cx, "bbox": (x0 + cx, y0 + cy, x0 + cx + cw, y0 + cy + ch), "stroke": area / sk,
                    "dark": float(np.percentile(core, 30)), "h": ch})
    return sorted(out, key=lambda g: g["x"])


def intra_token_font(doc: Document, new_id) -> list[Finding]:
    out = []
    if doc.modality == "digital_pdf":
        return out
    small = measured = 0
    for P in doc.pages:
        gray = cv2.cvtColor(cv2.imread(P.image_path), cv2.COLOR_BGR2GRAY)
        ov = _overlay_boxes(doc, P.index)
        for w in P.words:
            if ov and _in_any(w.bbox, ov):
                continue
            nd = sum(c.isdigit() for c in w.text)
            na = sum(c.isalpha() for c in w.text)
            if nd < 4 or na > 0:
                continue  # numbers only: letters have legitimately different stroke widths
            gl = _glyph_stats(gray, w)
            if len(gl) < nd:
                continue  # segmentation merged glyphs: no reliable per-digit statistics
            gl = gl[:nd]  # drop trailing '/' of '/-' style suffixes
            if len(gl) < 4:
                continue
            if float(np.median([g["h"] for g in gl])) < MIN_GLYPH_PX:
                small += 1
                continue  # downscaled / forwarded image: sub-pixel aliasing makes stroke widths unreliable
            measured += 1
            sw = np.array([g["stroke"] for g in gl])
            dk = np.array([g["dark"] for g in gl])
            hh = np.array([g["h"] for g in gl], float)
            n = len(gl)
            best = None
            # a forger replaces ADJACENT digits: test every contiguous run against the rest of the number
            for L in range(2, n // 2 + 1):  # single-glyph runs are too noisy (e.g. "1" stroke estimates)
                for st0 in range(0, n - L + 1):
                    run = np.zeros(n, bool)
                    run[st0:st0 + L] = True
                    rest = sw[~run]
                    med_r = float(np.median(rest))
                    sd_r = max(1.4826 * float(np.median(np.abs(rest - med_r))), 0.04 * med_r)
                    if float(np.std(rest)) / med_r > 0.08:
                        continue
                    z = (sw[run] - med_r) / sd_r
                    dev = (sw[run] - med_r) / med_r
                    if not (np.all(np.sign(z) == np.sign(z[0])) and np.all(np.abs(dev) >= 0.15)):
                        continue
                    zmin = float(np.min(np.abs(z)))
                    if zmin >= (6.0 if L == 1 else 4.5) and (best is None or zmin > best[0]):
                        best = (zmin, run, med_r, float(np.median(dev)))
            if best is None:
                continue
            zmin, odd, med_r, mdev = best
            rest = ~odd
            dark_gap = abs(float(np.median(dk[odd]) - np.median(dk[rest])))
            h_gap = abs(float(np.median(hh[odd]) - np.median(hh[rest]))) / max(1.0, float(np.median(hh[rest])))
            med = med_r
            dev = (sw - med) / med
            idx = np.nonzero(odd)[0]
            bb = (min(gl[i]["bbox"][0] for i in idx), min(gl[i]["bbox"][1] for i in idx),
                  max(gl[i]["bbox"][2] for i in idx), max(gl[i]["bbox"][3] for i in idx))
            out.append(Finding(
                id=new_id(), check="intra_token_font", family="visual", sensor="raster",
                title=f"Inside '{w.text}', {len(idx)} digit(s) are printed in a different weight from the rest",
                detail=(f"Digits of one printed number come from one font, one size and one pass of ink. Here "
                        f"{len(idx)} of {len(gl)} digits have stroke width {np.median(sw[odd]):.1f}px against "
                        f"{np.median(sw[rest]):.1f}px for the others ({np.median(dev[odd]) * 100:+.0f}%), ink darkness "
                        f"differs by {dark_gap:.0f} grey levels and height by {h_gap * 100:.0f}%. Part of this number was "
                        "replaced after printing."),
                confidence=round(float(min(0.88, 0.55 + 0.04 * zmin)), 2), localized=True,
                evidence=[Evidence(doc.doc_id, P.index, tuple(float(v) for v in bb), "odd digits", value=w.text),
                          Evidence(doc.doc_id, P.index, tuple(float(v) for v in w.bbox), "whole number", value=w.text)],
                docs=[doc.doc_id]))
    if small and not measured:
        doc.capabilities["intra_token_font"] = f"blind (digits under {MIN_GLYPH_PX}px tall: image too small)"
    else:
        doc.capabilities["intra_token_font"] = f"ok ({measured} numbers)" + (f", {small} too small" if small else "")
    return out


def _residual(g):
    return g.astype(np.float32) - cv2.medianBlur(g, 3).astype(np.float32)


def scan_clones(docs: dict, new_id) -> list[Finding]:
    """Pairwise check of scanned pages for shared sensor noise after alignment."""
    out = []
    pages = []
    for d in docs.values():
        if d.modality == "digital_pdf":
            continue
        for P in d.pages:
            if P.noise_sigma >= 1.5:
                pages.append((d, P))
    orb = cv2.ORB_create(3000)
    feats = {}
    for d, P in pages:
        g = cv2.cvtColor(cv2.imread(P.image_path), cv2.COLOR_BGR2GRAY)
        small = cv2.resize(g, None, fx=0.5, fy=0.5, interpolation=cv2.INTER_AREA)
        kp, des = orb.detectAndCompute(small, None)
        feats[(d.doc_id, P.index)] = (g, kp, des)
    bf = cv2.BFMatcher(cv2.NORM_HAMMING, crossCheck=True)
    for i in range(len(pages)):
        for j in range(i + 1, len(pages)):
            (da, Pa), (db, Pb) = pages[i], pages[j]
            if da.doc_id == db.doc_id or da.sha256 == db.sha256:
                continue
            if abs(Pa.width / Pa.height - Pb.width / Pb.height) > 0.03:
                continue
            ga, ka, dsa = feats[(da.doc_id, Pa.index)]
            gb, kb, dsb = feats[(db.doc_id, Pb.index)]
            if dsa is None or dsb is None or len(ka) < 50 or len(kb) < 50:
                continue
            m = bf.match(dsa, dsb)
            if len(m) < 60:
                continue
            src = np.float32([kb[x.trainIdx].pt for x in m]) * 2
            dst = np.float32([ka[x.queryIdx].pt for x in m]) * 2
            Hm, inl = cv2.findHomography(src, dst, cv2.RANSAC, 3.0)
            if Hm is None or inl is None or int(inl.sum()) < 60:
                continue
            wb = cv2.warpPerspective(gb, Hm, (ga.shape[1], ga.shape[0]), flags=cv2.INTER_NEAREST, borderValue=0)
            ra, rb = _residual(ga), _residual(wb)
            paper = (ga > 170) & (wb > 170)
            cors = []
            B = 64
            for y in range(0, ga.shape[0] - B, B):
                for x in range(0, ga.shape[1] - B, B):
                    pm = paper[y:y + B, x:x + B]
                    if pm.sum() < 0.6 * B * B:
                        continue
                    a = ra[y:y + B, x:x + B][pm]
                    b = rb[y:y + B, x:x + B][pm]
                    sa, sb = a.std(), b.std()
                    if sa < 1e-3 or sb < 1e-3:
                        continue
                    cors.append(float(((a - a.mean()) * (b - b.mean())).mean() / (sa * sb)))
            if len(cors) < 30:
                continue
            c = float(np.median(cors))
            if c < 0.45:
                continue
            diff = cv2.absdiff(ga, wb)
            diff = cv2.GaussianBlur(diff, (0, 0), 2.0)
            mask = ((diff > 35) & (wb > 0)).astype(np.uint8)
            mask = cv2.dilate(mask, np.ones((9, 9), np.uint8))
            n, lab, stt, _ = cv2.connectedComponentsWithStats(mask, connectivity=8)
            regions = sorted([tuple(int(v) for v in (stt[k][0], stt[k][1], stt[k][0] + stt[k][2], stt[k][1] + stt[k][3]))
                              for k in range(1, n) if stt[k][4] > 120], key=lambda r: -(r[2] - r[0]) * (r[3] - r[1]))[:6]
            out.append(Finding(
                id=new_id(), check="scan_clone", family="visual", sensor="raster",
                title=f"{db.filename} is a digitally edited copy of the scan {da.filename} (shared sensor grain {c:.2f})",
                detail=(f"After aligning the two pages ({int(inl.sum())} matched features), the scanner noise in their paper "
                        f"areas correlates at {c:.2f}; two separate scans of two separate sheets correlate near 0.00. "
                        f"One file was produced by editing the other. The {len(regions)} region(s) where the pages differ "
                        "are where it was edited."),
                confidence=round(min(0.97, 0.6 + 0.4 * c), 2), localized=bool(regions), smoking_gun=c > 0.6,
                evidence=[Evidence(da.doc_id, Pa.index, r, "differs between the two pages") for r in regions[:4]]
                         + [Evidence(db.doc_id, Pb.index, (0, 0, Pb.width, Pb.height), "edited copy (whole page)")],
                docs=[da.doc_id, db.doc_id], repair={"grain_correlation": round(c, 3), "target_docs": [db.doc_id]},
                verify_next="Ask for the original payslips from the employer's payroll portal."))
    return out


def _edge_sharpness(gray, bbox):
    x0, y0, x1, y1 = (int(v) for v in bbox)
    H, W = gray.shape
    x0, y0, x1, y1 = max(0, x0 - 2), max(0, y0 - 2), min(W, x1 + 2), min(H, y1 + 2)
    crop = gray[y0:y1, x0:x1]
    if crop.size < 150 or (y1 - y0) < 14:
        return None
    if float(np.median(crop)) < 140:
        return None  # light text on a dark band: polarity differs, skip
    _, ink = cv2.threshold(crop, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    ink = ink > 0
    if ink.sum() < 20 or (~ink).sum() < 20:
        return None
    g = crop.astype(np.float32)
    grad = np.hypot(cv2.Sobel(g, cv2.CV_32F, 1, 0, ksize=3), cv2.Sobel(g, cv2.CV_32F, 0, 1, ksize=3))
    contrast = float(np.median(crop[~ink])) - float(np.percentile(crop[ink], 20))
    if contrast < 60:
        return None
    return float(np.percentile(grad, 98)) / contrast


def optics_outliers(doc: Document, new_id) -> list[Finding]:
    """Scanner optics: everything that went through the scanner shares its blur (point-spread function).
    Text typed onto the image afterwards has crisper edges than every other word on the page. This
    measures ink EDGES, so it is physically independent of the paper-noise and compression sensors."""
    out = []
    if doc.modality == "digital_pdf":
        doc.capabilities["optics"] = "n/a (born-digital)"
        return out
    for P in doc.pages:
        gray = cv2.cvtColor(cv2.imread(P.image_path), cv2.COLOR_BGR2GRAY)
        vals, cands = [], []
        ov = _overlay_boxes(doc, P.index)
        for w in P.words:
            if sum(ch.isalnum() for ch in w.text) < 2 or (ov and _in_any(w.bbox, ov)):
                continue
            s = _edge_sharpness(gray, w.bbox)
            if s is None:
                continue
            if w.conf >= 0.5:
                vals.append((w, s))  # the page's optics baseline uses confident words only
            if sum(c.isdigit() for c in w.text) >= 2:
                cands.append((w, s))  # any value can be a candidate, even a poorly read one
        if len(vals) < 25:
            doc.capabilities["optics"] = f"blind (only {len(vals)} measurable words)"
            continue
        hgt = float(np.median([w.bbox[3] - w.bbox[1] for w, _ in vals]))
        if hgt < MIN_GLYPH_PX + 2:
            doc.capabilities["optics"] = f"blind (text only {hgt:.0f}px tall: image too small)"
            continue
        arr = np.array([s for _, s in vals])
        med = float(np.median(arr))
        sd = max(1.4826 * float(np.median(np.abs(arr - med))), 0.03 * med)
        frac = float(np.mean((arr - med) / sd > 3.0))
        hits = [(w, (s - med) / sd, s) for w, s in cands if (s - med) / sd >= 4.0]
        if frac > OPTICS_BIMODAL_FRAC or len(hits) > OPTICS_MAX_HITS:
            doc.capabilities["optics"] = (f"vetoed on page {P.index + 1}: {frac * 100:.0f}% of words / {len(hits)} values "
                                          "sharper than the page (two rendering layers, not an edit)")
            continue
        for w, z, s in hits:
            f = next((ff for ff in doc.fields.values() if ff.page == P.index and ff.bbox[0] <= w.bbox[0] + 2
                      and ff.bbox[2] >= w.bbox[2] - 2 and ff.bbox[1] <= w.bbox[1] + 4 and ff.bbox[3] >= w.bbox[3] - 4), None)
            out.append(Finding(
                id=new_id(), check="optics_outlier", family="visual", sensor="raster",
                title=f"'{w.text}' has crisper ink edges than every other word on the page (z = {z:.1f})",
                detail=(f"All {len(vals)} measurable words on this page share the scanner's blur: edge sharpness "
                        f"{med:.2f} +- {sd:.2f}. This value measures {s:.2f}. Text that was typed onto the image after "
                        "scanning never passed through the scanner's optics, so its edges are sharper. This sensor reads "
                        "ink edges, not paper, so it is independent of the noise and compression sensors."),
                confidence=round(float(min(0.88, 0.5 + 0.04 * z)), 2), localized=True,
                evidence=[Evidence(doc.doc_id, P.index, tuple(float(v) for v in w.bbox), f"edge sharpness {s:.2f} vs {med:.2f}",
                                   kind="field", value=w.text)],
                fields=[f.key()] if f else [], docs=[doc.doc_id]))
        doc.capabilities["optics"] = f"ok ({len(vals)} words)"
    return out
