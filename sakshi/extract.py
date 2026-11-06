"""Structured extraction. Every field keeps its page, pixel bbox, OCR confidence and
the method that produced it, so any finding can be traced back to the exact pixels.

Extraction is layout-driven (labels, segments, table headers) rather than
template-driven, so it works on layouts it has never seen as long as fields are
labelled the usual way.
"""
from __future__ import annotations

import re
from typing import Optional

import numpy as np

from .models import Document, Field, Line, Page, Word

AMOUNT_RE = re.compile(r"(?<![\d/-])(\d{1,3}(?:,\d{2,3})*(?:\.\d{2})|\d+\.\d{2})(?![\d/-])")
DATE_RE = re.compile(r"\b(\d{1,2})[-/.](\d{1,2})[-/.](\d{4})\b")
MONTHS = {m: i + 1 for i, m in enumerate(["january", "february", "march", "april", "may", "june", "july",
                                           "august", "september", "october", "november", "december"])}


# ---------------------------------------------------------------- normalizers
def parse_amount(s: str) -> Optional[float]:
    s = s.replace("Rs.", "").replace("Rs", "").replace("INR", "").replace("₹", "")
    s2 = re.sub(r"(?<=\d)[\s](?=\d{3}\b)", "", s)  # '14 500.00' -> '14500.00' (OCR split)
    m = AMOUNT_RE.search(s2)
    if not m:
        m2 = re.search(r"\d[\d,]*", s2)
        if not m2:
            return None
        try:
            return float(m2.group(0).replace(",", ""))
        except ValueError:
            return None
    return float(m.group(1).replace(",", ""))


MON3 = {m[:3]: i + 1 for i, m in enumerate(["january", "february", "march", "april", "may", "june", "july",
                                               "august", "september", "october", "november", "december"])}
MON3["sept"] = 9
DATE_ANY_RE = re.compile(
    r"\b(?:(?P<d1>\d{1,2})[-/.](?P<m1>\d{1,2})[-/.](?P<y1>\d{4}|\d{2})"
    r"|(?P<y2>\d{4})[-/.](?P<m2>\d{1,2})[-/.](?P<d2>\d{1,2})"
    r"|(?P<d3>\d{1,2})[-/. ]?(?P<m3>[A-Za-z]{3,9})[-/., ]+(?P<y3>\d{4}|\d{2}))\b")


def _iso(d, mo, y) -> Optional[str]:
    y = int(y)
    y = 2000 + y if y < 100 else y
    try:
        from datetime import date as _date
        return _date(y, int(mo), int(d)).isoformat()
    except (ValueError, TypeError):
        return None


def find_dates(s: str) -> list:
    """All dates in a string, ISO formatted. Handles DD-MM-YYYY, DD/MM/YY, YYYY-MM-DD, DD Mon YYYY, DD-Mon-YY."""
    out = []
    for m in DATE_ANY_RE.finditer(s):
        if m.group("d1"):
            v = _iso(m.group("d1"), m.group("m1"), m.group("y1"))
        elif m.group("y2"):
            v = _iso(m.group("d2"), m.group("m2"), m.group("y2"))
        else:
            mon = MON3.get(m.group("m3").lower()[:4] if m.group("m3").lower().startswith("sept") else m.group("m3").lower()[:3])
            v = _iso(m.group("d3"), mon, m.group("y3")) if mon else None
        if v:
            out.append(v)
    return out


def parse_date(s: str) -> Optional[str]:
    ds = find_dates(s)
    return ds[0] if ds else None


def norm_name(s: str) -> str:
    s = re.sub(r"\b(mr|mrs|ms|shri|smt|dr)\.?\s+", "", s, flags=re.I)
    s = re.sub(r"[^A-Za-z ]", " ", s)
    return re.sub(r"\s+", " ", s).strip().upper()


def norm_id(s: str) -> str:
    return re.sub(r"[^A-Za-z0-9]", "", s).upper()


ONES = {w: i for i, w in enumerate(["zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine",
                                    "ten", "eleven", "twelve", "thirteen", "fourteen", "fifteen", "sixteen",
                                    "seventeen", "eighteen", "nineteen"])}
