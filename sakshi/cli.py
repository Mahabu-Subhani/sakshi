"""Command line interface.

  python -m sakshi demo [--regenerate]          investigate both demo cases (the documents in dataset/cases)
  python -m sakshi run FILE [FILE ...] --out DIR [--case-id ID] [--lang eng+hin] [--memory registry.json] [--password PW ...]
  python -m sakshi redteam [--regenerate]       score SAKSHI on the red-team cases (the documents in dataset/redteam)
  python -m sakshi batch APPLICATIONS_DIR --out DIR [--workers N] [--memory registry.json]
  python -m sakshi serve [--host 127.0.0.1] [--port 8600] [--workers N] [--out DIR] [--memory registry.json]
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
    for r in d.get("rejected", []):
        print(f"  ! skipped {r['file']}: {r['reason'].removeprefix(r['file'] + ': ')}")
    for t in d["threads"][:6]:
        print(f"  - [{t['tier']}] {t['title'][:150]}")


def _has_docs(case_dir: Path) -> bool:
    return case_dir.is_dir() and any(case_dir.glob("0*"))


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
    regen = ("--regenerate", {"action": "store_true",
                              "help": "rebuild the documents with this machine's fonts and libraries first "
                                      "(results can then differ slightly from the published ones)"})
    rt = sub.add_parser("redteam", help="score SAKSHI on the red-team cases")
    rt.add_argument(regen[0], **regen[1])
    dm = sub.add_parser("demo", help="investigate both demo cases")
    dm.add_argument(regen[0], **regen[1])
    b = sub.add_parser("batch", help="investigate every application in a folder (one sub-folder each), in parallel")
    b.add_argument("folder")
    b.add_argument("--out", required=True)
    b.add_argument("--workers", type=int, default=2, help="cases run side by side, each in its own process")
    b.add_argument("--memory", help="cross-case memory file")
    b.add_argument("--lang", default="eng")
    sv = sub.add_parser("serve", help="REST API for a loan-origination system (POST /v1/cases)")
    sv.add_argument("--host", default="127.0.0.1")
    sv.add_argument("--port", type=int, default=8600)
    sv.add_argument("--workers", type=int, default=2)
    sv.add_argument("--out", default=str(ROOT / "out" / "service"))
    sv.add_argument("--memory", help="cross-case memory file")
    sv.add_argument("--lang", default="eng")
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
        # the published documents are used as they are, so everyone investigates the same files; rebuilding them
        # draws them with this machine's fonts, which can change OCR and therefore the counts
        cases = ROOT / "dataset" / "cases"
        if a.regenerate or not all(_has_docs(cases / c) for c in ("case_tampered", "case_genuine")):
            subprocess.run([sys.executable, str(ROOT / "dataset" / "generate.py")], check=True)
        for case, cid in (("case_tampered", "DEMO-TAMPERED"), ("case_genuine", "DEMO-GENUINE")):
            files = sorted(str(p) for p in (ROOT / "dataset" / "cases" / case).glob("0*"))
            print(f"\n== {cid}")
            d = run_case(files, ROOT / "out" / case, case_id=cid, progress=_progress)
            _report(d)
            print(f"  Dossier: {ROOT / 'out' / case / 'dossier.html'}")
    elif a.cmd == "redteam":
        if a.regenerate or not _has_docs(ROOT / "dataset" / "cases" / "case_genuine"):
            subprocess.run([sys.executable, str(ROOT / "dataset" / "generate.py")], check=True)
        rdir = ROOT / "dataset" / "redteam"
        if a.regenerate or not any(_has_docs(d) for d in rdir.glob("*") if d.is_dir() and not d.name.startswith("_")):
            subprocess.run([sys.executable, str(ROOT / "dataset" / "redteam.py")], check=True)
        subprocess.run([sys.executable, str(ROOT / "tests" / "run_redteam.py")], check=True)
    elif a.cmd == "batch":
        from .service import batch
        batch(a.folder, a.out, workers=a.workers, memory=a.memory, lang=a.lang)
    elif a.cmd == "serve":
        from .service import serve
        serve(host=a.host, port=a.port, workers=a.workers, out=a.out, memory=a.memory, lang=a.lang)
    elif a.cmd == "verify-audit":
        from .audit import AuditLog
        ok, msg = AuditLog(a.path, "verify").verify()
        print(msg)
        sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
