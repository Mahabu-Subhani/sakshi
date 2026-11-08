"""Issuer witness: Account Aggregator FI data (ReBIT deposit schema) reconciled against the uploaded statement.

The bank's record for the demo applicant (dataset/aa.py, from the same transactions the genuine statement is drawn
from) is attached to:

* the genuine demo case: every row matches, nothing new is reported;
* the tampered demo case: the EMI shown as 14,500 is reported against the bank's 24,500;
* the Forgery Lab's planned miss, once for every row the recipe can pick: a statement regenerated with one amount
  changed by 3,000 and every later balance recomputed (missed 0/2 without bank data);
* a statement regenerated without the October EMI row (balances recomputed): the bank's EMI is reported missing;
* bank data for a different account: no row is compared, one finding says so;
* bank data that covers a longer period, and a salary paid as two credits on the same day: no false finding.

    python tests/run_issuer.py
"""
import json
import random
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "dataset"))
sys.path.insert(0, str(ROOT / "tests"))
import aa as AA  # noqa: E402
import forgery_lab as FL  # noqa: E402
import generate as G  # noqa: E402
from sakshi.issuer import load  # noqa: E402
from sakshi.pipeline import run_case  # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f"  ({detail})" if detail else ""), flush=True)


def issuer_findings(d):
    return [f for f in d["findings"] if f["check"].startswith("issuer_")]


