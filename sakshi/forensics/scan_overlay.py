"""Overlay peel (v1.0): what is drawn ON TOP of a scanned PDF, and what the scan says underneath.

The most common real-world edit is not pixel work. Someone opens a scanned payslip in a PDF editor,
draws a white box over the net pay and types a new number. The scanned image inside the file is
untouched: the original value is still there, only hidden. SAKSHI renders the page the way a
reader sees it, extracts the bare scan from the same file, and compares the two at every place
the PDF draws something over the scan. Both panels of the evidence image are real pixels from
the submitted file; nothing is generated.

  ink hidden under the overlay + a different value on top  -> smoking gun (value replaced)
  ink hidden under the overlay, no number involved          -> inconsistency (could be a stamp)
  text on blank paper                                      -> observation (e-sign stamp, annotation),
                                                              inconsistency if it sits on an extracted value
"""
from __future__ import annotations

import re
from pathlib import Path

import cv2
import numpy as np
import pytesseract

from ..fonts import label_font
from ..models import Document, Evidence, Finding

NUM = re.compile(r"\d[\d,]*(?:\.\d+)?")


def _merge(objs, gap=6):
    boxes = [list(o["bbox"]) + [o] for o in objs]
    groups = []
    for b in boxes:
        for g in groups:
            if b[0] <= g["bbox"][2] + gap and b[2] >= g["bbox"][0] - gap and b[1] <= g["bbox"][3] + gap and b[3] >= g["bbox"][1] - gap:
                g["bbox"] = [min(g["bbox"][0], b[0]), min(g["bbox"][1], b[1]), max(g["bbox"][2], b[2]), max(g["bbox"][3], b[3])]
                g["objs"].append(b[4])
                break
        else:
            groups.append({"bbox": b[:4], "objs": [b[4]]})
    return groups


def _ocr_line(gray):
    if gray.size == 0:
        return ""
    big = cv2.resize(gray, None, fx=2, fy=2, interpolation=cv2.INTER_CUBIC)
    big = cv2.copyMakeBorder(big, 12, 12, 12, 12, cv2.BORDER_CONSTANT, value=255)
    try:
        return " ".join(pytesseract.image_to_string(big, config="--oem 1 --psm 7").split())
    except Exception:
        return ""


def _num(s):
    m = NUM.search(s or "")
    if not m:
        return None
    try:
        return float(m.group(0).replace(",", ""))
    except ValueError:
        return None


def _panel(render, base, bb, out_path):
    from PIL import Image, ImageDraw
    H, W = base.shape[:2]
    x0, y0, x1, y1 = (int(v) for v in bb)
    m = max(30, int(1.5 * (y1 - y0)))
    cx0, cy0, cx1, cy1 = max(0, x0 - 4 * m), max(0, y0 - m), min(W, x1 + 2 * m), min(H, y1 + m)
    a = Image.fromarray(render[cy0:cy1, cx0:cx1])
    b = Image.fromarray(base[cy0:cy1, cx0:cx1])
    for im in (a, b):
        ImageDraw.Draw(im).rectangle([x0 - cx0 - 3, y0 - cy0 - 3, x1 - cx0 + 3, y1 - cy0 + 3], outline=(200, 40, 40), width=3)
    small = label_font(18, bold=True)
    bar = 30
    canvas = Image.new("RGB", (a.width * 2 + 12, a.height + bar), (255, 255, 255))
    canvas.paste(a, (0, bar))
    canvas.paste(b, (a.width + 12, bar))
    dc = ImageDraw.Draw(canvas)
    dc.text((6, 6), "WHAT A READER SEES (PDF as rendered)", font=small, fill=(160, 30, 30))
    dc.text((a.width + 18, 6), "THE SCAN INSIDE THE SAME FILE, UNDERNEATH", font=small, fill=(20, 110, 60))
    if canvas.width > 1400:
        canvas = canvas.resize((1400, int(canvas.height * 1400 / canvas.width)))
    canvas.save(str(out_path), quality=88)
    return str(out_path)


