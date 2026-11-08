"""Safe failure when files cannot be read.

Found by a hands-on check from a fresh clone: when every uploaded file was rejected (an empty PDF, a file that is
not a PDF, an unsupported type, a damaged image), each was rejected with a reason, but the case status still read
"NO RULE-BREAKING ANOMALY FOUND", which reads as clean although nothing was analysed. The command line also did not
list the skipped files.

* every file rejected: status says NOTHING ANALYSED and "not a clean result", the summary says nothing was checked,
  every file is listed with its reason, the audit chain is intact;
* genuine documents plus broken files: the genuine documents are analysed as before (same counts as alone) and the
  broken files are listed as skipped;
* the command line prints each skipped file with its reason.

    python tests/run_rejected_files.py
"""
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from sakshi import pipeline  # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f"  ({detail})" if detail else ""), flush=True)


def broken_files(folder: Path) -> list[str]:
    folder.mkdir(parents=True)
    (folder / "empty.pdf").write_bytes(b"")
    (folder / "fake.pdf").write_text("this is not a pdf")
    (folder / "notes.txt").write_text("hello")
    (folder / "photo.jpg").write_bytes(bytes(range(256)) * 12)
    return sorted(str(p) for p in folder.iterdir())


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="sakshi_rejected_"))
    try:
        bad = broken_files(tmp / "bad")
        d = pipeline.run_case(bad, tmp / "out_bad", case_id="ALL-REJECTED", html=True)
        check("every file rejected: status says nothing was analysed",
              d["status"].startswith("NOTHING ANALYSED") and "not a clean result" in d["status"], d["status"])
        check("every file rejected: no documents, no findings", not d["documents"] and not d["findings"]
              and d["counts"] == {"potential_manipulation": 0, "inconsistency": 0, "observation": 0})
        check("every file rejected: the summary says nothing was checked",
              "Nothing was checked" in d["summary"] and "No rule-breaking" not in d["summary"])
        check("every file rejected: each file listed with a reason",
              sorted(r["file"] for r in d["rejected"]) == sorted(Path(p).name for p in bad)
              and all(r["reason"] for r in d["rejected"]))
        check("every file rejected: audit chain intact", d["audit"]["verified"])

        genuine = sorted(str(p) for p in (ROOT / "dataset/cases/case_genuine").glob("0*"))
        alone = pipeline.run_case(genuine, tmp / "out_alone", case_id="GENUINE", html=False)
        mixed = pipeline.run_case(genuine + bad[:2], tmp / "out_mixed", case_id="GENUINE-PLUS-BROKEN", html=False)
        check("genuine plus broken files: the genuine documents give the same result as alone",
              mixed["counts"] == alone["counts"] and mixed["status"] == alone["status"]
              and len(mixed["documents"]) == len(genuine), f"{mixed['counts']} vs {alone['counts']}")
        check("genuine plus broken files: the broken files are listed as skipped",
              sorted(r["file"] for r in mixed["rejected"]) == sorted(Path(p).name for p in bad[:2]))

        env = os.environ | {"PYTHONIOENCODING": "utf-8"}
        cli = subprocess.run([sys.executable, "-m", "sakshi", "run", *bad, "--out", str(tmp / "out_cli")], cwd=ROOT,
                             capture_output=True, text=True, encoding="utf-8", env=env, timeout=300)
        out = cli.stdout
        check("command line: status and every skipped file printed",
              "NOTHING ANALYSED" in out and all(f"skipped {Path(p).name}:" in out for p in bad), out.strip()[-200:])
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    ok = all(results)
    print("RESULT:", "ALL PASS" if ok else "FAILURES")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
