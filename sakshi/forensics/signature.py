"""Signature analysis: detection, placement, cross-document identity.

Wet signatures vary every time a person signs. Two signatures whose stroke
shapes are near-identical across documents mean one was reproduced (scanned,
copied, pasted). Guard: a signature image inserted by
software into two born-digital documents from the same issuer *is* expected
to be identical, so identity is only escalated when at least one copy is on a
scanned page (a supposed wet signature).
"""
from __future__ import annotations

import re

import cv2
import numpy as np
from skimage.morphology import skeletonize

from ..models import Document, Evidence, Finding

LABEL_RE = re.compile(r"^(for\s.*)?(authori[sz]ed\s+)?(signatory|signature)(\s+of\s+[a-z ]+)?\s*:?$", re.I)


def _printed_text_mask(P, shape) -> np.ndarray:
    """Pixels inside words read confidently as printed text: the PDF text layer, or OCR words read with
    confidence of at least 0.6 and at least two characters. Coloured printed text (a navy letterhead) is not ink."""
    m = np.zeros(shape[:2], np.uint8)
    for w in P.words:
        if len(w.text.strip()) < 2 or (w.source != "pdf_text" and w.conf < 0.6):
            continue
        x0, y0, x1, y1 = (int(round(v)) for v in w.bbox)
        m[max(0, y0 - 2):y1 + 2, max(0, x0 - 2):x1 + 2] = 1
    return m


def detect(doc: Document, ev_dir) -> list[dict]:
    sigs = []
    for P in doc.pages:
        bgr = cv2.imread(P.image_path)
        printed = _printed_text_mask(P, bgr.shape)
        hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)
        b, g, r = [bgr[:, :, i].astype(np.int16) for i in range(3)]
        blue = ((hsv[:, :, 0] >= 95) & (hsv[:, :, 0] <= 135) & (hsv[:, :, 1] > 70) & (hsv[:, :, 2] < 230)
                & (b - r > 40)).astype(np.uint8)
        blue = cv2.morphologyEx(blue, cv2.MORPH_OPEN, np.ones((2, 2), np.uint8))
        grown = cv2.dilate(blue, np.ones((41, 41), np.uint8))
        n, lab, st, _ = cv2.connectedComponentsWithStats(grown, connectivity=8)
        for i in range(1, n):
            x, y, w, h, area = st[i]
            ink = blue[y:y + h, x:x + w] & (lab[y:y + h, x:x + w] == i)
            if ink.sum() < 150 or w < 60 or h < 20:
                continue
            # a solid blue block (header band, photo background) is not a signature
            if ink.sum() > 0.35 * w * h:
                continue
            sk = skeletonize(ink > 0).sum()
            if sk == 0 or ink.sum() / sk > 7.0:
                continue  # thick filled shapes (photo, logo), not pen strokes
            if (ink & printed[y:y + h, x:x + w]).sum() >= 0.5 * ink.sum():
                continue  # mostly inside words read as printed text: coloured print, not a pen
            ys, xs = np.nonzero(ink)
            bb = (x + xs.min(), y + ys.min(), x + xs.max() + 1, y + ys.max() + 1)
            mask = ink[ys.min():ys.max() + 1, xs.min():xs.max() + 1].astype(np.uint8)
            crop_path = ev_dir / f"{doc.doc_id}_p{P.index}_sig{len(sigs)}.png"
            cv2.imwrite(str(crop_path), bgr[bb[1] - 6:bb[3] + 6, bb[0] - 6:bb[2] + 6])
            sigs.append({"doc": doc.doc_id, "page": P.index, "bbox": tuple(float(v) for v in bb), "mask": mask,
                         "crop": str(crop_path), "modality": doc.modality, "ink": "blue"})
        sigs += _black_near_captions(doc, P, bgr, [s for s in sigs if s["page"] == P.index], ev_dir, len(sigs))
        if doc.modality == "digital_pdf":
            sigs += _pdf_signature_images(doc, P, bgr, [s for s in sigs if s["page"] == P.index], ev_dir, len(sigs))
    doc.structure["signatures"] = [{"page": s["page"], "bbox": s["bbox"], "crop": s["crop"], "ink": s.get("ink")}
                                   for s in sigs]
    return sigs


