"""Evaluate SAKSHI against the ground-truth manifests of the demo dataset.

    python tests/run_eval.py [--out OUTDIR]

For the tampered case: every planted manipulation must be found on the right
document and field. For the genuine control case: no POTENTIAL_MANIPULATION
finding may appear (false-positive check). Exit code 1 on any failure.
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sakshi.pipeline import run_case  # noqa: E402

# planted manipulation -> (document prefix, checks that count as a hit, field substring or None)
EXPECT = [
    ("payslip net pay overlay", "01_", {"occluded_text"}, None),
    ("payslip font mix", "01_", {"font_mix"}, None),
    ("payslip arithmetic / words / bank", "01_", {"amount_words_mismatch", "arithmetic_break", "cross_doc_value_mismatch"}, "net_pay"),
    ("statement copy-moved digit", "02_", {"copy_move"}, None),
    ("statement EMI restored by repair", "02_", {"balance_chain_break", "statement_totals_mismatch", "recurring_amount_mismatch"}, "debit"),
    ("application EMI white-out", "03_", {"noise_inconsistency"}, "declared_emi"),
    ("application EMI typography", "03_", {"glyph_outlier"}, None),
    ("application EMI alignment", "03_", {"layout_rhythm_break"}, "declared_emi"),
    ("application income claim", "03_", {"claim_vs_evidence"}, "declared_income"),
    ("application DOB conflict", "03_", {"date_mismatch"}, "dob"),
    ("ID card photo splice", "04_", {"noise_inconsistency"}, None),
    ("letter signature reproduced", "05_", {"signature_identical"}, None),
    ("letter tenure inflated", "05_", {"date_mismatch"}, "date_of_joining"),
    ("letter salary contradicts bank", "05_", {"cross_doc_value_mismatch", "claim_vs_evidence"}, "letter_salary"),
]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(ROOT / "out"))
    a = ap.parse_args()
    ok = True
    res = {}
    for case in ("case_tampered", "case_genuine"):
        files = sorted(glob.glob(str(ROOT / "dataset" / "cases" / case / "0*")))
        d = run_case(files, Path(a.out) / case, case_id={"case_tampered": "DEMO-TAMPERED", "case_genuine": "DEMO-GENUINE"}[case], html=os.environ.get("SAKSHI_HTML", "1") == "1")
        res[case] = d
        docs = {x["doc_id"]: x["filename"] for x in d["documents"]}
        print(f"\n== {case}: {d['status']}  {d['counts']}  ({d['processing_seconds']}s)")
        if case == "case_tampered":
            for name, prefix, checks, field in EXPECT:
                hits = [f for f in d["findings"] if f["check"] in checks and f["tier"] != "OBSERVATION"
                        and any(docs[x].startswith(prefix) for x in (f["docs"] + [k.split(".")[0] for k in f["fields"]]))
                        and (field is None or any(field in k for k in f["fields"]))]
                tier = max((h["tier"] for h in hits), default="-", key=lambda t: ["-", "INCONSISTENCY", "POTENTIAL_MANIPULATION"].index(t))
                print(f"  [{'PASS' if hits else 'FAIL'}] {name:38s} -> {tier}")
                ok &= bool(hits)
            decoy = [f for f in d["findings"] if f["check"] == "name_mismatch" and f["tier"] != "OBSERVATION"]
            print(f"  [{'PASS' if not decoy else 'FAIL'}] {'MOHD vs Mohammed decoy not escalated':38s}")
            ok &= not decoy
            th = d["threads"][0] if d["threads"] else {}
            rec = th.get("recovered")
            print(f"  [{'PASS' if rec in ('68,500.00', 68500.0) else 'FAIL'}] {'original net pay recovered':38s} -> {rec}")
            ok &= rec in ("68,500.00", 68500.0)
        else:
            pm = [f for f in d["findings"] if f["tier"] == "POTENTIAL_MANIPULATION"]
            inc = [f for f in d["findings"] if f["tier"] == "INCONSISTENCY"]
            print(f"  [{'PASS' if not pm else 'FAIL'}] no potential-manipulation findings on genuine documents ({len(pm)})")
            for f in pm + inc:
                print(f"      {f['tier']}: {f['title'][:110]}")
            ok &= not pm
        print(f"  audit: {d['audit']['message']}")
    print("\nRESULT:", "ALL PASS" if ok else "FAILURES")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
