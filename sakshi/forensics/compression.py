# FILE: sakshi/forensics/compression.py
# Written by Gemini 4 Argon (round 2 of the v1.0 design debate). Integrated and tested by Claude.
from __future__ import annotations

from typing import Iterable, Sequence

import cv2
import numpy as np


def jpeg_ghosts(
    gray: np.ndarray,
    boxes: Sequence[tuple[int, int, int, int]],
    qualities: Iterable[int] = range(50, 100, 5),
) -> list[dict]:
    if gray.ndim != 2 or gray.dtype != np.uint8:
        raise ValueError("gray must be 2D uint8 array")

    h, w = gray.shape
    q_list = list(qualities)
    if not q_list or not boxes:
        return []

    valid_boxes: list[tuple[int, int, int, int]] = []
    for x0, y0, x1, y1 in boxes:
        x0c, y0c = max(0, int(x0)), max(0, int(y0))
        x1c, y1c = min(w, int(x1)), min(h, int(y1))
        if (x1c - x0c) * (y1c - y0c) >= 400:
            valid_boxes.append((x0c, y0c, x1c, y1c))

    if len(valid_boxes) < 3:
        return []

    # Local gradient magnitude + 1 (computed once in float32)
    gx = cv2.Sobel(gray, cv2.CV_32F, 1, 0, ksize=3)
    gy = cv2.Sobel(gray, cv2.CV_32F, 0, 1, ksize=3)
    grad_denom = cv2.magnitude(gx, gy) + 1.0
    gray_f = gray.astype(np.float32)

    num_q = len(q_list)
    num_b = len(valid_boxes)
    err_matrix = np.zeros((num_b, num_q), dtype=np.float32)

    # Full page re-encode once per quality; integral image for O(1) box queries
    for qi, q in enumerate(q_list):
        ok, enc = cv2.imencode(".jpg", gray, [int(cv2.IMWRITE_JPEG_QUALITY), int(q)])
        if not ok:
            continue
        dec = cv2.imdecode(enc, cv2.IMREAD_GRAYSCALE).astype(np.float32)
        diff = gray_f - dec
        norm_sq_err = (diff * diff) / grad_denom
        integ = cv2.integral(norm_sq_err, sdepth=cv2.CV_64F)

        for bi, (x0, y0, x1, y1) in enumerate(valid_boxes):
            area = float((x1 - x0) * (y1 - y0))
            box_sum = integ[y1, x1] - integ[y0, x1] - integ[y1, x0] + integ[y0, x0]
            err_matrix[bi, qi] = box_sum / area

    # Per-box zero-mean / unit-std across qualities so ghost dip is scale-invariant
    b_mean = err_matrix.mean(axis=1, keepdims=True)
    b_std = err_matrix.std(axis=1, keepdims=True) + 1e-6
    norm_curves = (err_matrix - b_mean) / b_std

    # Exclude quality=95+ edge effect if highest quality trivially minimizes all curves
    search_len = num_q - 1 if (num_q > 2 and q_list[-1] >= 95) else num_q
    q_star_indices = np.argmin(err_matrix[:, :search_len], axis=1)
    page_q_idx = int(np.median(q_star_indices))
    q_star_page = int(q_list[page_q_idx])

    # Compare each box's normalized response at the page's ghost quality
    at_page_q = norm_curves[:, page_q_idx]
    med = float(np.median(at_page_q))
    mad = float(np.median(np.abs(at_page_q - med)))
    scale = 1.4826 * mad if mad > 1e-5 else float(np.std(at_page_q)) + 1e-5

    out: list[dict] = []
    for bi, bbox in enumerate(valid_boxes):
        z = float(abs(at_page_q[bi] - med) / scale)
        q_box = int(q_list[q_star_indices[bi]])
        if z > 4.0 and q_box != q_star_page:
            out.append({
                "bbox": bbox,
                "q_star_box": q_box,
                "q_star_page": q_star_page,
                "z": round(z, 2),
                "note": f"JPEG ghost mismatch: box Q*={q_box} vs page Q*={q_star_page} (z={z:.1f})",
            })
    return out


