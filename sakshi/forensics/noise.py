"""Sensor-noise consistency (scans and photos).

A genuine scan is captured in one pass, so the sensor noise in flat paper areas
is statistically the same everywhere on the page. A region pasted in afterwards
(a white-out patch, a replaced photo) carries a different noise history: too
clean, too smooth, or differently compressed.

Per 16x16 window (stride 8) we estimate noise from the median-filter residual on
flat pixels only (edges excluded), then flag compact rectangular regions whose
noise is far below or above the page's own level.

Guards: saturated blocks are ignored (clipping hides noise),
long thin regions (creases, folds) are dropped, and the sensor declares itself
not applicable on born-digital renders, which have no sensor noise at all.
"""
from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np

from ..models import Document, Evidence, Finding

WIN, STRIDE = 16, 8


def noise_map(gray: np.ndarray):
    g = gray.astype(np.float32)
    med = cv2.medianBlur(gray, 3).astype(np.float32)
    res = g - med
    blur = cv2.GaussianBlur(g, (0, 0), 1.5)
    gx = cv2.Sobel(blur, cv2.CV_32F, 1, 0, ksize=3)
    gy = cv2.Sobel(blur, cv2.CV_32F, 0, 1, ksize=3)
    flat = (np.hypot(gx, gy) < 18) & (g > 18) & (g < 250)
    f = flat.astype(np.float32)
    # mean absolute residual over flat pixels in each window (box filters, vectorized);
    # sqrt(pi/2) * mean|r| estimates sigma for Gaussian noise.
    s_abs = cv2.boxFilter(np.abs(res) * f, -1, (WIN, WIN), normalize=False, anchor=(0, 0),
                          borderType=cv2.BORDER_CONSTANT)
    s_n = cv2.boxFilter(f, -1, (WIN, WIN), normalize=False, anchor=(0, 0), borderType=cv2.BORDER_CONSTANT)
    H, W = gray.shape
    s_abs = s_abs[: H - WIN + 1: STRIDE, : W - WIN + 1: STRIDE]
    s_n = s_n[: H - WIN + 1: STRIDE, : W - WIN + 1: STRIDE]
    with np.errstate(invalid="ignore", divide="ignore"):
        est = np.sqrt(np.pi / 2) * s_abs / s_n * 1.6  # 1.6: median-3 residual underestimates sigma
    est[s_n < 0.55 * WIN * WIN] = np.nan
    return est.astype(np.float32)


def page_sigma(gray: np.ndarray) -> float:
    est = noise_map(gray)
    v = est[np.isfinite(est)]
    return float(np.median(v)) if v.size else 0.0


def _components(mask: np.ndarray):
    n, lab, stats, _ = cv2.connectedComponentsWithStats(mask.astype(np.uint8), connectivity=8)
    return [(stats[i], lab == i) for i in range(1, n)]


def analyse(doc: Document, new_id, ev_dir: Path) -> list[Finding]:
    out: list[Finding] = []
    if doc.modality == "digital_pdf":
        doc.capabilities["noise"] = "n/a (born-digital render has no sensor noise)"
        return out
    for P in doc.pages:
        rgb = cv2.imread(P.image_path)[:, :, ::-1]
        gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
        est = noise_map(gray)
        valid = est[np.isfinite(est)]
        if valid.size < 50:
            doc.capabilities["noise"] = "blind (too few flat regions)"
            continue
        sig = float(np.median(valid))
        P.noise_sigma = sig
        if sig < 1.2:
            doc.capabilities["noise"] = f"blind (page noise sigma {sig:.2f} too low: likely a digital export, not a scan)"
            continue
        ratio = est / sig
        low = np.nan_to_num(ratio, nan=1.0) < 0.42
        high = np.nan_to_num(ratio, nan=1.0) > 3.0
        # heatmap for the dossier
        hm = np.nan_to_num(np.clip(ratio, 0, 2) / 2.0, nan=0.5)
        hm = cv2.resize((hm * 255).astype(np.uint8), (gray.shape[1], gray.shape[0]), interpolation=cv2.INTER_NEAREST)
        heat = cv2.applyColorMap(255 - hm, cv2.COLORMAP_JET)
        blend = cv2.addWeighted(rgb[:, :, ::-1], 0.55, heat, 0.45, 0)
        hp = ev_dir / f"{doc.doc_id}_p{P.index}_noise.jpg"
        cv2.imwrite(str(hp), blend, [cv2.IMWRITE_JPEG_QUALITY, 70])
        doc.capabilities["noise"] = "ok"
        doc.structure.setdefault("artifacts", {})[f"noise_heatmap_p{P.index}"] = str(hp)
        for kind, mask in (("too clean", low), ("too noisy", high)):
            for st, comp in _components(mask):
                x, y, w, h, area = st
                if area < (6 if kind == "too clean" else 16):
                    continue
                bw, bh = w * STRIDE + WIN, h * STRIDE + WIN
                fill = area / float(w * h)
                aspect = max(bw, bh) / max(1, min(bw, bh))
                if aspect > 9 or fill < 0.35:
                    continue  # creases, folds, scattered texture
                bbox = (x * STRIDE, y * STRIDE, x * STRIDE + bw, y * STRIDE + bh)
                inside = est[y:y + h, x:x + w][comp[y:y + h, x:x + w]]
                rs = float(np.nanmedian(inside))
                conf = float(np.clip(0.55 + 0.4 * (1 - min(rs / sig, 1.0)) if kind == "too clean"
                                     else 0.5 + 0.1 * (rs / sig - 2.6), 0.5, 0.95))
                out.append(Finding(
                    id=new_id(), check="noise_inconsistency", family="visual", sensor="noise",
                    title=f"Region is {kind} for this scan: noise {rs:.1f} vs page {sig:.1f}",
                    detail=(f"Every flat paper area on this page carries sensor noise of about {sig:.1f} grey levels. "
                            f"This {bw}x{bh}px rectangular region measures {rs:.1f}. A region that was {('painted or pasted in digitally' if kind == 'too clean' else 'imported from a noisier source')} "
                            "after scanning has a different noise history from the rest of the page."),
                    confidence=round(conf, 2), localized=True,
                    evidence=[Evidence(doc.doc_id, P.index, tuple(float(v) for v in bbox), f"noise {rs:.1f} vs {sig:.1f}",
                                       crop=str(hp))],
                    docs=[doc.doc_id]))
        out += field_level(doc, P, gray, sig, new_id, str(hp))
    return out


