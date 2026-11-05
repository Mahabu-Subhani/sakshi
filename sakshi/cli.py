"""Command line interface.

  python -m sakshi demo                         generate the demo dataset and investigate both cases
  python -m sakshi run FILE [FILE ...] --out DIR [--case-id ID] [--lang eng+hin] [--memory registry.json] [--password PW ...]
  python -m sakshi redteam                      build the blind red-team cases and score SAKSHI on them
  python -m sakshi verify-audit DIR/audit.jsonl
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _progress(i, n, stage, note):
    bar = "#" * (i + 1) + "." * (n - i - 1)
    print(f"  [{bar}] {stage}{(' · ' + note) if note else ''}", flush=True)


def _report(d):
    print(f"\n{d['status']}")
    print(f"  potential manipulation {d['counts']['potential_manipulation']} · inconsistency {d['counts']['inconsistency']} "
          f"· observation {d['counts']['observation']} · {d['processing_seconds']}s")
    for t in d["threads"][:6]:
        print(f"  - [{t['tier']}] {t['title'][:150]}")


def main(argv=None):
    ap = argparse.ArgumentParser(prog="sakshi", description="SAKSHI document forensics")
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run", help="investigate a set of documents belonging to one application")
    r.add_argument("files", nargs="+")
    r.add_argument("--out", required=True)
    r.add_argument("--case-id")
    r.add_argument("--lang", default="eng", help="Tesseract languages, e.g. eng or eng+hin")
    r.add_argument("--memory", help="cross-case memory file (remembers fingerprints of earlier cases)")
    r.add_argument("--password", action="append", default=[],
                   help="password for a locked PDF (repeat for several); tried on every locked PDF, never stored")
    sub.add_parser("redteam", help="build the blind red-team cases and score SAKSHI on them")
    sub.add_parser("demo", help="generate the demo dataset and investigate both cases")
    v = sub.add_parser("verify-audit", help="verify a hash-chained audit log")
    v.add_argument("path")
    a = ap.parse_args(argv)

    from .pipeline import run_case
    if a.cmd == "run":
        d = run_case(a.files, a.out, case_id=a.case_id, progress=_progress, lang=a.lang, registry_path=a.memory,
                     passwords=a.password)
        _report(d)
        print(f"\nDossier: {Path(a.out) / 'dossier.html'}")
    elif a.cmd == "demo":
        subprocess.run([sys.executable, str(ROOT / "dataset" / "generate.py")], check=True)
        for case, cid in (("case_tampered", "DEMO-TAMPERED"), ("case_genuine", "DEMO-GENUINE")):
            files = sorted(str(p) for p in (ROOT / "dataset" / "cases" / case).glob("0*"))
            print(f"\n== {cid}")
            d = run_case(files, ROOT / "out" / case, case_id=cid, progress=_progress)
            _report(d)
            print(f"  Dossier: {ROOT / 'out' / case / 'dossier.html'}")
    elif a.cmd == "redteam":
        if not (ROOT / "dataset" / "cases" / "case_genuine").exists():
            subprocess.run([sys.executable, str(ROOT / "dataset" / "generate.py")], check=True)
        subprocess.run([sys.executable, str(ROOT / "dataset" / "redteam.py")], check=True)
        subprocess.run([sys.executable, str(ROOT / "tests" / "run_redteam.py")], check=True)
    elif a.cmd == "verify-audit":
        from .audit import AuditLog
        ok, msg = AuditLog(a.path, "verify").verify()
        print(msg)
        sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
