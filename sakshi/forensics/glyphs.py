"""Digit typography consistency (scans and photos).

Forgers touch amounts and dates. A retyped value rarely matches the original
print exactly: ink darkness, stroke thickness, digit height and baseline drift.
Each numeric token is compared only with the other numeric tokens of the same
document (so dot-matrix or faded prints form their own population).

Guard: a deviation shared by two or more tokens is a style (bold headings,
larger totals), not an anomaly. Only singletons are reported.
"""
from __future__ import annotations

import re

import cv2
import numpy as np
from skimage.morphology import skeletonize

from ..models import Document, Evidence, Finding

FEATS = ["ink_darkness", "stroke_ratio", "height_ratio", "baseline_offset", "edge_sharpness"]
LABELS = {"ink_darkness": "ink darkness", "stroke_ratio": "stroke thickness",
          "height_ratio": "digit height", "baseline_offset": "baseline position",
          "edge_sharpness": "edge sharpness"}


def token_features(gray: np.ndarray, word, line_words) -> dict | None:
    x0, y0, x1, y1 = (int(v) for v in word.bbox)
    H, W = gray.shape
    x0, y0, x1, y1 = max(0, x0 - 1), max(0, y0 - 1), min(W, x1 + 1), min(H, y1 + 1)
    crop = gray[y0:y1, x0:x1]
    if crop.size < 60:
        return None
    if float(np.median(crop)) < 140:
        return None  # light text on a dark band (letterheads): inverted polarity, not comparable
    thr, ink = cv2.threshold(crop, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    ink = ink > 0
    if ink.sum() < 25:
        return None
    n, lab, st, _ = cv2.connectedComponentsWithStats(ink.astype(np.uint8), connectivity=8)
    comps = [st[i] for i in range(1, n) if st[i][4] >= 8]
    if not comps:
        return None
    hmax = max(c[3] for c in comps)
    digits = [c for c in comps if c[3] >= 0.6 * hmax]
    dh = float(np.median([c[3] for c in digits]))
    bottom = float(np.median([y0 + c[1] + c[3] for c in digits]))
    core = cv2.erode(ink.astype(np.uint8), np.ones((2, 2), np.uint8)) > 0
    dark = float(np.median(crop[core])) if core.sum() > 10 else float(np.median(crop[ink]))
    sk = skeletonize(ink)
    stroke = float(ink.sum()) / max(1.0, float(sk.sum()))
    # baseline relative to the line's other words
    wh = word.bbox[3] - word.bbox[1]
    others = [w for w in line_words if w is not word and w.conf > 0.5
              and abs((w.bbox[3] - w.bbox[1]) - wh) < 0.3 * wh]
    if len(others) >= 2:
        ref = float(np.median([w.bbox[3] for w in others]))
        base = (bottom - ref) / max(dh, 1.0)
    else:
        base = float("nan")  # not enough line-mates to define a baseline
    # edge sharpness: steepest ink edges relative to contrast. Text retyped digitally on top of a
    # scan has not been through the scanner's optics, so its edges are crisper.
    g = crop.astype(np.float32)
    grad = np.hypot(cv2.Sobel(g, cv2.CV_32F, 1, 0, ksize=3), cv2.Sobel(g, cv2.CV_32F, 0, 1, ksize=3))
    paper = float(np.median(crop[~ink])) if (~ink).sum() > 10 else 240.0
    contrast = max(20.0, paper - dark)
    sharp = float(np.percentile(grad, 97)) / contrast
    line_h = float(np.median([w.bbox[3] - w.bbox[1] for w in line_words])) if line_words else dh
    return {"ink_darkness": dark, "stroke_ratio": stroke / max(dh, 1.0), "height_ratio": dh / max(line_h, 1.0),
            "baseline_offset": base, "edge_sharpness": sharp, "digit_height": dh}


def analyse(doc: Document, new_id) -> list[Finding]:
    out: list[Finding] = []
    if doc.modality == "digital_pdf":
        doc.capabilities["glyphs"] = "n/a (born-digital: fonts are read from the file instead)"
        return out
    for P in doc.pages:
        gray = cv2.cvtColor(cv2.imread(P.image_path), cv2.COLOR_BGR2GRAY)
        toks = []
        from .raster import _in_any, _overlay_boxes
        ov = _overlay_boxes(doc, P.index)  # PDF-layer text over a scan is judged by the overlay sensor
        for line in P.lines:
            for w in line.words:
                if ov and _in_any(w.bbox, ov):
                    continue
                if sum(c.isdigit() for c in w.text) >= 3 and len(w.text) >= 3:
                    f = token_features(gray, w, line.words)
                    if f:
                        toks.append((w, f))
        if len(toks) < 8:
            doc.capabilities["glyphs"] = f"blind (only {len(toks)} numeric tokens, need 8)"
            continue
        page_dh = float(np.median([f["digit_height"] for _, f in toks]))
        for _, f in toks:  # digit height relative to the page's own digit height (one font size per form)
            f["height_ratio"] = f["digit_height"] / max(page_dh, 1.0)
        X = np.array([[f[k] for k in FEATS] for _, f in toks], dtype=float)
        med = np.nanmedian(X, axis=0)
        mad = 1.4826 * np.nanmedian(np.abs(X - med), axis=0)
        floor = np.array([4.0, 0.02, 0.025, 0.08, 0.15])  # minimum meaningful spread per feature
        scale = np.maximum(np.nan_to_num(mad), floor)
        Z = np.nan_to_num((X - med) / scale)
        flagged = []
        for i, (w, f) in enumerate(toks):
            z = Z[i]
            strong = [k for k, v in zip(FEATS, z) if abs(v) > 3.5]
            if not (len(strong) >= 2 or (strong and max(abs(z)) > 7)):
                continue
            # singleton guard: does any other token share this deviation?
            idx = [FEATS.index(k) for k in strong]
            tol = np.maximum(1.5, 0.35 * np.abs(z[idx]))
            twins = [j for j in range(len(toks)) if j != i and np.all(np.abs(Z[j, idx] - z[idx]) < tol)]
            if twins:
                continue
            # line-style guard (v1.0): a bold or larger value next to an equally bold/large label is the line's style
            line = next((l for l in P.lines if w in l.words), None)
            mates = [m for m in (line.words if line else []) if m is not w and sum(c.isalpha() for c in m.text) >= 3]
            ms = [token_features(gray, m, line.words) for m in mates]
            ms = [m for m in ms if m]
            if ms:
                ref_stroke = float(np.median([m["stroke_ratio"] for m in ms]))
                ref_h = float(np.median([m["digit_height"] for m in ms]))
                if abs(ref_stroke - f["stroke_ratio"]) / max(f["stroke_ratio"], 1e-6) < 0.15 and \
                        abs(ref_stroke - med[FEATS.index("stroke_ratio")]) > abs(f["stroke_ratio"] - ref_stroke) and \
                        abs(ref_h - f["digit_height"]) / max(f["digit_height"], 1.0) < 0.2:
                    continue
            flagged.append((w, f, z, strong))
        for w, f, z, strong in flagged:
            desc = ", ".join(f"{LABELS[k]} {z[FEATS.index(k)]:+.1f} sd" for k in strong)
            out.append(Finding(
                id=new_id(), check="glyph_outlier", family="visual", sensor="glyphs",
                title=f"'{w.text}' is printed differently from every other number on the page",
                detail=(f"Compared with the other {len(toks) - 1} numeric values on this page, this one deviates in {desc}. "
                        "No other value shares this style, so it is not a heading or bold style. A value retyped in a "
                        "different font, size or ink after printing looks like this."),
                confidence=round(float(np.clip(0.5 + 0.04 * max(abs(z)), 0.55, 0.78)), 2), localized=True,
                evidence=[Evidence(doc.doc_id, P.index, w.bbox, f"typography outlier ({desc})", value=w.text)],
                docs=[doc.doc_id]))
        doc.capabilities["glyphs"] = f"ok ({len(toks)} numeric tokens)"
    return out
