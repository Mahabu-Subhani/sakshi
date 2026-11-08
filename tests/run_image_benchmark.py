"""Run SAKSHI, unchanged, on a folder of single real document images and count what it raises.

Used for public datasets that are not bundled (their licences forbid redistribution or are unclear):

* genuine real scans (e.g. FUNSD, 199 scanned business forms): how often does SAKSHI flag an untouched real
  scan, at INCONSISTENCY and at POTENTIAL MANIPULATION, and which sensors fire?
* labelled real tampering (e.g. RTM): pass --tampered-list with the names of tampered images; the rest are genuine.

Each image is investigated alone, in its own isolated worker process, several side by side.

    python tests/run_image_benchmark.py --images PATH/TO/images --name funsd --out out/bench_funsd --workers 3
    python tests/run_image_benchmark.py --images DIR --tampered-list tampered.txt --name rtm ...
"""
from __future__ import annotations

import argparse
import collections
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from sakshi.service import Jobs  # noqa: E402

IMG = {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp", ".webp"}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--images", required=True)
    ap.add_argument("--name", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--workers", type=int, default=3)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--tampered-list", default="", help="file with one tampered image name (stem) per line")
    a = ap.parse_args()
    imgs = sorted(p for p in Path(a.images).iterdir() if p.suffix.lower() in IMG)
    if a.limit:
        imgs = imgs[:a.limit]
    tampered = set()
    if a.tampered_list:
        tampered = {Path(x.strip()).stem for x in Path(a.tampered_list).read_text().splitlines() if x.strip()}
    out = Path(a.out)
    jobs = Jobs(out / "runs", workers=a.workers, timeout_s=300)
    t0 = time.time()
    ids = [(p, jobs.submit([p], case_id=p.stem)) for p in imgs]
    jobs.wait()
    rows = []
    for p, jid in ids:
        j = jobs.get(jid)
        d = {}
        dj = Path(j["out"]) / "dossier.json"
        if j["status"] == "done" and dj.exists():
            d = json.loads(dj.read_text(encoding="utf-8"))
        fs = [f for f in d.get("findings", []) if f["tier"] != "OBSERVATION"]
        rows.append({"image": p.name, "job_id": jid, "tampered": p.stem in tampered, "status": j["status"],
                     "error": j.get("error", ""), "counts": d.get("counts"),
                     "best": "POTENTIAL_MANIPULATION" if any(f["tier"] == "POTENTIAL_MANIPULATION" for f in fs)
                     else "INCONSISTENCY" if fs else "NONE",
                     "checks": sorted({f["check"] for f in fs}),
                     "blind": sorted(k for k, v in (d.get("documents") or [{}])[0].get("capabilities", {}).items()
                                     if str(v).startswith("blind"))})
    ok = [r for r in rows if r["status"] == "done"]

    def rate(group, tier):
        n = len(group)
        k = sum(1 for r in group if (r["best"] != "NONE" if tier == "any" else r["best"] == tier))
        return {"n": n, "flagged": k, "rate": round(k / n, 3) if n else None}

    gen = [r for r in ok if not r["tampered"]]
    tam = [r for r in ok if r["tampered"]]
    summary = {"dataset": a.name, "images": len(rows), "completed": len(ok), "failed": len(rows) - len(ok),
               "wall_seconds": round(time.time() - t0, 1), "workers": a.workers,
               "genuine": {"any_flag": rate(gen, "any"), "potential_manipulation": rate(gen, "POTENTIAL_MANIPULATION"),
                           "checks_firing": collections.Counter(c for r in gen for c in r["checks"]).most_common()},
               "blind_sensors": collections.Counter(b for r in ok for b in r["blind"]).most_common()}
    if tam:
        summary["tampered"] = {"any_flag": rate(tam, "any"),
                               "potential_manipulation": rate(tam, "POTENTIAL_MANIPULATION"),
                               "checks_firing": collections.Counter(c for r in tam for c in r["checks"]).most_common()}
    (out / "results.json").write_text(json.dumps({"summary": summary, "rows": rows}, indent=1))
    print(json.dumps(summary, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
