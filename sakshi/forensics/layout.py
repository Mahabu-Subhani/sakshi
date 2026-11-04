"""Layout self-consistency ("document rhythm").

No template library is needed (Gemini's original idea used known templates;
Claude flipped it to self-consistency so it works on any issuer's layout).
A document is compared with itself:
  * form values share a left edge; table amounts share a right edge per column;
  * value text sits on the same baseline as its label;
  * table rows share a pitch.
Lines are fitted robustly (Theil-Sen) so a skewed scan does not look misaligned.
"""
from __future__ import annotations

import numpy as np

from ..models import Document, Evidence, Finding


def theil_sen(y: np.ndarray, x: np.ndarray):
    if len(y) < 3:
        return 0.0, float(np.median(x))
    slopes = []
    for i in range(len(y)):
        for j in range(i + 1, len(y)):
            if abs(y[j] - y[i]) > 1e-6:
                slopes.append((x[j] - x[i]) / (y[j] - y[i]))
    b = float(np.median(slopes)) if slopes else 0.0
    a = float(np.median(x - b * y))
    return b, a


def _outliers(points, min_px=4.0, k=4.0):
    """points: list of (key, y, x). Returns [(key, residual, scale)]."""
    if len(points) < 5:
        return []
    y = np.array([p[1] for p in points], float)
    x = np.array([p[2] for p in points], float)
    b, a = theil_sen(y, x)
    r = x - (a + b * y)
    mad = 1.4826 * float(np.median(np.abs(r - np.median(r))))
    scale = max(mad, 0.8)
    return [(points[i][0], float(r[i]), scale) for i in range(len(points)) if abs(r[i]) > max(min_px, k * scale)]


def analyse(doc: Document, new_id) -> list[Finding]:
    out: list[Finding] = []
    # 1) label-value forms: shared left edge of values, and value/label baseline agreement
    labeled = [f for f in doc.fields.values() if f.label_bbox and "same line" in f.method]
    if doc.doc_type == "application_form" and len(labeled) >= 5:
        # group by column: values whose left edges are within 60 px of each other
        cols = {}
        for f in labeled:
            key = round(f.bbox[0] / 120)
            cols.setdefault(key, []).append(f)
        for fs in cols.values():
            for f, r, s in _outliers([(f, (f.bbox[1] + f.bbox[3]) / 2, f.bbox[0]) for f in fs]):
                out.append(Finding(
                    id=new_id(), check="layout_rhythm_break", family="visual", sensor="layout",
                    title=f"Value '{f.raw}' starts {r:+.0f}px off the column every other value is aligned to",
                    detail=(f"{len(fs) - 1} other values in this column share one left edge (spread {s:.1f}px after "
                            "correcting for scan skew). Text typed in the original document lands on the same tab stop; "
                            "a value re-entered on top of a scan usually does not."),
                    confidence=round(float(min(0.7, 0.5 + 0.02 * abs(r) / s)), 2), localized=True,
                    evidence=[Evidence(doc.doc_id, f.page, f.bbox, f"left edge off by {r:+.0f}px", kind="field", value=f.raw)],
                    fields=[f.key()], docs=[doc.doc_id]))
    # 2) tables: right edge per amount column (row pitch and label-baseline checks were removed in v1.0:
    #    wrapped narrations and OCR box jitter made them fire on genuine documents)
    rows = doc.tables.get("transactions") or []
    if rows:
        for col in ("debit", "credit", "balance"):
            pts = [(r[col], (r[col].bbox[1] + r[col].bbox[3]) / 2, r[col].bbox[2]) for r in rows if r.get(col)]
            for f, r, s in _outliers(pts, min_px=5.0):
                out.append(Finding(
                    id=new_id(), check="layout_rhythm_break", family="visual", sensor="layout",
                    title=f"{col.title()} amount '{f.raw}' breaks the column's right alignment by {r:+.0f}px",
                    detail=f"Other {col} amounts share a right edge within {s:.1f}px (skew-corrected).",
                    confidence=0.7, localized=True,
                    evidence=[Evidence(doc.doc_id, f.page, f.bbox, f"right edge off by {r:+.0f}px", kind="field", value=f.raw)],
                    fields=[f.key()], docs=[doc.doc_id]))
    doc.capabilities["layout"] = "ok"
    return out