def field_noise(gray: np.ndarray, bbox, pad: int = 5):
    """Noise inside one field's value box, measured only on paper pixels between glyphs."""
    H, W = gray.shape
    x0, y0 = max(0, int(bbox[0]) - pad), max(0, int(bbox[1]) - pad)
    x1, y1 = min(W, int(bbox[2]) + pad), min(H, int(bbox[3]) + pad)
    g = gray[y0:y1, x0:x1].astype(np.float32)
    if g.size < 200:
        return None, 0
    res = g - cv2.medianBlur(gray[y0:y1, x0:x1], 3).astype(np.float32)
    blur = cv2.GaussianBlur(g, (0, 0), 1.2)
    grad = np.hypot(cv2.Sobel(blur, cv2.CV_32F, 1, 0, ksize=3), cv2.Sobel(blur, cv2.CV_32F, 0, 1, ksize=3))
    ink = cv2.dilate((g < 150).astype(np.uint8), np.ones((5, 5), np.uint8)) > 0
    flat = (grad < 14) & ~ink & (g < 250)
    n = int(flat.sum())
    if n < 120:
        return None, n
    v = res[flat]
    return 1.6 * 1.4826 * float(np.median(np.abs(v - np.median(v)))) + 1e-6, n


def field_level(doc: Document, P, gray, sig, new_id, heat_path) -> list[Finding]:
    """Targeted check on every extracted value box: forgers edit values, not margins."""
    out = []
    vals = []
    for f in doc.fields.values():
        if f.page != P.index or f.kind not in ("amount", "date", "id", "int"):
            continue
        s, n = field_noise(gray, f.bbox)
        if s is not None:
            vals.append((f, s, n))
    if len(vals) < 4:
        return out
    ref = float(np.median([s for _, s, _ in vals]))
    ref = max(ref, 0.6 * sig)
    for f, s, n in vals:
        r = s / ref
        if r < 0.35:
            out.append(Finding(
                id=new_id(), check="noise_inconsistency", family="visual", sensor="noise",
                title=f"Paper around '{f.raw}' is unnaturally clean: noise {s:.1f} vs {ref:.1f} around other values",
                detail=(f"Between the glyphs of this value, the paper carries {s:.1f} grey levels of noise, against "
                        f"{ref:.1f} around the other {len(vals) - 1} values on the page (page-wide {sig:.1f}). "
                        "This is what a digital white-out or pasted patch looks like: the scanner's noise is gone."),
                confidence=round(float(np.clip(0.6 + 0.4 * (1 - r / 0.35), 0.6, 0.95)), 2), localized=True,
                evidence=[Evidence(doc.doc_id, P.index, f.bbox, f"value-box noise {s:.1f} vs {ref:.1f}", kind="field",
                                   value=f.raw, crop=heat_path)],
                fields=[f.key()], docs=[doc.doc_id]))
    return out
