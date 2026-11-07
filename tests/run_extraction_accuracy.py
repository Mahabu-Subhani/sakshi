"""Field-level extraction accuracy against generator ground truth.

    python tests/run_extraction_accuracy.py

The demo documents are synthetic, so every true value is known: it comes from the constants in
dataset/generate.py (the applicant, the payslip lines, the statement transactions). Two conditions:

  * clean   - dataset/cases/case_genuine: born-digital payslip PDF, scanned statement, scanned
              application form, scanned ID card, scanned employment letter;
  * phone   - dataset/redteam/G10_genuine_whatsapp_photos: the payslip and the employment letter
              photographed and forwarded on WhatsApp (perspective, uneven light, JPEG twice).

A field counts as correct only if its normalised value equals the truth exactly (amounts to the paisa,
dates as ISO dates, identifiers and names ignoring spacing and punctuation). A field the pipeline did not
extract counts as wrong. Statement transactions are scored per row: date, amount and running balance must
all be right. Prints a table per document and the totals; exit code 0 (this is a measurement, not a gate).
"""
from __future__ import annotations

import importlib.util
import re
import sys
import tempfile
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sakshi.pipeline import run_case  # noqa: E402

spec = importlib.util.spec_from_file_location("sakshi_generate", ROOT / "dataset" / "generate.py")
G = importlib.util.module_from_spec(spec)
sys.modules["sakshi_generate"] = G
spec.loader.exec_module(G)
P = G.PERSON


def iso(d):  # "31-10-2026" -> "2026-10-31"
    dd, mm, yy = d.split("-")
    return f"{yy}-{mm}-{dd}"


GROSS = sum(v for _, v in G.EARNINGS)
DED = sum(v for _, v in G.DEDUCTIONS)
TRUTH = {
    "salary_slip": {"employee_name": P["name"], "employee_id": P["emp_id"], "designation": P["designation"],
                    "date_of_joining": iso(P["doj"]), "pan": P["pan"], "account_no": P["account"],
                    "pay_date": iso("31-10-2026"), "gross": GROSS, "total_deductions": DED, "net_pay": G.NET,
                    "net_pay_words": G.NET, "employer": P["employer"]},
    "bank_statement": {"account_holder": P["bank_name"], "account_no": P["account"], "ifsc": P["ifsc"],
                       "summary_opening": G.OPENING, "summary_debits": sum(t[2] for t in G.TXNS),
                       "summary_credits": sum(t[3] for t in G.TXNS),
                       "summary_closing": G.OPENING - sum(t[2] for t in G.TXNS) + sum(t[3] for t in G.TXNS)},
    "application_form": {"applicant_name": P["name"], "dob": iso(P["dob"]), "pan": P["pan"], "mobile": P["mobile"],
                         "address": P["address"], "employer": P["employer"], "designation": P["designation"],
                         "date_of_joining": iso(P["doj"]), "declared_income": G.NET, "declared_emi": G.EMI,
                         "account_no": P["account"], "ifsc": P["ifsc"], "loan_amount": 2500000, "tenure": 240,
                         "application_date": iso("02-11-2026"), "place": "Bengaluru"},
    "identity_card": {"name": P["name"], "dob": iso(P["dob"]), "id_no": P["id_no"], "issued": iso("12-01-2022"),
                      "valid_till": iso("11-01-2032"), "address": P["address"]},
    "employment_letter": {"employee_name": P["name"], "employee_id": P["emp_id"], "employer": P["employer"],
                          "date_of_joining": iso(P["doj"]), "designation": P["designation"], "letter_salary": G.NET,
                          "letter_date": iso("03-11-2026")},
}


def norm(v):
    if isinstance(v, (int, float)):
        return round(float(v), 2)
    return re.sub(r"[^A-Z0-9]", "", str(v).upper())