TENS = {"twenty": 20, "thirty": 30, "forty": 40, "fifty": 50, "sixty": 60, "seventy": 70, "eighty": 80, "ninety": 90}
SCALES = {"hundred": 100, "thousand": 1000, "lakh": 100000, "lakhs": 100000, "lac": 100000, "crore": 10000000,
          "crores": 10000000}


def words_to_number(s: str) -> Optional[int]:
    """'Rupees Sixty Eight Thousand Five Hundred Only' -> 68500 (Indian numbering)."""
    toks = re.findall(r"[a-z]+", s.lower())
    total, cur, seen = 0, 0, False
    for t in toks:
        if t in ONES:
            cur += ONES[t]; seen = True
        elif t in TENS:
            cur += TENS[t]; seen = True
        elif t == "hundred":
            cur = max(cur, 1) * 100; seen = True
        elif t in SCALES:
            total += max(cur, 1) * SCALES[t]; cur = 0; seen = True
    return total + cur if seen else None


# ---------------------------------------------------------------- layout helpers
def union(boxes):
    boxes = list(boxes)
    return (min(b[0] for b in boxes), min(b[1] for b in boxes), max(b[2] for b in boxes), max(b[3] for b in boxes))


def segments(line: Line, gap_px: float = 34.0) -> list[list[Word]]:
    """Split a visual line into column segments at large horizontal gaps."""
    segs, cur = [], []
    for w in line.words:
        if cur and w.bbox[0] - cur[-1].bbox[2] > gap_px:
            segs.append(cur)
            cur = []
        cur.append(w)
    if cur:
        segs.append(cur)
    return segs


def seg_text(seg: list[Word]) -> str:
    return " ".join(w.text for w in seg)


def make_field(doc: Document, page: Page, name: str, words: list[Word], kind: str, method: str,
               label_words: list[Word] | None = None, raw: str | None = None, ref: str | None = None) -> Optional[Field]:
    words = [w for w in words if w.text.strip()]
    if not words:
        return None
    raw = raw if raw is not None else seg_text(words)
    if kind == "amount":
        value = parse_amount(raw)
    elif kind == "date":
        value = parse_date(raw)
    elif kind == "name":
        value = norm_name(raw)
    elif kind == "id":
        value = norm_id(raw)
    elif kind == "int":
        m = re.search(r"\d+", raw)
        value = int(m.group(0)) if m else None
    elif kind == "words_amount":
        value = words_to_number(raw)
        value = float(value) if value is not None else None
        kind = "amount"
    else:
        value = re.sub(r"\s+", " ", raw).strip()
    if value is None or value == "":
        return None
    conf = float(np.mean([w.conf for w in words]))
    if kind in ("amount", "id", "date"):
        conf = float(min(w.conf for w in words))  # one bad glyph spoils a number
    return Field(name=name, raw=raw, value=value, kind=kind, doc_id=doc.doc_id, page=page.index,
                 bbox=tuple(round(v, 1) for v in union(w.bbox for w in words)), conf=round(conf, 3), method=method,
                 label_bbox=tuple(round(v, 1) for v in union(w.bbox for w in label_words)) if label_words else None,
                 ref=ref or f"{doc.doc_id}.{name}")


def find_label(page: Page, pattern: str):
    """Find a label regex on any line. Returns (line, label_words, value_words_same_line, next_line)."""
    rx = re.compile(pattern, re.I)
    for li, line in enumerate(page.lines):
        words = [w for w in line.words if w.conf >= 0.1]
        if not words:
            continue
        text, starts = "", []
        for w in words:
            starts.append(len(text))
            text += w.text + " "
        m = rx.search(text)
        if not m:
            continue
        lw = [w for w, s in zip(words, starts) if s < m.end() and s + len(w.text) > m.start()]
        after = [w for w, s in zip(words, starts) if s >= m.end()]
        # value = first segment after the label (the label->value gap may be wide),
        # ending at the next big gap, which separates two-column layouts
        val = []
        for w in after:
            if not val:
                if w.bbox[0] - lw[-1].bbox[2] > 700:
                    break
                val.append(w)
                continue
            if w.bbox[0] - val[-1].bbox[2] > 40:
                break
            val.append(w)
        nxt = page.lines[li + 1] if li + 1 < len(page.lines) else None
        return line, lw, val, nxt
    return None


