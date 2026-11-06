"""Judge-style check for cross-case memory: run EVERY demo case back to back into ONE registry,
the way someone clicking through the demos on one machine would.

    python tests/run_registry_chain.py [--out OUTDIR]

Every case in the dataset uses the same fictional applicant except RT7 (a different person reusing
the first applicant's ID photo and salary account). PASS = only RT7 raises a non-observation
cross-case finding; every re-use by the same applicant stays an observation, including when the
genuine applicant comes back after RT7 was remembered (the earlier holder owns the identifier).
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sakshi.pipeline import run_case  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(ROOT / "out" / "registry_chain"))
    a = ap.parse_args()
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    reg = out / "registry_chain.json"
    reg.unlink(missing_ok=True)
    cases = [ROOT / "dataset" / "cases" / "case_genuine", ROOT / "dataset" / "cases" / "case_tampered"]
    cases += sorted(p for p in (ROOT / "dataset" / "redteam").glob("*_*") if (p / "MANIFEST_ground_truth.json").exists())
    # then the demo-order trap: the genuine applicant comes back AFTER the identity ring was remembered,
    # once under the same case ID (a re-run) and once under a new one (a second application)
    runs = [(c, c.name) for c in cases] + [(cases[0], cases[0].name), (cases[0], "case_genuine_second_application")]
    ok = True
    for c, cid in runs:
        files = sorted(str(p) for p in c.iterdir() if p.suffix.lower() in (".pdf", ".jpg", ".jpeg", ".png"))
        d = run_case(files, out / cid, case_id=cid, html=False, registry_path=reg)
        cc = [f for f in d["findings"] if f["check"].startswith("cross_case")]
        loud = [f for f in cc if f["tier"] != "OBSERVATION"]
        expect = c.name.startswith("RT7")
        good = bool(loud) == expect
        ok &= good
        print(f"{'PASS' if good else 'FAIL'} {cid:40s} cross-case: {len(cc)} ({len(loud)} above observation)")
        for f in loud[:3]:
            print(f"      {f['tier'][:3]} {f['title'][:110]}")
    print("\nRESULT:", "ALL PASS" if ok else "FAILURES")


if __name__ == "__main__":
    main()
