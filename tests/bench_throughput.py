"""Throughput: the same 8 applications (4 tampered, 4 genuine demo cases) with 1 worker and with N workers.

Reports wall-clock time and five-document cases per hour, and checks that every case gives the same counts in
both runs. Run it on an otherwise idle machine; numbers depend on the CPU.

    python tests/bench_throughput.py [--workers 4] [--json out.json]
"""
import argparse
import csv
import json
import os
import platform
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from sakshi.service import batch  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--json", default="")
    a = ap.parse_args()
    tmp = Path(tempfile.mkdtemp(prefix="sakshi_bench_"))
    try:
        apps = tmp / "apps"
        for i in range(4):
            for case in ("case_tampered", "case_genuine"):
                shutil.copytree(ROOT / "dataset/cases" / case, apps / f"{case}_{i}")
        runs = {}
        for w in (1, a.workers):
            out = tmp / f"out_{w}"
            s = batch(apps, out, workers=w, echo=lambda *x: None)
            rows = {r["application"]: (r["potential_manipulation"], r["inconsistency"], r["observation"])
                    for r in csv.DictReader(open(out / "summary.csv", encoding="utf-8"))}
            runs[w] = (s, rows)
            print(f"{w} worker(s): {s['done']}/{s['applications']} in {s['wall_seconds']} s -> "
                  f"{s['cases_per_hour']} cases per hour", flush=True)
        same = runs[1][1] == runs[a.workers][1]
        speed = runs[1][0]["wall_seconds"] / runs[a.workers][0]["wall_seconds"]
        print(f"same counts in both runs: {same}; speed-up with {a.workers} workers: {speed:.2f}x "
              f"on {os.cpu_count()} logical CPUs ({platform.processor() or platform.machine()})")
        if a.json:
            Path(a.json).write_text(json.dumps({"cpu_count": os.cpu_count(), "processor": platform.processor(),
                                                "runs": {str(k): v[0] for k, v in runs.items()},
                                                "same_counts": same, "speedup": round(speed, 2)}, indent=1))
        return 0 if same else 1
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