def zero_variance_patches(
    gray: np.ndarray,
    boxes: Sequence[tuple[int, int, int, int]],
    pad: int = 6,
) -> list[dict]:
    """Paper noise inside a value box vs a ring around it.

    Claude's review fix: the first version measured raw std over the box *plus* its pad, so a flat
    patch smaller than the pad mixed flat and noisy pixels (and a brightness step between them) into
    one std and was missed. Now the inner region is the box itself, the ring starts outside the pad,
    and noise is the robust MAD of the median-filter residual, which ignores brightness steps.
    """
    if gray.ndim != 2 or gray.dtype != np.uint8:
        raise ValueError("gray must be 2D uint8 array")

    h, w = gray.shape
    ink_mask = (gray <= 150).astype(np.uint8)
    kernel = np.ones((5, 5), dtype=np.uint8)  # 5x5 dilate = within 2 px of ink
    near_ink = cv2.dilate(ink_mask, kernel, iterations=1)
    paper_mask = near_ink == 0
    resid = gray.astype(np.float32) - cv2.medianBlur(gray, 3).astype(np.float32)

    def robust(v: np.ndarray) -> float:
        return float(1.4826 * np.median(np.abs(v - np.median(v)))) * 1.6

    out: list[dict] = []
    ring_w = 10
    for x0, y0, x1, y1 in boxes:
        ix0, iy0 = max(0, int(x0)), max(0, int(y0))
        ix1, iy1 = min(w, int(x1)), min(h, int(y1))
        ox0, oy0 = max(0, ix0 - pad), max(0, iy0 - pad)
        ox1, oy1 = min(w, ix1 + pad), min(h, iy1 + pad)
        rx0, ry0 = max(0, ox0 - ring_w), max(0, oy0 - ring_w)
        rx1, ry1 = min(w, ox1 + ring_w), min(h, oy1 + ring_w)
        if ix1 <= ix0 or iy1 <= iy0:
            continue

        roi_res = resid[ry0:ry1, rx0:rx1]
        roi_paper = paper_mask[ry0:ry1, rx0:rx1]
        inner_mask = np.zeros_like(roi_paper, dtype=bool)
        inner_mask[iy0 - ry0: iy1 - ry0, ix0 - rx0: ix1 - rx0] = True
        outer_mask = np.zeros_like(roi_paper, dtype=bool)
        outer_mask[oy0 - ry0: oy1 - ry0, ox0 - rx0: ox1 - rx0] = True

        inner_pixels = roi_res[inner_mask & roi_paper]
        ring_pixels = roi_res[(~outer_mask) & roi_paper]
        if inner_pixels.size < 20 or ring_pixels.size < 20:
            continue

        inner_std = robust(inner_pixels)
        ring_std = robust(ring_pixels)

        if ring_std > 1.5 and inner_std < 0.25 * ring_std:
            out.append({
                "bbox": (int(x0), int(y0), int(x1), int(y1)),
                "inner_std": round(inner_std, 3),
                "ring_std": round(ring_std, 3),
                "note": f"Erasure patch: paper noise {inner_std:.2f} inside vs {ring_std:.2f} around",
            })
    return out


if __name__ == "__main__":
    import time
    rng = np.random.default_rng(42)
    # 1. Base noisy page with synthetic text lines, compressed at Q=75
    page = rng.normal(235, 6.0, (2339, 1654)).clip(0, 255).astype(np.uint8)
    for y in range(150, 2200, 45):
        cv2.putText(page, "INR 45,200.00 NEFT CR AXIS", (100, y), cv2.FONT_HERSHEY_SIMPLEX, 0.8, 30, 2)
    _, buf75 = cv2.imencode(".jpg", page, [int(cv2.IMWRITE_JPEG_QUALITY), 75])
    page = cv2.imdecode(buf75, cv2.IMREAD_GRAYSCALE)

    boxes = [(100 + (i % 4) * 350, 120 + (i // 4) * 180, 380 + (i % 4) * 350, 175 + (i // 4) * 180) for i in range(40)]

    # 2. Box 0: flat white patch (MS Paint erasure) with fresh text
    x0, y0, x1, y1 = boxes[0]
    page[y0 - 4: y1 + 4, x0 - 4: x1 + 4] = 242
    cv2.putText(page, "99,000.00", (x0 + 10, y1 - 12), cv2.FONT_HERSHEY_SIMPLEX, 0.8, 25, 2)

    # 3. Box 1: spliced region from a Q=60 JPEG
    gx0, gy0, gx1, gy1 = boxes[1]
    patch_src = rng.normal(230, 8.0, (gy1 - gy0, gx1 - gx0)).clip(0, 255).astype(np.uint8)
    cv2.putText(patch_src, "85,000.00", (10, 40), cv2.FONT_HERSHEY_SIMPLEX, 0.8, 35, 2)
    _, buf60 = cv2.imencode(".jpg", patch_src, [int(cv2.IMWRITE_JPEG_QUALITY), 60])
    page[gy0:gy1, gx0:gx1] = cv2.imdecode(buf60, cv2.IMREAD_GRAYSCALE)

    t0 = time.perf_counter()
    zv_hits = zero_variance_patches(page, boxes)
    jg_hits = jpeg_ghosts(page, boxes)
    dt_ms = (time.perf_counter() - t0) * 1000.0

    assert any(h["bbox"] == boxes[0] for h in zv_hits), f"Missed flat patch: {zv_hits}"
    assert not any(h["bbox"] == boxes[2] for h in zv_hits), "Clean box triggered ZV"
    assert any(h["bbox"] == boxes[1] for h in jg_hits), f"Missed JPEG ghost: {jg_hits}"
    assert not any(h["bbox"] == boxes[2] for h in jg_hits), "Clean box triggered JG"
    print(f"PASS in {dt_ms:.1f} ms | ZV={len(zv_hits)} | JG={len(jg_hits)}")