def label_field(doc, page, name, pattern, kind, next_line_ok=False):
    r = find_label(page, pattern)
    if not r:
        return None
    line, lw, val, nxt = r
    method = "label-anchored, same line"
    if not val and next_line_ok and nxt is not None and nxt.bbox[1] - line.bbox[3] < 60:
        val = [w for w in nxt.words if w.conf >= 0.25]
        method = "label-anchored, value on next line"
    return make_field(doc, page, name, val, kind, method, label_words=lw)


def add(doc: Document, f: Optional[Field]):
    if f is not None:
        if f.name in doc.fields:
            doc.structure.setdefault("duplicates", []).append(f.name)
            return
        doc.fields[f.name] = f


def page_text_index(page: Page):
    text, spans = "", []
    for line in page.lines:
        for w in line.words:
            if w.conf < 0.25:
                continue
            spans.append((len(text), len(text) + len(w.text), w))
            text += w.text + " "
        text += "\n"
    return text, spans


def regex_field(doc, page, name, pattern, kind, group=1):
    text, spans = page_text_index(page)
    m = re.search(pattern, text, re.I | re.S)
    if not m:
        return None
    a, b = m.span(group)
    ws = [w for s, e, w in spans if s < b and e > a]
    return make_field(doc, page, name, ws, kind, "pattern in running text", raw=m.group(group))


# ---------------------------------------------------------------- per-type extractors
def extract_salary_slip(doc: Document):
    p = doc.pages[0]
    for name, pat, kind in [
        ("employee_name", r"employee name\s*:", "name"), ("employee_id", r"employee id\s*:", "id"),
        ("designation", r"designation\s*:", "text"), ("date_of_joining", r"date of joining\s*:", "date"),
        ("pan", r"\bpan\s*:", "id"), ("account_no", r"(bank )?a/?c no\.?\s*:", "id"),
        ("pay_date", r"pay date\s*:", "date"), ("gross", r"gross earnings", "amount"),
        ("total_deductions", r"total deductions", "amount"), ("net_pay", r"net pay[^:]*:", "amount"),
        ("net_pay_words", r"amount in words\s*:", "words_amount"),
    ]:
        add(doc, label_field(doc, p, name, pat, kind))
    # employer: first header line containing LTD / LIMITED / PVT
    for line in p.lines[:6]:
        if re.search(r"\b(pvt|ltd|limited|llp)\b", line.text, re.I):
            add(doc, make_field(doc, p, "employer", line.words, "name", "letterhead line"))
            break
    m = re.search(r"month of\s+([a-z]+)\s+(\d{4})", " ".join(l.text for l in p.lines), re.I)
    if m and m.group(1).lower() in MONTHS:
        doc.structure["pay_month"] = f"{m.group(2)}-{MONTHS[m.group(1).lower()]:02d}"
    # earnings / deductions table: amount segments preceded by a text segment
    start = next((i for i, l in enumerate(p.lines) if re.search(r"\bearnings\b.*\bdeductions\b", l.text, re.I)), None)
    end = next((i for i, l in enumerate(p.lines) if re.search(r"gross earnings", l.text, re.I)), None)
    earnings, deductions = [], []
    if start is not None and end is not None:
        mid = p.width / 2
        for line in p.lines[start + 1:end]:
            segs = segments(line)
            for i, sg in enumerate(segs):
                if parse_amount(seg_text(sg)) is not None and AMOUNT_RE.search(seg_text(sg)) and i > 0:
                    label = seg_text(segs[i - 1])
                    side = earnings if sg[0].bbox[0] < mid else deductions
                    slug = re.sub(r"[^a-z]+", "_", label.lower()).strip("_")
                    f = make_field(doc, p, slug, sg, "amount", "earnings/deductions table cell",
                                   label_words=segs[i - 1], ref=f"{doc.doc_id}.{'earn' if side is earnings else 'ded'}.{slug}")
                    if f:
                        side.append(f)
    doc.tables["earnings"] = earnings
    doc.tables["deductions"] = deductions
    doc.structure["sections"] = ["header", "employee details", "earnings", "deductions", "totals", "net pay",
                                 "signatory"]


