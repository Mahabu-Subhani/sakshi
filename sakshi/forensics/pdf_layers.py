"""PDF layer archaeology (born-digital PDFs only).

The classic digital edit: draw an opaque rectangle over the old value and write
the new value on top. The text layer then still contains the old value, under
the shape, earlier in the content stream. We use the content-stream sequence
numbers of text spans and filled shapes to find text that was painted over,
and recover it.

Also checked: several fonts inside one value, invisible text, incremental
updates (more than one %%EOF), and metadata time travel.

Guard (from Gemini's red team): template-based enterprise PDFs (SAP, Oracle)
legitimately layer text over boxes. We only flag when a *value-like* token
(digits) is occluded *and* a different value is drawn on top inside the same
region.
"""
from __future__ import annotations

import re
from datetime import datetime

import cv2
import pymupdf as fitz

from ..models import Document, Evidence, Finding

VALUE_RE = re.compile(r"\d")


def _rect_overlap(a, b) -> float:
    x0, y0 = max(a[0], b[0]), max(a[1], b[1])
    x1, y1 = min(a[2], b[2]), min(a[3], b[3])
    if x1 <= x0 or y1 <= y0:
        return 0.0
    inter = (x1 - x0) * (y1 - y0)
    area = (a[2] - a[0]) * (a[3] - a[1])
    return inter / area if area > 0 else 0.0


def _pdf_date(s: str):
    m = re.match(r"D:(\d{4})(\d{2})(\d{2})(\d{2})?(\d{2})?", s or "")
    if not m:
        return None
    y, mo, d, h, mi = (int(x) if x else 0 for x in m.groups())
    try:
        return datetime(y, mo, d, h, mi)
    except ValueError:
        return None