def analyse(doc: Document, new_id, evidence_dir: Path | None = None) -> list[Finding]:
    out = []
    layers = doc.structure.get("scan_overlays", [])
    if not layers:
        doc.capabilities["scan_overlay"] = "ok (nothing drawn over the scan)" if doc.modality == "scanned_pdf" else "n/a"
        return out
    n_groups = 0
    for L in layers:
        P = doc.pages[L["page"]]
        render = cv2.cvtColor(cv2.imread(P.image_path), cv2.COLOR_BGR2RGB)
        base = cv2.cvtColor(cv2.imread(L["base_image"]), cv2.COLOR_BGR2RGB)
        if render.shape != base.shape:
            base = cv2.resize(base, (render.shape[1], render.shape[0]))
        gr, gb = cv2.cvtColor(render, cv2.COLOR_RGB2GRAY), cv2.cvtColor(base, cv2.COLOR_RGB2GRAY)
        H, W = gr.shape
        for g in _merge(L["objects"]):
            n_groups += 1
            x0, y0, x1, y1 = (int(round(v)) for v in g["bbox"])
            x0, y0, x1, y1 = max(0, x0 - 3), max(0, y0 - 3), min(W, x1 + 3), min(H, y1 + 3)
            if x1 - x0 < 4 or y1 - y0 < 4:
                continue
            r, b = gr[y0:y1, x0:x1], gb[y0:y1, x0:x1]
            area = r.size
            hidden = int(((b < 130) & (r > 200)).sum())   # scan ink that the reader can no longer see
            added = int(((r < 130) & (b > 200)).sum())    # ink that exists only in the PDF layer
            if hidden + added < 15:
                continue  # the drawing does not change what a reader sees (e.g. invisible frame)
            over = " ".join(o["text"] for o in g["objs"] if o["text"]).strip() or _ocr_line(r)
            under = _ocr_line(b) if hidden >= max(25, 0.01 * area) else ""
            on_field = next((f for f in doc.fields.values() if f.page == P.index and f.bbox[0] < x1 and f.bbox[2] > x0
                             and f.bbox[1] < y1 and f.bbox[3] > y0), None)
            nv, nu = _num(over), _num(under)
            crop = ""
            if evidence_dir is not None:
                crop = _panel(render, base, (x0, y0, x1, y1), Path(evidence_dir) / f"{doc.doc_id}_p{P.index}_peel_{n_groups}.jpg")
            ev = [Evidence(doc.doc_id, P.index, (x0, y0, x1, y1), "drawn over the scan" + (f": '{over}'" if over else ""),
                           kind="peel", crop=crop, value=over),
                  Evidence(doc.doc_id, P.index, (x0, y0, x1, y1), "region as submitted", kind="region", value=over)]
            kinds = sorted({o["kind"] for o in g["objs"]})
            # Guards. (1) Redaction: masking characters on top, or a dark box with nothing on top,
            # hides information on purpose; that is recorded, never treated as a replaced value.
            hidden_mask = ((b < 130) & (r > 200)).astype(np.uint8)
            n_cc, _, st_cc, _ = cv2.connectedComponentsWithStats(hidden_mask)
            # (2) the hidden ink must look like characters (several stroke-sized blobs), not logo shading or a rule line
            charlike = sum(1 for k in range(1, n_cc) if 6 <= st_cc[k][3] <= 3 * (y1 - y0) and st_cc[k][4] >= 8) >= 2
            dark_box = float(np.median(r)) < 80
            masked = bool(re.search(r"[xX*#]{3,}|redact|masked", over or "")) or (dark_box and not (over or "").strip())
            region = {"page": P.index, "bbox": [x0, y0, x1, y1], "text": over, "benign": False, "why": ""}
            doc.structure.setdefault("overlay_regions", []).append(region)
            if hidden >= max(25, 0.01 * area) and (masked or not charlike):
                region.update(benign=True, why="redaction drawn in the PDF" if masked else "PDF shape over non-text marks")
                if masked:
                    doc.structure["redacted"] = True
                out.append(Finding(
                    id=new_id(), check="scan_annotation", family="file_structure", sensor="scan_overlay",
                    title=(f"Part of the scan is masked in the PDF ({'redaction' if masked else 'non-text marks covered'})"
                           + (f": '{over[:40]}'" if over else "")),
                    detail=("A shape drawn over the scan hides " + ("characters on purpose (masking characters or a dark box). "
                            "Redacting one's own identifiers is common; ask for the unredacted copy if that value matters."
                            if masked else "marks that are not characters (logo shading, a rule line). Recorded only.")),
                    confidence=0.4, localized=True, evidence=ev, fields=[], docs=[doc.doc_id],
                    repair={"seen": over, "underneath": "", "has_number": False, "redaction": masked}))
                continue
            if hidden >= max(25, 0.01 * area):
                def numlike(t):
                    t = (t or "").replace(" ", "")
                    return bool(t) and sum(ch.isdigit() or ch in ",.-/" for ch in t) / len(t) >= 0.7
                replaced = (nv is not None and nu is not None and abs(nv - nu) > 0.5
                            and numlike(over) and numlike(under))
                if replaced and on_field:
                    doc.structure.setdefault("peeled", []).append({"ref": on_field.key(), "value": nu, "seen": nv})
                title = (f"The PDF hides part of the scan under '{over or 'a drawn shape'}'; the scanned paper underneath reads "
                         f"'{under or '(unreadable ink)'}'")
                out.append(Finding(
                    id=new_id(), check="overlay_hides_scan", family="file_structure", sensor="scan_overlay",
                    title=title,
                    detail=(f"This page is a scanned image with {', '.join(kinds)} drawn on top of it inside the PDF. Under that "
                            f"drawing, {hidden} pixels of scanned ink are hidden from a reader. Peeling the drawing off (reading "
                            f"the image stored in the same file) shows '{under or 'ink that OCR cannot read'}' where the reader "
                            f"sees '{over or '(a shape)'}'."
                            + (" A different number was typed over the number on the scanned paper." if replaced else "")),
                    confidence=0.95 if replaced else 0.75, localized=True, smoking_gun=replaced,
                    evidence=ev, fields=[on_field.key()] if on_field else [], docs=[doc.doc_id],
                    repair={"seen": over, "underneath": under, "recovered_value": (under if replaced else None),
                            "has_number": nv is not None},
                    verify_next="Ask the issuer for the original file; compare against the value peeled from underneath."))
            else:
                if not on_field:
                    region.update(benign=True, why="annotation / stamp drawn in the PDF over blank paper")
                out.append(Finding(
                    id=new_id(), check="overlay_on_value" if on_field else "scan_annotation", family="file_structure",
                    sensor="scan_overlay",
                    title=(f"'{over}' exists only as a layer drawn on top of the scan, not on the scanned paper"
                           if on_field else f"Text added on top of the scan: '{over[:60]}'"),
                    detail=("The scanned image underneath is blank paper at this spot. "
                            + ("An extracted value lives only in the PDF layer, so it was not on the paper that was scanned."
                               if on_field else "Typical of an e-sign stamp, a page number or an annotation added after scanning.")),
                    confidence=0.7 if on_field else 0.4, localized=True, evidence=ev,
                    fields=[on_field.key()] if on_field else [], docs=[doc.doc_id],
                    repair={"seen": over, "underneath": "", "has_number": nv is not None}))
    doc.capabilities["scan_overlay"] = f"ok ({n_groups} object group(s) drawn over the scan, peeled and compared)"
    return out