def extract_bank_statement(doc: Document, reocr=None):
    """Header fields by label; the transaction table by the constraint-guided parser
    (forensics/table_parser.py): it tries every column-role
    hypothesis against the running-balance equation and keeps the one that fits."""
    from .forensics.table_parser import parse_statement
    p0 = doc.pages[0]
    for name, pat, kind in [("account_holder", r"account holder( name)?\s*:", "name"),
                            ("account_no", r"account (no|number)\.?\s*:", "id"),
                            ("ifsc", r"ifsc( code)?\s*:", "id")]:
        add(doc, label_field(doc, p0, name, pat, kind))
    r = find_label(p0, r"(statement )?period\s*:")
    if r:
        ds = find_dates(" ".join(w.text for w in r[2]))
        if len(ds) >= 2:
            doc.structure["period"] = ds[:2]
    res = parse_statement(doc.pages, reocr=reocr)
    doc.structure["table_layout"] = res["layout"]
    doc.structure["transition_fit"] = round(res["transition_fit"], 3)
    doc.structure["healed"] = res["healed"]
    for n in res["notes"]:
        doc.notes.append("Statement table: " + n)
    rows = []

    def cell(c, name, page):
        if not c:
            return None
        return Field(name=name, raw=c["raw"], value=float(c["value"]), kind="amount", doc_id=doc.doc_id, page=page,
                     bbox=tuple(round(v, 1) for v in c["bbox"]), conf=round(float(c["conf"]), 3),
                     method=f"table cell ({res['layout'].replace('_', ' ')}, balance-equation fit {res['transition_fit']:.0%})",
                     ref=f"{doc.doc_id}.{name}")

    for r0 in res["rows"]:
        if r0["kind"] in ("total", "carried_forward"):
            continue  # summaries and page carry-overs are not chain links
        if r0["kind"] == "brought_forward" and rows:
            continue  # B/F repeats the previous page's last balance
        idx = len(rows)
        dt = r0.get("date")
        row = {"date": Field(name=f"row{idx}.date", raw=dt["raw"], value=dt["iso"], kind="date", doc_id=doc.doc_id,
                             page=r0["page"], bbox=tuple(round(v, 1) for v in dt["bbox"]), conf=round(float(dt["conf"]), 3),
                             method="table cell", ref=f"{doc.doc_id}.row{idx}.date") if dt else None,
               "description": r0["description"], "page": r0["page"],
               "bbox": tuple(round(v, 1) for v in r0["bbox"]), "opening": r0["kind"] in ("opening", "brought_forward"),
               "kind": r0["kind"]}
        for col in ("debit", "credit", "balance"):
            f = cell(r0.get(col), f"row{idx}.{col}", r0["page"])
            if f:
                row[col] = f
        if not row["date"] and not row["opening"]:
            continue
        rows.append(row)
    # Column sanity: with a smudged balance cell the parser may take the row's amount as its
    # balance. A cell that sits in another column's x-band is moved to that column, or dropped as unreadable.
    import statistics
    med = {}
    for col in ("debit", "credit", "balance"):
        xs = [r[col].bbox[2] for r in rows if r.get(col)]
        if len(xs) >= 3:
            med[col] = statistics.median(xs)
    tol = 40.0
    moved = 0
    if "balance" in med:
        for r in rows:
            b = r.get("balance")
            if not b or abs(b.bbox[2] - med["balance"]) <= tol:
                continue
            home = next((c for c in ("debit", "credit") if c in med and abs(b.bbox[2] - med[c]) <= tol), None)
            del r["balance"]
            if home and not r.get(home):
                nm = f"{b.name.split('.')[0]}.{home}"
                r[home] = Field(name=nm, raw=b.raw, value=b.value, kind="amount", doc_id=b.doc_id, page=b.page,
                                bbox=b.bbox, conf=b.conf, method=b.method + "; moved to its column by x-position",
                                ref=f"{doc.doc_id}.{nm}")
            else:
                r["unreadable"] = True
            moved += 1
    if moved:
        doc.notes.append(f"Statement table: {moved} balance cell(s) were not in the balance column (smudged or unreadable "
                         "balance); the running-balance check bridges over those rows.")
    doc.tables["transactions"] = rows
    # Balance fit over CONFIDENTLY read transitions only: garbage typed into a few balance
    # cells must not drag the fit down and switch statement arithmetic off for the one row that matters.
    good = tot = 0
    for a, b in zip(rows, rows[1:]):
        cells = [a.get("balance"), b.get("balance")] + [b.get(k) for k in ("debit", "credit") if b.get(k)]
        if not a.get("balance") or not b.get("balance") or min(c.conf for c in cells) < 0.6:
            continue
        tot += 1
        exp = a["balance"].value + (b["credit"].value if b.get("credit") else 0.0) - (b["debit"].value if b.get("debit") else 0.0)
        good += abs(exp - b["balance"].value) <= 0.51
    doc.structure["confident_transitions"] = tot
    doc.structure["confident_fit"] = round(good / tot, 3) if tot else None
    p = doc.pages[-1]
    for name, pat in [("summary_opening", r"opening balance\s*:"), ("summary_debits", r"total (debits|withdrawals)\s*:"),
                      ("summary_credits", r"total (credits|deposits)\s*:"), ("summary_closing", r"closing balance\s*:")]:
        add(doc, label_field(doc, p, name, pat, "amount"))
    doc.structure["sections"] = ["bank header", "account details", "transaction table", "summary"]