def same(a, b):
    if isinstance(b, (int, float)):
        try:
            return abs(float(a) - float(b)) < 0.005
        except (TypeError, ValueError):
            return False
    return norm(a) == norm(b)


def statement_rows(doc):
    """True rows: (iso date, signed amount, balance) after the opening balance."""
    truth, bal = [], G.OPENING
    for date, _desc, dr, cr in G.TXNS:
        bal = round(bal - dr + cr, 2)
        truth.append((iso(date), round(cr - dr, 2), bal))
    got = []
    for r in doc.get("tables", {}).get("transactions", []):
        if str(r.get("description", "")).upper().startswith("OPENING"):
            continue
        amt = lambda k: (r.get(k) or {}).get("value") or 0.0
        got.append((r.get("date"), round(float(amt("credit")) - float(amt("debit")), 2), round(float(amt("balance")), 2)))
    hits = 0
    for t in truth:
        for g in got:
            if g[0] and (g[0] == t[0] or (len(g[0]) == 10 and iso(g[0]) == t[0] if g[0][2] == "-" else False)) \
                    and abs(g[1] - t[1]) < 0.005 and abs(g[2] - t[2]) < 0.005:
                hits += 1
                break
    return hits, len(truth)


def score(case_dir, files=None):
    files = files or sorted(str(p) for p in Path(case_dir).iterdir() if p.name != "MANIFEST_ground_truth.json")
    d = run_case(files, Path(tempfile.mkdtemp()), case_id=Path(case_dir).name, html=False)
    out = []
    for doc in d["documents"]:
        truth = TRUTH.get(doc["type"])
        if not truth:
            continue
        got = {f["name"]: f for f in doc["fields"]}
        ok, misses, confs = 0, [], defaultdict(list)
        for k, v in truth.items():
            f = got.get(k)
            hit = f is not None and same(f["value"], v)
            ok += hit
            if f is not None and f.get("conf") is not None:
                confs[hit].append(f["conf"])
            if not hit:
                misses.append(f"{k}={'(not extracted)' if f is None else repr(f.get('raw'))}")
        rows = statement_rows(doc) if doc["type"] == "bank_statement" else None
        out.append((doc["filename"], doc["type"], ok, len(truth), rows, misses, confs))
    return out


def main():
    total = defaultdict(lambda: [0, 0])
    rows_total = defaultdict(lambda: [0, 0])
    conf_ok, conf_bad = [], []
    for label, case, files in [("clean", ROOT / "dataset/cases/case_genuine", None),
                               ("phone", ROOT / "dataset/redteam/G10_genuine_whatsapp_photos",
                                [str(ROOT / "dataset/redteam/G10_genuine_whatsapp_photos" / n)
                                 for n in ("01_payslip_oct2026.jpg", "05_employment_letter.jpg")])]:
        print(f"\n== {label}: {case.name}")
        for fn, typ, ok, n, rows, misses, confs in score(case, files):
            total[label][0] += ok; total[label][1] += n
            conf_ok += confs[True]; conf_bad += confs[False]
            extra = ""
            if rows:
                rows_total[label][0] += rows[0]; rows_total[label][1] += rows[1]
                extra = f"   transactions {rows[0]}/{rows[1]} rows exact"
            print(f"  {fn:38s} {typ:18s} fields {ok:2d}/{n:2d}{extra}")
            for m in misses:
                print(f"      miss: {m}")
    print("\nRESULT")
    for label, (ok, n) in total.items():
        print(f"  {label:6s} fields exact: {ok}/{n} ({ok / n:.0%})")
    for label, (ok, n) in rows_total.items():
        print(f"  {label:6s} statement rows exact: {ok}/{n}")
    if conf_ok:
        print(f"  mean confidence: correct fields {sum(conf_ok) / len(conf_ok):.2f}"
              + (f", wrong fields {sum(conf_bad) / len(conf_bad):.2f} (n={len(conf_bad)})" if conf_bad else ", no wrong extracted fields"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
