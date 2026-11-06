"""Devil's advocate: every finding must survive its benign explanations.

The catalog (benign_catalog.json) was written by Gemini; each explanation is
paired here with a deterministic test. Results:
  ruled_out    - the test shows this innocent explanation does not apply
  plausible    - the innocent explanation could be true; the finding cannot escalate
  explains     - the innocent explanation fully accounts for it; finding demoted to OBSERVATION
  not_testable - prototype cannot decide; stated honestly in the dossier
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pymupdf as fitz

from ..ingest import open_pdf
from ..models import BenignTest, Finding
from .repair import OCR_MAP, TRANSLIT, levenshtein, name_key

CATALOG = json.loads((Path(__file__).parent / "benign_catalog.json").read_text())


def _cat(check: str, cid: str) -> tuple[str, str]:
    for e in CATALOG.get(check, []):
        if e["id"] == cid:
            return e["explanation"], e["test"]
    return cid, ""


def _bt(check, cid, result, detail=""):
    e, t = _cat(check, cid)
    return BenignTest(explanation=e, test=t, result=result, detail=detail)


def _doc_text(doc) -> str:
    return " ".join(w.text for p in doc.pages for w in p.words).lower()


SCAN_PHYSICS = {"noise_inconsistency", "zero_variance_patch", "compression_ghost", "optics_outlier", "glyph_outlier",
                "intra_token_font", "copy_move", "layout_rhythm_break", "signature_placement", "signature_missing"}


def _benign_overlay(f: Finding, docs: dict):
    """A scan-physics anomaly that sits on a region the overlay sensor already documented as a redaction,
    stamp or annotation drawn in the PDF is explained by that layer (G12: a redaction box is flat)."""
    if f.check not in SCAN_PHYSICS or not f.evidence:
        return None
    e = f.evidence[0]
    d = docs.get(e.doc_id)
    if not d:
        return None
    for r in d.structure.get("overlay_regions", []):
        if not r["benign"] or r["page"] != e.page:
            continue
        b = r["bbox"]
        ix = min(e.bbox[2], b[2] + 4) - max(e.bbox[0], b[0] - 4)
        iy = min(e.bbox[3], b[3] + 4) - max(e.bbox[1], b[1] - 4)
        if ix > 0 and iy > 0 and ix * iy >= 0.5 * max(1.0, (e.bbox[2] - e.bbox[0]) * (e.bbox[3] - e.bbox[1])):
            return r
    return None


def run(f: Finding, docs: dict, ctx: dict) -> list[BenignTest]:
    fields, vals = ctx["fields"], ctx["vals"]
    c = f.check
    T = []
    ov = _benign_overlay(f, docs)
    if ov:
        return [BenignTest("The region is a layer drawn in the PDF, already documented by the overlay sensor",
                           "anomaly coincides with a redaction / stamp / annotation drawn over the scan", "explains",
                           f"{ov['why']}" + (f": '{ov['text'][:40]}'" if ov.get("text") else ""))]
    # safe failure on unseen statement layouts: if SAKSHI could not make the balance equation hold on most rows,
    # a chain break is more likely SAKSHI's misreading than the document's (a judge's real bank statement)
    stmt_checks = {"deleted_row", "balance_chain_break", "statement_totals_mismatch", "recurring_missing",
                   "recurring_amount_mismatch"}
    if c in stmt_checks or (f.sensor == "repair_solver" and stmt_checks & set(f.repair.get("checks", []))):
        fits = []
        for k in f.fields:
            if k in fields and docs[fields[k].doc_id].doc_type == "bank_statement":
                st = docs[fields[k].doc_id].structure
                # prefer the fit over confidently read rows; fall back to the parser's fit
                fits.append(st.get("confident_fit") if st.get("confident_transitions", 0) >= 5 else st.get("transition_fit"))
        fits = [x for x in fits if x is not None]
        if fits and min(fits) < 0.8:
            fit = min(fits)
            T.append(BenignTest("SAKSHI misread an unfamiliar statement layout", "the balance equation holds on at least "
                                "80% of parsed rows", "explains" if fit < 0.6 else "plausible",
                                f"it holds on only {fit:.0%} of rows, so the table reading itself is uncertain"))
            if fit < 0.6:
                return T
    if f.check == "deleted_row":
        ref = f.fields[0]
        fld = fields[ref]
        doc = docs[fld.doc_id]
        rows = doc.tables.get("transactions", [])
        i = next((k for k, r in enumerate(rows) if r.get("balance") and r["balance"].key() == ref), None)
        gap_lines = []
        if i is not None and i > 0 and rows[i - 1]["page"] == rows[i]["page"]:
            P = doc.pages[rows[i]["page"]]
            y_top, y_bot = rows[i - 1]["bbox"][3], rows[i]["bbox"][1]
            gap_lines = [l for l in P.lines if l.bbox[1] >= y_top - 2 and l.bbox[3] <= y_bot + 2
                         and any(ch.isdigit() for ch in l.text)]
        same_page = i is not None and i > 0 and rows[i - 1]["page"] == rows[i]["page"]
        T.append(_bt("balance_chain_break", "missed_row",
                     "plausible" if (gap_lines or not same_page) else "ruled_out",
                     ("unparsed line(s) between the rows: " + "; ".join(l.text[:40] for l in gap_lines)) if gap_lines
                     else ("rows are on different pages" if not same_page else
                           "no printed line exists between the two rows, so the parser did not skip one")))
        T.append(BenignTest("Loan closed or prepaid, so the EMI stopped", "a closure would stop the EMI but could not "
                            "lower the balance without a printed row", "ruled_out",
                            "the balance fell by the EMI amount with no row printed"))
        T.append(_bt("balance_chain_break", "rounding", "ruled_out", f"difference is Rs. {f.repair['deleted_amount']:,.2f}"))
        return T
    if f.sensor == "repair_solver":
        ref = f.fields[0]
        fld = fields[ref]
        cur, new = f.repair["current"], f.repair["proposed"]
        diff = abs(cur - new)
        for chk in f.repair.get("checks", [c]):
            pass
        T.append(_bt("arithmetic_break", "rounding", "ruled_out" if diff >= 1 else "explains",
                     f"difference is Rs. {diff:,.2f}"))
        a, b = f"{cur:.2f}", f"{new:.2f}"
        one_char = len(a) == len(b) and sum(x != y for x, y in zip(a, b)) == 1
        low = fld.conf < 0.6
        T.append(_bt("arithmetic_break", "ocr_misread", "plausible" if (low and one_char) else "ruled_out",
                     f"OCR confidence {fld.conf:.2f}; read '{fld.raw}' vs consistent {new:,.2f}"
                     + (" (one character apart)" if one_char else "")))
        txt = _doc_text(docs[fld.doc_id])
        kws = [k for k in ("bonus", "arrears", "adjustment", "reimbursement", "recovery", "pro-rata", "pro rata",
                           "final settlement", "lop", "prepayment", "part payment", "rate revision") if k in txt]
        T.append(_bt("arithmetic_break", "unlisted_component", "plausible" if kws else "ruled_out",
                     ("keywords found: " + ", ".join(kws)) if kws else "no bonus/arrears/adjustment wording in the document"))
        if "cross_doc_value_mismatch" in f.repair.get("checks", []) or f.repair.get("claim"):
            T.append(_bt("cross_doc_value_mismatch", "timing", "ruled_out",
                         "salary credit matched by date window (pay month or within 7 days of pay date)"))
        if f.repair.get("contested"):
            T.append(BenignTest("The blamed value is the honest one and the other documents were changed together",
                                "income triangulation finds no decisive majority", "plausible",
                                "see the income triangulation finding"))
        if f.repair.get("soft_only"):
            T.append(_bt("recurring_amount_mismatch", "salary_revision", "plausible",
                         "only salary-recurrence rules are broken; salaries change legitimately"))
        if "recurring_amount_mismatch" in f.repair.get("checks", []) and not f.repair.get("soft_only"):
            brk = "balance_chain_break" in f.repair.get("checks", []) or "statement_totals_mismatch" in f.repair.get("checks", [])
            T.append(_bt("recurring_amount_mismatch", "emi_revision", "ruled_out" if brk else "plausible",
                         "the bank's own running balance and totals disagree with this amount" if brk
                         else "an EMI can change after a rate reset"))
        return T
    if c in ("name_mismatch",) and f.repair.get("equivalent"):
        T.append(_bt("name_mismatch", "transliteration", "explains", "names are identical after transliteration/abbreviation mapping"))
        return T
    if f.sensor == "equality":
        kind = f.repair.get("kind")
        sv, mv = str(f.repair["suspect"]), str(f.repair["majority"])
        conf = min(fields[r].conf for r in f.repair["all_refs"])
        if kind == "name":
            a, b = set(name_key(sv).split()), set(name_key(mv).split())
            T.append(_bt("name_mismatch", "transliteration", "ruled_out", "names differ even after transliteration"))
            T.append(_bt("name_mismatch", "token_order", "explains" if a == b else "ruled_out", ""))
            ini = all(any(x == y or (len(x) == 1 and y.startswith(x)) or (len(y) == 1 and x.startswith(y)) for y in b) for x in a)
            T.append(_bt("name_mismatch", "initials", "plausible" if ini else "ruled_out", ""))
        elif kind == "date":
            ds, dm = sv.replace("/", "-"), mv.replace("/", "-")
            ps, pm = ds.split("-"), dm.split("-")
            swapped = len(ps) == 3 and len(pm) == 3 and ps[0] == pm[1] and ps[1] == pm[0] and ps[2] == pm[2]
            T.append(_bt("date_mismatch", "format", "explains" if swapped else "ruled_out",
                         "day/month swap " + ("makes them equal" if swapped else "does not make them equal")))
            nd = sum(x != y for x, y in zip(ds, dm)) if len(ds) == len(dm) else 99
            T.append(_bt("date_mismatch", "typo", "plausible" if nd == 1 else "ruled_out",
                         f"the two dates differ in {nd} character(s)" if nd < 99 else "different lengths"))
        elif kind == "id":
            a, b = sv.upper().translate(OCR_MAP), mv.upper().translate(OCR_MAP)
            ed = levenshtein(sv.upper(), mv.upper())
            res = "explains" if a == b else ("explains" if (ed <= 1 and conf < 0.6) else "ruled_out")
            T.append(_bt("id_mismatch", "ocr_confusion", res,
                         f"edit distance {ed}, lowest OCR confidence {conf:.2f}"))
        else:
            ed = levenshtein(sv.lower(), mv.lower())
            T.append(BenignTest("Minor spelling or punctuation difference", "edit distance at most 3",
                                "plausible" if ed <= 3 else "ruled_out", f"edit distance {ed}"))
        return T
    if c == "cross_case_photo_reuse":
        T.append(BenignTest("Same person photographed for two cards", "identical image hash, not just a similar face",
                            "ruled_out", f"hash distance {f.repair.get('hamming')} bits"))
        return T
    if c == "cross_case_identifier_reuse":
        T.append(BenignTest("Joint account, family member's number or a data-entry error",
                            "not testable without the other application's consent records", "not_testable", ""))
        return T
    if c == "income_triangulation":
        if not f.repair.get("decisive"):
            T.append(BenignTest("Either group of witnesses could be the honest one", "one value has at least 1.5x the "
                                "support of the other and no self-contradicting document in it", "plausible",
                                "no decisive majority; verify with the employer"))
        return T
    if c in ("overlay_hides_scan", "overlay_on_value"):
        seen, under, num = f.repair.get("seen", ""), f.repair.get("underneath", ""), f.repair.get("has_number")
        replaced = f.smoking_gun
        T.append(BenignTest("Digital stamp, e-sign block or seal placed by the issuer after scanning",
                            "a stamp adds wording; it does not put a different number where the scan has one",
                            "ruled_out" if replaced else ("plausible" if not num else "ruled_out"),
                            f"reader sees '{seen[:40]}', scan underneath reads '{under[:40]}'" if under else f"added text '{seen[:40]}'"))
        if c == "overlay_on_value":
            T.append(BenignTest("Form filled in digitally on a scanned blank template", "the paper underneath is blank at "
                                "this spot", "plausible", "nothing was hidden; the value was typed into the PDF"))
        T.append(BenignTest("Scanner-app text enhancement or OCR layer", "such layers are invisible or redraw every word, "
                            "not one value", "ruled_out", "only this region is drawn over the scan"))
        return T
    if c == "statutory_mismatch":
        doc = docs[fields[f.fields[0]].doc_id] if f.fields and f.fields[0] in fields else None
        txt = _doc_text(doc) if doc else ""
        lop = re.search(r"\b(lop|loss of pay|lwp)\b[^0-9\n]{0,15}[1-9]|\b(arrears|pro.?rata)\b", txt)
        T.append(BenignTest("PF computed on days actually paid (loss of pay) or on a restricted PF wage",
                            "slip shows non-zero LOP days, arrears or pro-rata pay", "plausible" if lop else "ruled_out",
                            f"found '{lop.group(0)}'" if lop else "no loss-of-pay, paid-days or arrears wording on the slip"))
        T.append(BenignTest("Voluntary PF or a PF wage wider than basic", "PF above 12% of basic", "ruled_out",
                            "PF is BELOW 12% of the printed basic, the opposite direction"))
        return T
    if c == "format_violation":
        fld = fields[f.fields[0]] if f.fields else None
        if fld:
            T.append(BenignTest("OCR misread a character", "OCR confidence below 0.60",
                                "explains" if fld.conf < 0.6 else "ruled_out", f"OCR confidence {fld.conf:.2f}"))
        return T
    doc = docs[f.docs[0]] if f.docs else None
    if c == "occluded_text":
        T.append(_bt("occluded_text", "stamp", "ruled_out", "occluder is an opaque white rectangle"))
        T.append(_bt("occluded_text", "watermark", "ruled_out", "occluder is fully opaque"))
        T.append(_bt("occluded_text", "template", "ruled_out" if f.repair.get("displayed_value") else "plausible",
                     "a different value is written on top" if f.repair.get("displayed_value") else "nothing written on top"))
    elif c == "font_mix":
        tok = f.evidence[0].value if f.evidence else ""
        T.append(_bt("font_mix", "symbol_fallback", "plausible" if re.search(r"[^\d,.\s]", tok) else "ruled_out",
                     f"token '{tok}' " + ("contains symbols" if re.search(r"[^\d,.\s]", tok) else "is digits only")))
        try:
            pdf = open_pdf(doc.path)
            form = bool(pdf.is_form_pdf)
            pdf.close()
        except Exception:
            form = False
        T.append(_bt("font_mix", "form_field", "plausible" if form else "ruled_out",
                     "PDF has form fields" if form else "PDF has no form fields"))
    elif c == "noise_inconsistency":
        x0, y0, x1, y1 = f.evidence[0].bbox
        P = doc.pages[f.evidence[0].page]
        area = (x1 - x0) * (y1 - y0) / float(P.width * P.height)
        asp = max(x1 - x0, y1 - y0) / max(1.0, min(x1 - x0, y1 - y0))
        T.append(_bt("noise_inconsistency", "crease", "ruled_out" if asp < 9 else "plausible",
                     f"region aspect ratio {asp:.1f}"))
        T.append(_bt("noise_inconsistency", "lighting", "ruled_out" if area < 0.25 else "plausible",
                     f"region covers {area * 100:.1f}% of the page"))
        import cv2
        g = cv2.imread(P.image_path, cv2.IMREAD_GRAYSCALE)[int(y0):int(y1), int(x0):int(x1)]
        m = float(g.mean()) if g.size else 128
        T.append(_bt("noise_inconsistency", "saturation", "plausible" if (m > 248 or m < 8) else "ruled_out",
                     f"region mean brightness {m:.0f}"))
    elif c == "glyph_outlier":
        T.append(_bt("glyph_outlier", "style", "ruled_out", "no other value on the page shares this deviation"))
        note = f.evidence[0].note if f.evidence else ""
        only_dark = "darkness" in note and note.count("sd") == 1
        T.append(_bt("glyph_outlier", "print_defect", "plausible" if only_dark else "ruled_out", note))
    elif c == "layout_rhythm_break":
        T.append(_bt("layout_rhythm_break", "skew", "ruled_out", "measured against a skew-corrected robust fit"))
        T.append(_bt("layout_rhythm_break", "handwritten", "not_testable", ""))
    elif c == "copy_move":
        jb = False
        if doc.path.lower().endswith(".pdf"):
            try:
                pdf = open_pdf(doc.path)
                for xref in range(1, pdf.xref_length()):
                    if "JBIG2Decode" in (pdf.xref_object(xref) or ""):
                        jb = True
                        break
                pdf.close()
            except Exception:
                pass
        T.append(_bt("copy_move", "jbig2", "explains" if jb else "ruled_out",
                     "PDF uses JBIG2 symbol coding" if jb else "no JBIG2 compression in the file"))
        a, b = (f.evidence[0].value, f.evidence[1].value) if len(f.evidence) > 1 else ("", "")
        T.append(_bt("copy_move", "template", "ruled_out" if a != b else "plausible",
                     f"tokens '{a}' and '{b}'"))
    elif c == "signature_identical":
        both = f.repair.get("both_digital")
        T.append(_bt("signature_identical", "digital_insertion", "explains" if both else "ruled_out",
                     "both documents are born-digital" if both else "one copy is on a scanned (wet-ink) document"))
        if not both:
            if f.repair.get("both_system"):
                T.append(_bt("signature_identical", "printed_stored_image", "explains",
                             "both are system-generated documents (payslips/statements) that print a stored signature image"))
            else:
                T.append(_bt("signature_identical", "printed_stored_image", "not_testable",
                             "cannot tell from pixels whether the issuer printed a stored signature image"))
    elif c == "missing_field":
        T.append(_bt("missing_field", "optional", "ruled_out", "field is in the required list for this document type"))
    elif c == "incremental_update":
        try:
            pdf = open_pdf(doc.path)
            sig = any(w.field_type == fitz.PDF_WIDGET_TYPE_SIGNATURE for pg in pdf for w in (pg.widgets() or []))
            form = bool(pdf.is_form_pdf)
            pdf.close()
        except Exception:
            sig = form = False
        T.append(_bt("incremental_update", "esign", "plausible" if (sig or form) else "ruled_out",
                     "signature/form fields present" if (sig or form) else "no signature or form fields in the file"))
    elif c == "metadata_dates":
        T.append(_bt("metadata_dates", "reexport", "not_testable", ""))
    elif c == "hidden_text":
        T.append(BenignTest("OCR text layer of a scanned PDF", "page is image-only with invisible text on top",
                            "plausible" if doc.modality != "digital_pdf" else "ruled_out", doc.modality))
    return T