def extract_application(doc: Document):
    p = doc.pages[0]
    for name, pat, kind in [
        ("applicant_name", r"applicant name\s*:", "name"), ("dob", r"date of birth\s*:", "date"),
        ("pan", r"\bpan\s*:", "id"), ("mobile", r"mobile\s*:", "id"), ("address", r"address\s*:", "text"),
        ("employer", r"employer\s*:", "name"), ("designation", r"designation\s*:", "text"),
        ("date_of_joining", r"date of joining\s*:", "date"),
        ("declared_income", r"(net )?monthly income[^:]*:", "amount"),
        ("declared_emi", r"existing monthly em[il1|]s?[^:]*:", "amount"),
        ("account_no", r"(salary )?account no\.?\s*:", "id"), ("ifsc", r"ifsc\s*:", "id"),
        ("loan_amount", r"loan amount requested[^:]*:", "amount"), ("tenure", r"tenure[^:]*:", "int"),
        ("application_date", r"date of application\s*:", "date"), ("place", r"place\s*:", "text"),
    ]:
        add(doc, label_field(doc, p, name, pat, kind))
    doc.structure["sections"] = ["bank header", "applicant details", "employment & income", "loan request",
                                 "declaration", "signature"]


def extract_identity(doc: Document):
    p = doc.pages[0]
    for name, pat, kind in [("name", r"^name\s*:?\s*$", "name"), ("dob", r"date of birth|\bdob\b", "date"),
                            ("id_no", r"\bid no\.?|\bid number", "id"), ("issued", r"\bissued\b", "date"),
                            ("valid_till", r"valid till|valid upto|expiry", "date")]:
        add(doc, label_field(doc, p, name, pat, kind, next_line_ok=True))
    r = find_label(p, r"^address\s*:?\s*$")
    if r:
        li = p.lines.index(r[0])
        ws = []
        for ln in p.lines[li + 1:li + 3]:
            ws += [w for w in ln.words if w.conf >= 0.25]
        add(doc, make_field(doc, p, "address", ws, "text", "label-anchored, value on following lines", label_words=r[1]))
    doc.structure["sections"] = ["issuer band", "photo", "identity fields", "address"]


def extract_letter(doc: Document):
    p = doc.pages[0]
    add(doc, regex_field(doc, p, "employee_name", r"(?:mr|ms|mrs)\.?\s+([A-Za-z .]+?)\s*\(", "name"))
    add(doc, regex_field(doc, p, "employee_id", r"employee id\s+([A-Z0-9-]+)", "id"))
    add(doc, regex_field(doc, p, "employer", r"working with\s+(.+?)\s+since", "name"))
    add(doc, regex_field(doc, p, "date_of_joining", r"since\s+(\d{1,2}[-/. ]?(?:\d{1,2}|[A-Za-z]{3,9})[-/., ]+\d{2,4})", "date"))
    add(doc, regex_field(doc, p, "designation", r"\d{4}\s+as\s+([^\n.]+?)\s*(?:\.|\n|$)", "text"))
    add(doc, regex_field(doc, p, "letter_salary", r"(?:net|gross)?\s*(?:monthly\s+)?salary is\s+(?:rs\.?|inr|\u20b9)?\s*([\d,]+(?:\.\d{2})?)", "amount"))
    add(doc, regex_field(doc, p, "letter_ctc_annual", r"annual\s+ctc\s+(?:is|of)?\s*(?:rs\.?|inr|\u20b9)?\s*([\d,]+(?:\.\d{2})?)", "amount"))
    add(doc, regex_field(doc, p, "letter_date", r"date\s*:\s*(\d{1,2}[-/. ]?(?:\d{1,2}|[A-Za-z]{3,9})[-/., ]+\d{2,4})", "date"))
    text = page_text_index(p)[0].lower()
    doc.structure["salary_basis"] = "net" if re.search(r"net (monthly )?salary", text) else (
        "gross" if re.search(r"gross|ctc", text) else "unspecified")
    doc.structure["sections"] = ["letterhead", "reference & date", "subject", "body", "signatory"]


