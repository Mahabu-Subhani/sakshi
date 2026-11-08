"""Judge-style check for cross-case memory: every demo case back to back into ONE memory, the way someone clicking
through the demos on one machine would, plus the order and verification checks of the v1.1 design.

    python tests/run_registry_chain.py [--out OUTDIR]

Every case in the dataset uses the same fictional applicant except RT7 (a different person reusing the first
applicant's ID photo and salary account). Since v1.1 the order in which applications arrive decides nothing:

1. chain: before RT7 no case raises a cross-case finding above observation; RT7, and every later application of
   the applicant whose identity RT7 reuses, is CONTESTED (INCONSISTENCY), never POTENTIAL MANIPULATION: without an
   issuer, nothing says which of the two people is genuine;
2. the genuine applicant coming back after RT7 is contested the same way (first-seen no longer wins), and RT7's
   case receives a 'contested by' notice in memory;
3. the genuine applicant with the bank's own record (Account Aggregator data) attached: the salary account is
   verified as theirs (observation); the photo stays contested, because no issuer verifies photos offline;
4. a verified genuine application first, then RT7: RT7's use of the verified salary account is POTENTIAL
   MANIPULATION; the photo stays contested;
5. order invariance: genuine-then-RT7 and RT7-then-genuine give both applications the same tiers.
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "dataset"))
from sakshi.pipeline import run_case  # noqa: E402

DOC = (".pdf", ".jpg", ".jpeg", ".png")
ok = True


def check(name, good, detail=""):
    global ok
    ok &= bool(good)
    print(f"{'PASS' if good else 'FAIL'} {name}" + (f"  ({detail})" if detail else ""), flush=True)


def files(c: Path, aa: Path | None = None):
    fs = sorted(str(p) for p in c.iterdir() if p.suffix.lower() in DOC)
    return fs + ([str(aa)] if aa else [])


def cross(d):
    cc = [f for f in d["findings"] if f["check"].startswith("cross_case")]
    return cc, [f for f in cc if f["tier"] != "OBSERVATION"]


def tiers(d):
    return sorted((f["check"], f["tier"]) for f in cross(d)[1])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(ROOT / "out" / "registry_chain"))
    a = ap.parse_args()
    out = Path(a.out)
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)
    import aa as AA
    aa_xml, _ = AA.write(out / "aa")
    genuine = ROOT / "dataset" / "cases" / "case_genuine"
    rt7 = ROOT / "dataset" / "redteam" / "RT7_identity_ring"

    print("== 1. every demo case into one memory")
    reg = out / "registry_chain.json"
    cases = [genuine, ROOT / "dataset" / "cases" / "case_tampered"]
    cases += sorted(p for p in (ROOT / "dataset" / "redteam").glob("*_*") if (p / "MANIFEST_ground_truth.json").exists())
    rt7_seen = False
    for c in cases:
        d = run_case(files(c), out / c.name, case_id=c.name, html=False, registry_path=reg)
        cc, loud = cross(d)
        if c.name.startswith("RT7") or rt7_seen:
            # RT7 itself, and every later application of the applicant whose identity RT7 reuses: contested both ways
            check(f"{c.name:34s} contested, not escalated", loud and all(f["tier"] == "INCONSISTENCY" for f in loud),
                  "; ".join(f"{f['tier'][:3]} {f['check']}" for f in loud))
            rt7_seen = True
        else:
            check(f"{c.name:34s} nothing above observation", not loud, f"{len(cc)} cross-case finding(s)")

    print("== 2. the genuine applicant comes back after RT7")
    d = run_case(files(genuine), out / "genuine_again", case_id="case_genuine", html=False, registry_path=reg)
    loud = cross(d)[1]
    check("re-run of case_genuine is contested too (first-seen no longer wins)",
          loud and all(f["tier"] == "INCONSISTENCY" for f in loud), "; ".join(f["check"] for f in loud))
    mem = {c["case_id"]: c for c in json.loads(reg.read_text())["cases"]}
    check("RT7's case carries a 'contested by' notice in memory", mem["RT7_identity_ring"].get("contested_by"),
          str(mem["RT7_identity_ring"].get("contested_by", [])[:2]))

    print("== 3. the genuine applicant with the bank's own record attached")
    d = run_case(files(genuine, aa_xml), out / "genuine_aa", case_id="case_genuine_with_bank_record", html=False,
                 registry_path=reg)
    cc, loud = cross(d)
    acct = [f for f in cc if f.get("repair", {}).get("identifier") == "account"]
    check("salary account verified as the genuine applicant's (observation)",
          acct and all(f["tier"] == "OBSERVATION" and f["check"] == "cross_case_reused_by_other" for f in acct),
          "; ".join(f"{f['tier'][:3]} {f['title'][:70]}" for f in acct))
    check("photo stays contested (no issuer verifies photos offline)",
          any(f["check"] == "cross_case_photo_reuse" and f["tier"] == "INCONSISTENCY" for f in loud))

    print("== 4. verified genuine application first, then RT7")
    reg2 = out / "registry_verified.json"
    run_case(files(genuine, aa_xml), out / "v_genuine", case_id="V-GENUINE", html=False, registry_path=reg2)
    d = run_case(files(rt7), out / "v_rt7", case_id="V-RT7", html=False, registry_path=reg2)
    cc, loud = cross(d)
    acct = [f for f in loud if f.get("repair", {}).get("identifier") == "account"]
    check("RT7 using the bank-verified salary account: POTENTIAL MANIPULATION",
          acct and all(f["tier"] == "POTENTIAL_MANIPULATION" for f in acct),
          "; ".join(f"{f['tier'][:3]} {f['title'][:70]}" for f in acct))
    check("RT7 photo stays contested", any(f["check"] == "cross_case_photo_reuse" and f["tier"] == "INCONSISTENCY"
                                           for f in loud))

    print("== 5. order invariance without bank data")
    res = {}
    for order in (("G", "R"), ("R", "G")):
        r = out / f"registry_{''.join(order)}.json"
        for who in order:
            c = genuine if who == "G" else rt7
            d = run_case(files(c), out / f"o_{''.join(order)}_{who}", case_id=f"O-{who}", html=False, registry_path=r)
            res[(order, who)] = tiers(d)
    first = {who: res[(("G", "R"), who)] for who in "GR"}
    second = {who: res[(("R", "G"), who)] for who in "GR"}
    # the application that arrives first has nothing to compare with, so compare each one when it arrives second
    check("RT7 arriving second and the genuine applicant arriving second get the same tiers",
          first["R"] == second["G"] or (first["R"] and second["G"]
                                        and {t for _, t in first["R"]} == {t for _, t in second["G"]} == {"INCONSISTENCY"}),
          f"RT7 second: {first['R']}; genuine second: {second['G']}")
    print("\nRESULT:", "ALL PASS" if ok else "FAILURES")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