def _pdf_signature_images(doc: Document, P, bgr, found: list[dict], ev_dir, start: int) -> list[dict]:
    """In a born-digital PDF a signature is usually a pasted image, not pen strokes on the page. An embedded image
    counts as a signature when it is small, wider than tall, mostly paper with thin dark strokes (not a photo or a
    filled logo) and sits on the lower part of the page or just above a signature caption."""
    from ..ingest import open_pdf
    out = []
    try:
        pdf = open_pdf(doc.path)
        page = pdf[P.index]
    except Exception:
        return out
    k = P.width / page.rect.width
    labels = [l for l in P.lines if LABEL_RE.search(l.text.strip()) and len(l.text) < 45]
    for img in page.get_images(full=True):
        xref = img[0]
        for r in page.get_image_rects(xref):
            bb = (r.x0 * k, r.y0 * k, r.x1 * k, r.y1 * k)
            w, h = bb[2] - bb[0], bb[3] - bb[1]
            if w < 40 or h < 15 or not (1.2 <= w / h <= 8.0) or w * h > 0.15 * P.width * P.height:
                continue
            near_caption = any(-40 < l.bbox[1] - bb[3] < 260 and bb[0] < l.bbox[2] + 250 and bb[2] > l.bbox[0] - 250
                               for l in labels)
            if not near_caption and bb[1] < 0.45 * P.height:
                continue
            x0, y0, x1, y1 = (int(v) for v in bb)
            crop = bgr[max(0, y0):y1, max(0, x0):x1]
            if crop.size == 0:
                continue
            ink = (cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY) < 170).astype(np.uint8)
            frac = ink.mean()
            sk = skeletonize(ink > 0).sum()
            # a pasted image may be scaled, so stroke width (ink / skeleton) is judged against the image's height
            if not (0.01 <= frac <= 0.30) or sk == 0 or ink.sum() / sk > max(7.0, 0.1 * h):
                continue  # blank, a filled logo or a photo, not handwriting
            if any(min(bb[2], s["bbox"][2]) > max(bb[0], s["bbox"][0]) and min(bb[3], s["bbox"][3]) > max(bb[1], s["bbox"][1])
                   for s in found + out):
                continue  # already found as ink
            crop_path = ev_dir / f"{doc.doc_id}_p{P.index}_sig{start + len(out)}.png"
            cv2.imwrite(str(crop_path), bgr[max(0, y0 - 6):y1 + 6, max(0, x0 - 6):x1 + 6])
            out.append({"doc": doc.doc_id, "page": P.index, "bbox": tuple(float(v) for v in bb), "mask": ink,
                        "crop": str(crop_path), "modality": doc.modality, "ink": "image", "xref": xref,
                        "near_caption": near_caption})
    pdf.close()
    return out


def pasted_later(doc: Document, sigs: list[dict], new_id) -> list[Finding]:
    """A signature image whose object first appears after the file's first end-of-file marker was added in a later
    save. E-signing tools do this too, so it is an inconsistency, and it is not reported when the file carries a
    digital signature."""
    out = []
    mine = [s for s in sigs if s.get("ink") == "image" and s["doc"] == doc.doc_id]
    if not mine or (doc.structure.get("digital_signature") or {}).get("signed"):
        return out
    raw = open(doc.path, "rb").read()
    first_eof = raw.find(b"%%EOF")
    if first_eof < 0 or raw.count(b"%%EOF") < 2:
        return out
    for s in mine:
        m = re.search(rb"(?:^|\s)%d 0 obj" % s["xref"], raw)
        if m and m.start() > first_eof:
            out.append(Finding(
                id=new_id(), check="signature_image_added_later", family="file_structure", sensor="signature",
                title=f"{doc.filename}: the signature image was added in a later save, after the document was first made",
                detail="The image object is not in the file's first saved version; it was appended by a later "
                       "save. Signing tools can do this legitimately, so this is a question to ask, not proof.",
                confidence=0.7, localized=True,
                evidence=[Evidence(doc.doc_id, s["page"], s["bbox"], "signature image added later", crop=s["crop"])],
                docs=[doc.doc_id], verify_next="Ask the issuer for the original signed document."))
    return out


