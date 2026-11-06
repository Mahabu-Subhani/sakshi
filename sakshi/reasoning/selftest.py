"""Forgery canaries: per-document self-calibration of the pixel sensors.

Before trusting a sensor's silence on an uploaded document, SAKSHI forges that
document itself, in memory, using the document's own pixels (same-source, so
texture and compression match by construction, which fixes a weakness of
the first version of this idea):

  copy-move canary  - copy a real digit glyph from one value onto another value's digit
  white-out canary  - flatten the paper between the glyphs of one value

If a sensor cannot catch its own canary on this document, its silence means
nothing here and the dossier says so ("blind on this document").
Digital PDFs get a layer canary: an in-memory white-box edit.
"""
from __future__ import annotations

import random

import cv2
import numpy as np
import pymupdf as fitz

from ..forensics import copy_move, noise, pdf_layers
from ..ingest import open_pdf


def run(doc, seed: int = 7) -> dict:
    rnd = random.Random(seed)
    out = {}
    if doc.modality == "digital_pdf":
        out["pdf_layers"] = _pdf_canary(doc)
        return out
    P = doc.pages[0]
    if P.noise_sigma < 1.5:
        return {"copy_move": "skipped (page has no measurable sensor noise)",
                "noise": "skipped (page has no measurable sensor noise)"}
    gray = cv2.cvtColor(cv2.imread(P.image_path), cv2.COLOR_BGR2GRAY)
    # copy-move canaries
    gl = copy_move.digit_glyphs(gray, P.words)
    hits, tries = 0, 0
    by_size = {}
    for g in gl:
        by_size.setdefault((g["w"], g["h"]), []).append(g)
    pools = [v for v in by_size.values() if len(v) >= 2]
    rnd.shuffle(pools)
    for pool in pools[:4]:
        a, b = rnd.sample(pool, 2)
        canvas = gray.copy()
        x0, y0, x1, y1 = b["bbox"]
        sx0, sy0 = a["bbox"][:2]
        canvas[y0:y1, x0:x1] = gray[sy0:sy0 + (y1 - y0), sx0:sx0 + (x1 - x0)]
        tries += 1
        if copy_move._pair_score(canvas, a, b, P.noise_sigma) < 0.40:
            hits += 1
    out["copy_move"] = f"{hits}/{tries} canaries caught" if tries else "no glyph pairs available"
    # white-out canaries on numeric value boxes
    vals = [f for f in doc.fields.values() if f.kind in ("amount", "date", "id") and f.page == 0]
    rnd.shuffle(vals)
    hits, tries = 0, 0
    for f in vals[:3]:
        canvas = gray.copy()
        x0, y0, x1, y1 = (int(v) for v in f.bbox)
        reg = canvas[y0 - 4:y1 + 4, x0 - 4:x1 + 4]
        if reg.size == 0:
            continue
        paper = reg > 150
        med = int(np.median(reg[paper])) if paper.any() else 240
        reg[paper] = med
        s, _ = noise.field_noise(canvas, f.bbox)
        s0, _ = noise.field_noise(gray, f.bbox)
        if s is None or s0 is None:
            continue
        tries += 1
        if s < 0.35 * s0:
            hits += 1
    out["noise"] = f"{hits}/{tries} canaries caught" if tries else "no value boxes available"
    return out


def _pdf_canary(doc) -> str:
    try:
        pdf = open_pdf(doc.path)
        page = pdf[0]
        words = [w for w in page.get_text("words") if any(c.isdigit() for c in w[4])]
        if not words:
            return "no numeric text to forge"
        w = words[len(words) // 2]
        r = fitz.Rect(w[:4])
        page.draw_rect(r, color=None, fill=(1, 1, 1), overlay=True)
        page.insert_text(fitz.Point(r.x0, r.y1 - 1), "99,999.00", fontsize=max(6, r.height * 0.8), overlay=True)
        tt = page.get_texttrace()
        dr = [d for d in page.get_drawings() if d.get("fill") is not None]
        last = max(d["seqno"] for d in dr)
        shape = next(d for d in dr if d["seqno"] == last)
        under = [s for s in tt if s["seqno"] < last and pdf_layers._rect_overlap(tuple(s["bbox"]), tuple(shape["rect"])) > 0.6]
        pdf.close()
        return "1/1 canaries caught" if under else "0/1 canaries caught"
    except Exception as e:  # never let a self-test crash the case
        return f"canary failed to run ({type(e).__name__})"
