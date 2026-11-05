"""Score SAKSHI on the public "Find it again!" receipt-forgery dataset (ICDAR 2023, L3i La Rochelle):
real SROIE receipt scans, some forged by hand with image editors, with the forged regions annotated.

    python tests/run_findit.py --data PATH/TO/findit2 [--split test] [--out OUTDIR] [--limit N] [--json results.json]

The dataset is not bundled (download: https://l3i-share.univ-lr.fr/2023Finditagain/index.html).
Every receipt is investigated alone, as a one-document case, with the detection code unchanged.
Forged receipt = DETECTED if any INCONSISTENCY or POTENTIAL_MANIPULATION finding appears, and
LOCALIZED if the evidence box of such a finding overlaps an annotated modified region (copy sources,
'Original area': 'yes', are not targets). Genuine receipt = CLEAN if no such finding appears.
Results are appended per receipt to results.jsonl in OUTDIR, so an interrupted run resumes.
"""
from __future__ import annotations

import argparse
import ast
import csv
import json
import sys
import time
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sakshi.pipeline import run_case  # noqa: E402

ORDER = ["NONE", "OBSERVATION", "INCONSISTENCY", "POTENTIAL_MANIPULATION"]


def targets(annotation: str) -> list[tuple[float, float, float, float]]:
    if not annotation or annotation == "0":
        return []
    ann = ast.literal_eval(annotation)
    boxes = []
    for r in ann.get("regions", []):
        if str(r.get("region_attributes", {}).get("Original area", "no")).lower() == "yes":
            continue
        s = r["shape_attributes"]
        boxes.append((s["x"], s["y"], s["x"] + s["width"], s["y"] + s["height"]))
    return boxes


def overlaps(a, b) -> bool:
    return min(a[2], b[2]) > max(a[0], b[0]) and min(a[3], b[3]) > max(a[1], b[1])


def score_receipt(img: Path, row: dict, out: Path) -> dict:
    t0 = time.time()
    forged = row["forged"] == "1"
    res = {"image": img.name, "forged": forged, "digital_annotation": row["digital annotation"] == "1",
           "handwritten_annotation": row["handwritten annotation"] == "1"}
    try:
        d = run_case([str(img)], out / img.stem, case_id=img.stem, html=False, registry_path=None)
    except Exception as e:  # noqa: BLE001
        res.update({"error": f"{type(e).__name__}: {e}"[:200], "seconds": round(time.time() - t0, 1)})
        return res
    loud = [f for f in d["findings"] if f["tier"] != "OBSERVATION"]
    best = max((f["tier"] for f in loud), key=ORDER.index, default="NONE")
    res.update({"status": d["status"], "counts": d["counts"], "seconds": d["processing_seconds"],
                "flagged": bool(loud), "best_tier": best, "checks": sorted({f["check"] for f in loud}),
                "titles": [f"{f['tier'][:3]} {f['check']}: {f['title'][:100]}" for f in loud[:6]],
                "rejected": [r["reason"] for r in d["rejected"]]})
    if forged:
        tb = targets(row["forgery annotations"])
        res["localized"] = any(overlaps(e["bbox"], t) for f in loud for e in f["evidence"]
                               if e.get("bbox") is not None for t in tb)
        res["n_targets"] = len(tb)
    return res


def summarize(results: list[dict]):
    ok = [r for r in results if "error" not in r]
    errs = [r for r in results if "error" in r]
    fg = [r for r in ok if r["forged"]]
    gen = [r for r in ok if not r["forged"]]
    det = sum(r["flagged"] for r in fg)
    fa = sum(r["flagged"] for r in gen)
    print(f"\nReceipts: {len(results)} ({len(fg)} forged, {len(gen)} genuine, {len(errs)} errors)")
    print(f"Detected {det}/{len(fg)} forged receipts "
          f"({sum(r['best_tier'] == 'POTENTIAL_MANIPULATION' for r in fg)} at POTENTIAL_MANIPULATION); "
          f"localized {sum(r.get('localized', False) for r in fg)}/{len(fg)}")
    print(f"Clean {len(gen) - fa}/{len(gen)} genuine receipts (false alarms: {fa})")
    for name, key in (("handwritten note", "handwritten_annotation"), ("digital note", "digital_annotation")):
        sub = [r for r in gen if r[key]]
        print(f"    genuine with {name}: false alarms {sum(r['flagged'] for r in sub)}/{len(sub)}")
    plain = [r for r in gen if not r["handwritten_annotation"] and not r["digital_annotation"]]
    print(f"    genuine with no note: false alarms {sum(r['flagged'] for r in plain)}/{len(plain)}")
    if det + fa:
        print(f"Precision {det / (det + fa):.2f}, recall {det / max(1, len(fg)):.2f}, "
              f"false-alarm rate {fa / max(1, len(gen)):.2f}")
    for label, group in (("forged", fg), ("genuine", gen)):
        c = Counter(ch for r in group for ch in r["checks"])
        print(f"Checks firing on {label}: " + (", ".join(f"{k} {v}" for k, v in c.most_common()) or "none"))
    if ok:
        print(f"Mean {sum(r['seconds'] for r in ok) / len(ok):.1f} s per receipt")
    for r in errs[:5]:
        print(f"ERROR {r['image']}: {r['error']}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", required=True, help="folder holding test/, train/, val/ and test.txt ...")
    ap.add_argument("--split", default="test", choices=["test", "val", "train"])
    ap.add_argument("--out", default=str(ROOT / "out" / "findit"))
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--json", default="")
    a = ap.parse_args()
    data, out = Path(a.data), Path(a.out) / a.split
    out.mkdir(parents=True, exist_ok=True)
    with open(data / f"{a.split}.txt", newline="", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    if a.limit:
        rows = rows[:a.limit]
    log = out / "results.jsonl"
    done = {}
    if log.exists():
        for line in log.read_text(encoding="utf-8").splitlines():
            r = json.loads(line)
            done[r["image"]] = r
    results = []
    for i, row in enumerate(rows, 1):
        if row["image"] in done:
            results.append(done[row["image"]])
            continue
        r = score_receipt(data / a.split / row["image"], row, out)
        results.append(r)
        with open(log, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(r) + "\n")
        if "error" in r:
            verdict = "ERROR   "
        elif r["forged"]:
            verdict = ("DETECTED" if r["flagged"] else "MISSED  ") + (" +loc" if r.get("localized") else "     ")
        else:
            verdict = ("FALSE+  " if r["flagged"] else "CLEAN   ") + "     "
        print(f"[{i}/{len(rows)}] {verdict} {r['image']}  ({r.get('seconds')}s) {(r.get('titles') or [''])[0][:80]}",
              flush=True)
    summarize(results)
    if a.json:
        Path(a.json).write_text(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