def _black_near_captions(doc: Document, P, bgr, blue_here: list[dict], ev_dir, start: int) -> list[dict]:
    """Black or dark ink is everywhere on a page (printed text, rules, logos), so it is only searched for in the
    place a signature belongs: just above a signature caption that has no blue signature. Every OCR word box is
    erased first, long straight rules are removed, and only thin, curving pen strokes are kept."""
    labels = [l for l in P.lines if LABEL_RE.search(l.text.strip()) and len(l.text) < 45]
    out = []
    if not labels:
        return out
    H, W = bgr.shape[:2]
    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
    sat = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)[:, :, 1]
    dark = ((gray < 120) & (sat < 90)).astype(np.uint8)
    for w in P.words:  # printed text is not a signature; OCR junk read off pen strokes is not printed text
        t = (w.text or "").strip()
        if (w.conf or 0) < 0.6 or len(t) < 2 or sum(ch.isalnum() for ch in t) < 0.6 * len(t):
            continue
        x0, y0, x1, y1 = [int(round(v)) for v in w.bbox]
        dark[max(0, y0 - 3):y1 + 3, max(0, x0 - 3):x1 + 3] = 0
    rules = cv2.morphologyEx(dark, cv2.MORPH_OPEN, np.ones((1, 45), np.uint8)) |         cv2.morphologyEx(dark, cv2.MORPH_OPEN, np.ones((45, 1), np.uint8))
    dark = dark & (1 - rules)
    dark = cv2.morphologyEx(dark, cv2.MORPH_OPEN, np.ones((2, 2), np.uint8))
    hs = sorted(w.bbox[3] - w.bbox[1] for w in P.words if (w.conf or 0) >= 0.6)
    th = hs[len(hs) // 2] if hs else 24.0  # typical printed text height on this page
    n0, lab0, st0, _ = cv2.connectedComponentsWithStats(dark, connectivity=8)
    keep = np.zeros(n0, np.uint8)
    for i in range(1, n0):  # printed glyphs are about one text line tall; pen strokes are taller or much longer
        keep[i] = st0[i][3] >= 1.4 * th or st0[i][2] >= 3.0 * th
    dark = keep[lab0].astype(np.uint8)
    for l in labels:
        if any(-40 < l.bbox[1] - s["bbox"][3] < 260 and s["bbox"][0] < l.bbox[2] + 250 and s["bbox"][2] > l.bbox[0] - 250
               for s in blue_here + out):
            continue
        zx0, zx1 = max(0, int(l.bbox[0] - 250)), min(W, int(l.bbox[2] + 250))
        zy0, zy1 = max(0, int(l.bbox[1] - 380)), min(H, int(l.bbox[1] + 30))
        zone = dark[zy0:zy1, zx0:zx1]
        if zone.sum() < 150:
            continue
        grown = cv2.dilate(zone, np.ones((25, 25), np.uint8))
        n, lab, st, _ = cv2.connectedComponentsWithStats(grown, connectivity=8)
        best = None
        for i in range(1, n):
            x, y, w, h, _a = st[i]
            ink = zone[y:y + h, x:x + w] & (lab[y:y + h, x:x + w] == i)
            s_ink = int(ink.sum())
            if s_ink < 150 or w < 60 or h < 20 or s_ink > 0.35 * w * h:
                continue
            sk = int(skeletonize(ink > 0).sum())
            if sk == 0 or s_ink / sk > 7.0 or sk < 1.2 * (w + h):
                continue  # thick blobs, or short straight marks rather than pen strokes
            if best is None or s_ink > best[0]:
                best = (s_ink, x, y, w, h, ink)
        if best is None:
            continue
        _, x, y, w, h, ink = best
        ys, xs = np.nonzero(ink)
        bb = (zx0 + x + xs.min(), zy0 + y + ys.min(), zx0 + x + xs.max() + 1, zy0 + y + ys.max() + 1)
        mask = ink[ys.min():ys.max() + 1, xs.min():xs.max() + 1].astype(np.uint8)
        crop_path = ev_dir / f"{doc.doc_id}_p{P.index}_sig{start + len(out)}.png"
        cv2.imwrite(str(crop_path), bgr[max(0, bb[1] - 6):bb[3] + 6, max(0, bb[0] - 6):bb[2] + 6])
        out.append({"doc": doc.doc_id, "page": P.index, "bbox": tuple(float(v) for v in bb), "mask": mask,
                    "crop": str(crop_path), "modality": doc.modality, "ink": "black"})
    return out


def placement(doc: Document, sigs: list[dict], new_id) -> list[Finding]:
    out = []
    for P in doc.pages:
        labels = [l for l in P.lines if LABEL_RE.search(l.text.strip()) and len(l.text) < 45]
        mine = [s for s in sigs if s["page"] == P.index]
        for l in labels:
            near = [s for s in mine if -40 < l.bbox[1] - s["bbox"][3] < 260 and s["bbox"][0] < l.bbox[2] + 250
                    and s["bbox"][2] > l.bbox[0] - 250]
            if not near:
                out.append(Finding(
                    id=new_id(), check="signature_missing", family="visual", sensor="signature",
                    title=f"No signature found near '{l.text.strip()}'",
                    detail="The document has a signature caption but no pen strokes (blue or black ink) in the "
                           "expected place above it.",
                    confidence=0.45, localized=True,
                    evidence=[Evidence(doc.doc_id, P.index, l.bbox, "signature caption without signature")],
                    docs=[doc.doc_id]))
        for s in mine:
            if labels and not any(-40 < l.bbox[1] - s["bbox"][3] < 260 for l in labels):
                out.append(Finding(
                    id=new_id(), check="signature_placement", family="visual", sensor="signature",
                    title="Signature is far from any signature caption",
                    detail="Signatures normally sit just above their caption. This one is elsewhere on the page.",
                    confidence=0.5, localized=True,
                    evidence=[Evidence(doc.doc_id, s["page"], s["bbox"], "misplaced signature", crop=s["crop"])],
                    docs=[doc.doc_id]))
    return out


def similarity(a: np.ndarray, b: np.ndarray) -> float:
    """Shape similarity of two ink masks after normalizing position and scale (dilated IoU)."""
    ra = a.shape[1] / max(1, a.shape[0])
    rb = b.shape[1] / max(1, b.shape[0])
    if abs(ra - rb) / max(ra, rb) > 0.15:
        return 0.0
    size = (240, int(240 / ra)) if ra >= 1 else (int(96 * ra), 96)
    A = cv2.resize(a, size, interpolation=cv2.INTER_AREA) > 0
    B = cv2.resize(b, size, interpolation=cv2.INTER_AREA) > 0
    k = np.ones((3, 3), np.uint8)
    A = cv2.dilate(A.astype(np.uint8), k) > 0
    B = cv2.dilate(B.astype(np.uint8), k) > 0
    return float((A & B).sum() / max(1, (A | B).sum()))


def cross_document(all_sigs: list[dict], docs: dict, new_id) -> list[Finding]:
    out = []
    for i in range(len(all_sigs)):
        for j in range(i + 1, len(all_sigs)):
            a, b = all_sigs[i], all_sigs[j]
            if a["doc"] == b["doc"]:
                continue
            s = similarity(a["mask"], b["mask"])
            if s < 0.72:
                continue
            both_digital = a["modality"] == "digital_pdf" and b["modality"] == "digital_pdf"
            system_docs = {"salary_slip", "bank_statement"}
            both_system = docs[a["doc"]].doc_type in system_docs and docs[b["doc"]].doc_type in system_docs
            da, db = docs[a["doc"]], docs[b["doc"]]
            out.append(Finding(
                id=new_id(), check="signature_identical", family="visual", sensor="signature",
                title=(f"Signatures on {da.filename} and {db.filename} are shape-identical (similarity {s:.2f})"),
                detail=("Two signatures by the same signatory never match stroke for stroke; natural variation on "
                        "this dataset gives similarity around 0.3 to 0.6. "
                        + ("Both documents are born-digital, so a software-inserted signature image is expected."
                           if both_digital else
                           "At least one copy sits on a scanned page, i.e. it is presented as a wet signature, "
                           "yet it matches another document's signature exactly.")),
                confidence=round(0.5 + 0.45 * (s - 0.72) / 0.28, 2) if not both_digital else 0.3, localized=True,
                evidence=[Evidence(a["doc"], a["page"], a["bbox"], "signature A", crop=a["crop"]),
                          Evidence(b["doc"], b["page"], b["bbox"], "signature B", crop=b["crop"])],
                docs=[a["doc"], b["doc"]], repair={"similarity": round(s, 3), "both_digital": both_digital,
                                                   "both_system": both_system,
                                                   "target_docs": [x["doc"] for x in (a, b) if x["modality"] != "digital_pdf"]}))
    return out