def run(files, out, cid):
    return run_case([str(f) for f in files], out, case_id=cid, html=False)


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="sakshi_issuer_"))
    try:
        xml, js = AA.write(tmp / "aa")
        a, b = load(xml), load(js)
        check("XML and JSON renderings read identically",
              [(t.direction, t.amount, t.dates, t.balance) for t in a.txns]
              == [(t.direction, t.amount, t.dates, t.balance) for t in b.txns] and len(a.txns) == len(G.TXNS),
              f"{len(a.txns)} transactions, account {a.masked_account}")

        print("== demo cases with the bank's record")
        gen = sorted((ROOT / "dataset/cases/case_genuine").glob("0*"))
        base = run(gen, tmp / "g0", "GENUINE-NO-AA")["counts"]  # this machine's own counts without bank data
        d = run(gen + [xml], tmp / "g", "AA-GENUINE")
        rep = d["issuer_data"][0]["statements"][0]
        check("genuine: every statement row matches the bank's record",
              rep["matched"] == rep["statement_rows"] == 13 and not issuer_findings(d), f"{rep['matched']}/13 matched")
        check("genuine: counts identical with and without the bank's record, nothing above observation",
              d["counts"] == base and base["potential_manipulation"] == 0 and base["inconsistency"] == 0,
              f"{d['counts']} vs {base}")
        tam = sorted((ROOT / "dataset/cases/case_tampered").glob("0*"))
        d = run(tam + [js], tmp / "t", "AA-TAMPERED")
        hit = [f for f in issuer_findings(d) if f["check"] == "issuer_amount_differs"]
        check("tampered: EMI 14,500 reported against the bank's 24,500 at POTENTIAL MANIPULATION",
              len(hit) == 1 and hit[0]["tier"] == "POTENTIAL_MANIPULATION" and "24,500.00" in hit[0]["title"],
              hit[0]["title"][:90] if hit else "none")

        print("== Forgery Lab planned miss: regenerated statement, with the bank's record")
        g = FL.genuine_set(tmp / "_gen", seed=1)
        caught = 0
        for i in (0, 3, 4, 6, 9):  # every row r_consistent_edit can pick
            tx = list(G.TXNS)
            dt, desc, dr, cr = tx[i]
            tx[i] = (dt, desc, dr + 3000 if dr else 0.0, cr + 3000 if cr else 0.0)
            G.build_statement(tmp / f"st_{i}.pdf", tx)
            st, _ = G.simulate_scan(G.render_pdf(tmp / f"st_{i}.pdf"), seed=40 + i, angle=0.2)
            case = tmp / f"regen_{i}"
            FL.write_case(case, g, {"statement_img": st})
            d = run(sorted(case.iterdir()) + [xml], tmp / f"run_regen_{i}", f"AA-REGEN-{i}")
            f = [x for x in issuer_findings(d) if x["check"] == "issuer_amount_differs"
                 and x["tier"] == "POTENTIAL_MANIPULATION"]
            ok = len(f) == 1 and f"{dr + cr:,.2f}" in f[0]["title"]
            caught += ok
            check(f"row {i} ({desc[:22]}) changed by 3,000: caught at POTENTIAL MANIPULATION", ok,
                  f[0]["title"][:80] if f else [x["title"][:60] for x in issuer_findings(d)])
        check("planned miss now caught when the bank's record is attached", caught == 5, f"{caught}/5")

        print("== statement regenerated without the October EMI")
        tx = [t for k, t in enumerate(G.TXNS) if k != G.TAMPER_ROW]
        G.build_statement(tmp / "st_del.pdf", tx)
        st, _ = G.simulate_scan(G.render_pdf(tmp / "st_del.pdf"), seed=77, angle=0.2)
        FL.write_case(tmp / "deleted", g, {"statement_img": st})
        d = run(sorted((tmp / "deleted").iterdir()) + [xml], tmp / "run_del", "AA-DELETED")
        f = [x for x in issuer_findings(d) if x["check"] == "issuer_row_absent"]
        check("the bank's EMI of 24,500 on 05-10-2026 is reported missing from the statement",
              len(f) == 1 and "24,500.00" in f[0]["title"] and "05-10-2026" in f[0]["title"]
              and f[0]["tier"] == "POTENTIAL_MANIPULATION", f[0]["title"][:90] if f else "none")

        print("== safety: different account, longer period, split salary")
        other = AA.account(person=dict(G.PERSON, account="50100999990000"))
        ox, _ = AA.write(tmp / "aa_other", acc=other)
        d = run(gen + [ox], tmp / "run_other", "AA-OTHER")
        kinds = [x["check"] for x in issuer_findings(d)]
        check("different account: one finding, no row compared",
              kinds == ["issuer_account_mismatch"] and not d["issuer_data"][0]["statements"][0]["compared"], str(kinds))
        longer = AA.account(txns=list(G.TXNS) + [("05-11-2026", "EMI DEMO HOME FIN LN88213", 24500.0, 0.0)],
                            end="2026-11-30")
        split = AA.account(txns=[t for t in G.TXNS if t[0] != "31-10-2026"]
                           + [("31-10-2026", "SALARY NIMBUS ANALYTICS OCT PART 1", 0.0, 40000.0),
                              ("31-10-2026", "SALARY NIMBUS ANALYTICS OCT PART 2", 0.0, 28500.0)])
        for name, acc in (("longer period", longer), ("split salary", split)):
            p, _ = AA.write(tmp / f"aa_{name[:5]}", acc=acc)
            d = run(gen + [p], tmp / f"run_{name[:5]}", f"AA-{name[:5].upper()}")
            check(f"{name}: no false finding", not issuer_findings(d), [x["title"][:60] for x in issuer_findings(d)])

        print("== not bank data")
        junk = tmp / "notes.json"
        junk.write_text(json.dumps({"hello": "world"}))
        d = run(gen + [junk], tmp / "run_junk", "AA-JUNK")
        check("a JSON file that is not FI data is skipped with a reason",
              any(r["file"] == "notes.json" for r in d["rejected"]) and d["counts"]["potential_manipulation"] == 0,
              d["rejected"][0]["reason"][:70] if d["rejected"] else "")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    ok = all(results)
    print("RESULT:", "ALL PASS" if ok else "FAILURES")
    return 0 if ok else 1


if __name__ == "__main__":
    random.seed(7)
    sys.exit(main())