def analyse(doc: Document, new_id) -> list[Finding]:
    findings: list[Finding] = []
    if doc.modality != "digital_pdf":
        doc.capabilities["pdf_layers"] = "n/a (not a born-digital PDF)"
        return findings
    pdf = fitz.open(doc.path)
    raw = open(doc.path, "rb").read()
    for pi, page in enumerate(pdf):
        if pi >= len(doc.pages):
            break
        P = doc.pages[pi]
        scale = P.width / page.rect.width
        page_img = cv2.cvtColor(cv2.imread(P.image_path), cv2.COLOR_BGR2GRAY)
        spans = []
        for s in page.get_texttrace():
            txt = "".join(chr(c[0]) for c in s["chars"])
            spans.append({"text": txt, "seq": s["seqno"], "font": s["font"], "size": s["size"],
                          "bbox": tuple(s["bbox"]), "type": s.get("type", 0), "opacity": s.get("opacity", 1.0),
                          "color": s.get("color")})
        shapes = [d for d in page.get_drawings() if d.get("fill") is not None and d["type"] in ("f", "fs")]
        hidden_boxes, hidden_seq, hidden_txt = [], set(), []
        for sh in shapes:
            r = tuple(sh["rect"])
            under = [s for s in spans if s["seq"] < sh["seqno"] and _rect_overlap(s["bbox"], r) > 0.6
                     and VALUE_RE.search(s["text"])]
            over = [s for s in spans if s["seq"] > sh["seqno"] and _rect_overlap(s["bbox"], r) > 0.5]
            if not under:
                continue
            for u in under:
                hidden_boxes.append(u["bbox"])
                hidden_seq.add(u["seq"])
                hidden_txt.append((u["bbox"], set(u["text"].split())))
            if over and any(o["text"].strip() != u["text"].strip() for o in over for u in under):
                u, o = under[0], over[0]
                bb = tuple(v * scale for v in r)
                findings.append(Finding(
                    id=new_id(), check="occluded_text", family="file_structure", sensor="pdf_layers",
                    title=f"Value '{u['text'].strip()}' is hidden under a filled shape; '{o['text'].strip()}' is drawn on top",
                    detail=(f"In the PDF content stream, the text '{u['text'].strip()}' (font {u['font']}, step {u['seq']}) "
                            f"is painted first, then an opaque {sh['fill']} rectangle is drawn over it (step {sh['seqno']}), "
                            f"then '{o['text'].strip()}' (font {o['font']}, size {o['size']:.1f}, step {o['seq']}) is written "
                            "on top. A reader sees only the last value. The original value is recoverable from the file."),
                    confidence=0.97, localized=True, smoking_gun=True,
                    evidence=[Evidence(doc.doc_id, pi, bb, f"occluding rectangle; hidden text '{u['text'].strip()}'",
                                       kind="region", value=u["text"].strip())],
                    docs=[doc.doc_id],
                    repair={"recovered_value": u["text"].strip(), "displayed_value": o["text"].strip()},
                    verify_next="Request the payslip directly from the employer's payroll system or HR mailbox."))
            elif not over:
                findings.append(Finding(
                    id=new_id(), check="occluded_text", family="file_structure", sensor="pdf_layers",
                    title=f"Text '{under[0]['text'].strip()}' is covered by a filled shape",
                    detail="A value-like text span is painted over by an opaque shape with nothing written on top. "
                           "This can be a redaction or a template artefact.",
                    confidence=0.6, localized=True,
                    evidence=[Evidence(doc.doc_id, pi, tuple(v * scale for v in r), "covered text", value=under[0]["text"])],
                    docs=[doc.doc_id]))
        # drop occluded words from what the reader "sees"
        if hidden_boxes:
            keep, hid = [], []
            for w in P.words:
                wb = tuple(v / scale for v in w.bbox)
                if any(_rect_overlap(wb, hb) > 0.6 and w.text in toks for hb, toks in hidden_txt) and \
                        not any(h.text == w.text and h.bbox == w.bbox for h in hid):
                    hid.append(w)
                else:
                    keep.append(w)
            P.words = keep
            P.hidden_words = hid  # type: ignore[attr-defined]
        # invisible / white text
        for s in spans:
            if not s["text"].strip():
                continue
            white = s["color"] is not None and all(c > 0.97 for c in (s["color"] if isinstance(s["color"], (list, tuple)) else [s["color"]]))
            if white:  # white text is only invisible on a white background
                x0, y0, x1, y1 = (int(v * scale) for v in s["bbox"])
                patch = page_img[max(0, y0):y1, max(0, x0):x1]
                white = patch.size > 0 and float(patch.mean()) > 235
            if s["type"] == 3 or s["opacity"] == 0 or white:
                findings.append(Finding(
                    id=new_id(), check="hidden_text", family="file_structure", sensor="pdf_layers",
                    title=f"Invisible text in the file: '{s['text'].strip()[:40]}'",
                    detail="Text exists in the PDF but is rendered invisible (render mode 3, zero opacity or white). "
                           "Scanned PDFs with an OCR layer use this legitimately.",
                    confidence=0.5, localized=True,
                    evidence=[Evidence(doc.doc_id, pi, tuple(v * scale for v in s["bbox"]), "invisible text", value=s["text"])],
                    docs=[doc.doc_id]))
        # font mix inside value-like tokens: compare each numeric span's font to the document's numeric majority
        num = [s for s in spans if re.fullmatch(r"[\d,.\s]+", s["text"].strip() or "x") and s["seq"] not in hidden_seq]
        fams = {}
        for s in num:
            fam = re.split(r"[-,]", s["font"])[0]
            fams[fam] = fams.get(fam, 0) + 1
        if len(fams) > 1:
            major = max(fams, key=fams.get)
            for s in num:
                fam = re.split(r"[-,]", s["font"])[0]
                if fam != major and fams[fam] <= max(1, 0.2 * len(num)):
                    findings.append(Finding(
                        id=new_id(), check="font_mix", family="visual", sensor="pdf_layers",
                        title=f"Amount '{s['text'].strip()}' uses font {s['font']}; every other amount uses {major}",
                        detail=(f"{fams[major]} numeric values on this page are set in {major}. This one is set in "
                                f"{s['font']} at {s['size']:.1f}pt. Payroll engines render every amount with the same font."),
                        confidence=0.85, localized=True,
                        evidence=[Evidence(doc.doc_id, pi, tuple(v * scale for v in s["bbox"]),
                                           f"font {s['font']} vs majority {major}", value=s["text"].strip())],
                        docs=[doc.doc_id]))
    # incremental updates and metadata
    n_eof = raw.count(b"%%EOF")
    meta = doc.pdf_meta
    cd, md = _pdf_date(meta.get("creationDate", "")), _pdf_date(meta.get("modDate", ""))
    if n_eof > 1:
        findings.append(Finding(
            id=new_id(), check="incremental_update", family="file_structure", sensor="pdf_layers",
            title=f"File was modified after it was first written ({n_eof - 1} incremental update{'s' if n_eof > 2 else ''})",
            detail=(f"The PDF contains {n_eof} end-of-file markers: the original file plus appended revisions. "
                    "Editors append changes this way. Some e-sign tools do too, so this alone proves nothing."),
            confidence=0.7, evidence=[Evidence(doc.doc_id, 0, (0, 0, doc.pages[0].width, 40), "file trailer", kind="file")],
            docs=[doc.doc_id]))
    if cd and md and abs((md - cd).total_seconds()) > 60:
        findings.append(Finding(
            id=new_id(), check="metadata_dates", family="file_structure", sensor="pdf_layers",
            title=f"Modified {md:%d-%m-%Y %H:%M}, created {cd:%d-%m-%Y %H:%M}",
            detail="Creation and modification timestamps differ. Payroll systems usually stamp both at generation.",
            confidence=0.5, evidence=[Evidence(doc.doc_id, 0, (0, 0, doc.pages[0].width, 40), "document info dictionary", kind="file")],
            docs=[doc.doc_id]))
    doc.capabilities["pdf_layers"] = "ok"
    pdf.close()
    return findings