def extract_generic(doc: Document):
    """Unknown layouts: harvest every 'Label: value' pair so cross-checks still get data."""
    for p in doc.pages:
        for line in p.lines:
            for sg in segments(line):
                t = seg_text(sg)
                m = re.match(r"([A-Za-z][A-Za-z /().]{2,40}):\s*(.+)$", t)
                if not m:
                    continue
                label = re.sub(r"[^a-z]+", "_", m.group(1).lower()).strip("_")
                vw = [w for w in sg if not w.text.endswith(":")][-max(1, len(m.group(2).split())):]
                kind = "date" if parse_date(m.group(2)) else ("amount" if AMOUNT_RE.search(m.group(2)) else "text")
                add(doc, make_field(doc, p, f"generic.{label}", vw, kind, "generic label:value harvest"))


EXTRACTORS = {
    "salary_slip": extract_salary_slip,
    "bank_statement": extract_bank_statement,
    "application_form": extract_application,
    "identity_card": extract_identity,
    "employment_letter": extract_letter,
}

REQUIRED = {
    "salary_slip": ["employee_name", "employee_id", "pan", "account_no", "gross", "total_deductions", "net_pay",
                    "net_pay_words", "date_of_joining", "employer"],
    "bank_statement": ["account_holder", "account_no", "ifsc"],
    "application_form": ["applicant_name", "dob", "pan", "declared_income", "declared_emi", "account_no",
                         "employer", "loan_amount", "application_date"],
    "identity_card": ["name", "dob", "id_no", "valid_till"],
    "employment_letter": ["employee_name", "employer", "date_of_joining", "letter_date"],
}


def extract(doc: Document, reocr=None) -> None:
    if doc.doc_type == "bank_statement":
        extract_bank_statement(doc, reocr=reocr)
    else:
        EXTRACTORS.get(doc.doc_type, extract_generic)(doc)
    # identifiers the submitter masked ('XXXXXX821Q', '****7812') are not values: they never enter format or
    # cross-document checks, and their absence is reported as masked, not missing
    masked = []
    for name, f in list(doc.fields.items()):
        if name in ("pan", "account_no", "id_no", "mobile", "aadhaar", "employee_id") and re.search(r"[Xx*#]{3,}", str(f.raw)):
            masked.append(name)
            del doc.fields[name]
    if masked:
        doc.structure["masked_fields"] = masked
        doc.notes.append("Masked by the submitter (not checked): " + ", ".join(m.replace("_", " ") for m in masked) + ".")
    req = REQUIRED.get(doc.doc_type, [])
    missing = [r for r in req if r not in doc.fields and r not in masked]
    if req and len(missing) >= 0.6 * len(req):
        # keywords said one thing, the structure says another: do not pretend to understand it
        doc.notes.append(f"Keywords suggested '{doc.doc_type}', but {len(missing)} of {len(req)} expected fields are "
                         "absent, so the document is treated as unclassified and only generic checks are applied.")
        doc.type_evidence = doc.type_evidence + [f"structure check failed ({len(missing)}/{len(req)} fields missing)"]
        doc.doc_type, doc.type_confidence, doc.witness = "unknown", 0.0, 1
        doc.fields, doc.tables = {}, {}
        extract_generic(doc)
        req, missing = [], []
    doc.structure["required_fields"] = req
    doc.structure["missing"] = missing
    doc.structure.setdefault("duplicates", [])
