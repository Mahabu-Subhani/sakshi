"""Copy-move detection on digits (scans and photos).

A scanner never produces the same noise twice. Two copies of the digit '1'
printed in different rows look alike in shape, but the paper grain around them
is independent random noise. If the grain around two glyphs is the same pixel
for pixel, one was copied from the other after scanning.

We compare every pair of digit glyphs of similar size inside numeric tokens and
measure the median absolute difference on the *paper* pixels around them,
normalized by the page's own noise level. Genuine pairs sit near 0.67 x sigma x
sqrt(2); copies sit near zero (plus a little re-compression error).
"""
from __future__ import annotations

import re
from collections import defaultdict

import cv2
import numpy as np

from ..models import Document, Evidence, Finding

PAD = 3


def digit_glyphs(gray: np.ndarray, words) -> list[dict]:
    """Connected ink components inside numeric tokens, with their pixel crops."""
    H, W = gray.shape
    out = []
    for w in words:
        if not re.search(r"\d", w.text) or sum(c.isdigit() for c in w.text) < 2:
            continue
        x0, y0, x1, y1 = (int(v) for v in w.bbox)
        x0, y0, x1, y1 = max(0, x0 - 2), max(0, y0 - 2), min(W, x1 + 2), min(H, y1 + 2)
        crop = gray[y0:y1, x0:x1]
        if crop.size == 0:
            continue
        ink = (crop < 140).astype(np.uint8)
        n, lab, st, _ = cv2.connectedComponentsWithStats(ink, connectivity=8)
        hmax = max((st[i][3] for i in range(1, n)), default=0)
        for i in range(1, n):
            cx, cy, cw, ch, area = st[i]
            if ch < 0.6 * hmax or area < 12:
                continue  # commas, dots, specks
            gx0, gy0 = x0 + cx - PAD, y0 + cy - PAD
            gx1, gy1 = x0 + cx + cw + PAD, y0 + cy + ch + PAD
            if gx0 < 0 or gy0 < 0 or gx1 > W or gy1 > H:
                continue
            out.append({"word": w, "bbox": (gx0, gy0, gx1, gy1), "w": cw, "h": ch, "area": int(area)})
    return out


def _pair_score(gray, a, b, sig):
    """Best median |diff| on paper pixels over +-1 px alignment, normalized by expected noise."""
    ax0, ay0, ax1, ay1 = a["bbox"]
    A = gray[ay0:ay1, ax0:ax1].astype(np.float32)
    best = 9e9
    bx0, by0 = b["bbox"][:2]
    for dy in (-1, 0, 1):
        for dx in (-1, 0, 1):
            y, x = by0 + dy, bx0 + dx
            B = gray[y:y + A.shape[0], x:x + A.shape[1]].astype(np.float32)
            if B.shape != A.shape:
                continue
            paper = (A > 165) & (B > 165)
            if paper.sum() < 0.3 * A.size:
                continue
            if A[paper].std() < 0.5 * sig or B[paper].std() < 0.5 * sig:
                return 9e9  # noise-free paper (digital fill): the noise sensor's job, not a copy-move
            d = np.abs(A - B)[paper]
            best = min(best, float(np.median(d)))
    return best / (sig * np.sqrt(2) + 1e-6)


def analyse(doc: Document, new_id) -> list[Finding]:
    out: list[Finding] = []
    if doc.modality == "digital_pdf":
        doc.capabilities["copy_move"] = "n/a (born-digital: identical glyphs are expected)"
        return out
    for P in doc.pages:
        sig = P.noise_sigma
        if sig < 1.5:
            doc.capabilities["copy_move"] = f"blind (page noise {sig:.2f} too low to fingerprint)"
            continue
        gray = cv2.cvtColor(cv2.imread(P.image_path), cv2.COLOR_BGR2GRAY)
        gl = digit_glyphs(gray, P.words)
        if len(gl) < 2:
            doc.capabilities["copy_move"] = "n/a (fewer than 2 digit glyphs)"
            continue
        # cheap vectorized prefilter: same size (+-1px) and same ink shape (a copy has its donor's shape)
        masks = np.stack([cv2.resize((gray[g["bbox"][1] + PAD:g["bbox"][3] - PAD, g["bbox"][0] + PAD:g["bbox"][2] - PAD]
                                      < 140).astype(np.uint8), (12, 20), interpolation=cv2.INTER_NEAREST).ravel()
                          for g in gl]).astype(np.float32)
        inter = masks @ masks.T
        cnt = masks.sum(1)
        union = cnt[:, None] + cnt[None, :] - inter
        iou = inter / np.maximum(union, 1)
        ws = np.array([g["w"] for g in gl]); hs = np.array([g["h"] for g in gl])
        xs = np.array([g["bbox"][0] for g in gl]); ys = np.array([g["bbox"][1] for g in gl])
        cand = (iou > 0.8) & (np.abs(ws[:, None] - ws[None, :]) <= 1) & (np.abs(hs[:, None] - hs[None, :]) <= 1) \
            & ((np.abs(xs[:, None] - xs[None, :]) > 4) | (np.abs(ys[:, None] - ys[None, :]) > 4))
        ii, jj = np.nonzero(np.triu(cand, 1))
        pairs = len(ii)
        for i, j in zip(ii.tolist(), jj.tolist()):
            a, b = gl[i], gl[j]
            if a["word"] is b["word"]:
                continue  # repeated digits inside one value (e.g. '00') are not a copy-move signal
            if True:
                if True:
                    s = _pair_score(gray, a, b, sig)
                    if s < 0.40:
                        out.append(Finding(
                            id=new_id(), check="copy_move", family="visual", sensor="copy_move",
                            title=f"A glyph in '{a['word'].text}' is a pixel copy of a glyph in '{b['word'].text}'",
                            detail=(f"The paper grain around the two glyphs is identical (normalized difference {s:.2f}; "
                                    f"independent scanned glyphs on this page score about 0.67). Scanner noise is random, "
                                    "so identical grain means one patch was copied onto the other after scanning."),
                            confidence=round(float(np.clip(0.97 - 0.5 * s, 0.8, 0.97)), 2), localized=True,
                            evidence=[Evidence(doc.doc_id, P.index, tuple(float(v) for v in a["bbox"]),
                                               "glyph A (suspected paste)", value=a["word"].text),
                                      Evidence(doc.doc_id, P.index, tuple(float(v) for v in b["bbox"]),
                                               "glyph B (identical grain)", value=b["word"].text)],
                            docs=[doc.doc_id]))
        doc.capabilities["copy_move"] = f"ok ({len(gl)} digit glyphs, {pairs} pairs compared)"
    return _merge(out)


def _merge(fs: list[Finding]) -> list[Finding]:
    """One finding per pair of words (a token can have several copied glyphs)."""
    by = {}
    for f in fs:
        k = tuple(sorted([f.evidence[0].value + str(f.evidence[0].bbox[1] // 10), f.evidence[1].value + str(f.evidence[1].bbox[1] // 10)]))
        if k not in by:
            by[k] = f
    return list(by.values())
