"""Check the console's process-isolated case runner (sakshi/console_worker.py).

    python tests/run_console_worker.py

1. A case run in the worker gives the same counts as the in-process pipeline.
2. A case that exceeds its timeout is stopped, its worker process is gone, and the next case runs normally.
3. A second case started while one is running is refused instead of doubling the load.
Exit code 1 on any failure.
"""
from __future__ import annotations

import sys
import tempfile
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sakshi.console_worker import CaseTimeout, ConsoleBusy, run_isolated  # noqa: E402
from sakshi.pipeline import run_case  # noqa: E402


def main() -> int:
    files = sorted(str(p) for p in (ROOT / "dataset" / "cases" / "case_tampered").glob("0*"))
    if not files:
        print("demo case missing: run python dataset/generate.py first")
        return 1
    ok = True

    def check(cond, msg):
        nonlocal ok
        ok &= bool(cond)
        print(("PASS " if cond else "FAIL ") + msg, flush=True)

    ref = run_case(files, Path(tempfile.mkdtemp()), case_id="REF", html=False)["counts"]
    stages = []
    d = run_isolated(files, Path(tempfile.mkdtemp()), case_id="ISO", progress=lambda i, n, s, note: stages.append(s))
    check(d["counts"] == ref, f"worker counts match the in-process pipeline: {d['counts']}")
    check(len(stages) == 10, f"all 10 stages reported progress ({len(stages)})")

    import psutil
    before = {p.pid for p in psutil.Process().children(recursive=True)}
    t = time.time()
    try:
        run_isolated(files, Path(tempfile.mkdtemp()), case_id="SLOW", timeout_s=4)
        check(False, "timeout raised")
    except CaseTimeout as e:
        check(time.time() - t < 30, f"stalled case stopped after its timeout ({time.time() - t:.1f} s): {e}")
    time.sleep(1)
    left = {p.pid for p in psutil.Process().children(recursive=True)} - before
    check(not left, f"no worker process left behind ({len(left)})")
    d2 = run_isolated(files, Path(tempfile.mkdtemp()), case_id="AFTER")
    check(d2["counts"] == ref, "the next case runs normally after a timeout")

    errors = []
    th = threading.Thread(target=lambda: run_isolated(files, Path(tempfile.mkdtemp()), case_id="FIRST"))
    th.start()
    time.sleep(2)
    try:
        run_isolated(files, Path(tempfile.mkdtemp()), case_id="SECOND")
    except ConsoleBusy as e:
        errors.append(e)
    th.join()
    check(len(errors) == 1, "a second case started during a run is refused")

    print("\nRESULT:", "ALL PASS" if ok else "FAILURES")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
