"""Score SAKSHI on the red-team cases and the layout-varied genuine controls.

    python tests/run_redteam.py [--out OUTDIR] [--json results.json]

Manipulated case = DETECTED if any non-observation finding points at a target document
(and at a target field when the manifest names fields). Genuine case = CLEAN if no
POTENTIAL_MANIPULATION and no INCONSISTENCY finding appears.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sakshi.pipeline import run_case  # noqa: E402

ORDER = ["NONE", "OBSERVATION", "INCONSISTENCY", "POTENTIAL_MANIPULATION"]


def score_case(case_dir: Path, out: Path) -> dict:
    man = json.loads((case_dir / "MANIFEST_ground_truth.json").read_text())
    files = sorted(str(p) for p in case_dir.iterdir() if p.name != "MANIFEST_ground_truth.json")
    reg = None
    if man.get("needs_registry"):
        # cross-case memory: the earlier genuine application of another person is investigated first
        reg = out / "registry_rt.json"
        if reg.exists():
            reg.unlink()
        prior = sorted(str(p) for p in (ROOT / "dataset" / "cases" / "case_genuine").glob("0*"))
        run_case(prior, out / "prior_case_genuine", case_id="DEMO-GENUINE", html=False, registry_path=reg)
    d = run_case(files, out / case_dir.name, case_id=case_dir.name, html=os.environ.get("SAKSHI_HTML", "0") == "1",
                 registry_path=reg)
    docs = {x["doc_id"]: x["filename"] for x in d["documents"]}
    fs = d["findings"] + d.get("document_assessments", [])
    res = {"case": case_dir.name, "manipulated": man["manipulated"], "status": d["status"], "counts": d["counts"],
           "seconds": d["processing_seconds"]}
    if man["manipulated"]:
        best, hits = "NONE", []
        for t in man["targets"]:
            for f in fs:
                if f["tier"] == "OBSERVATION":
                    continue
                on_doc = any(docs.get(x, "").startswith(t["doc"]) for x in f["docs"] + [k.split(".")[0] for k in f["fields"]])
                on_field = not t["fields"] or any(any(fl in k for fl in t["fields"]) for k in f["fields"]) \
                    or f["check"] in ("noise_inconsistency", "glyph_outlier", "copy_move", "scan_clone", "compression_ghost",
                                      "zero_variance_patch", "intra_token_font", "optics_outlier", "document_assessment",
                                      "cross_case_photo_reuse", "cross_case_identifier_reuse", "cross_case_file_reuse")
                if on_doc and on_field:
                    hits.append(f"{f['tier'][:3]} {f['check']}: {f['title'][:90]}")
                    if ORDER.index(f["tier"]) > ORDER.index(best):
                        best = f["tier"]
        res.update({"detected": best != "NONE", "best_tier": best, "hits": hits[:8]})
    else:
        bad = [f for f in d["findings"] if f["tier"] != "OBSERVATION"]
        res.update({"clean": not bad, "false_alarms": [f"{f['tier'][:3]} {f['check']}: {f['title'][:100]}" for f in bad]})
    return res


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(ROOT / "out" / "redteam"))
    ap.add_argument("--json", default="")
    a = ap.parse_args()
    cases = sorted((ROOT / "dataset" / "redteam").glob("*_*"))
    results = []
    for c in cases:
        if not (c / "MANIFEST_ground_truth.json").exists():
            continue
        r = score_case(c, Path(a.out))
        results.append(r)
        if r["manipulated"]:
            print(f"{'DETECTED' if r['detected'] else 'MISSED  '} {r['best_tier']:24s} {r['case']}  ({r['seconds']}s)")
            for h in r["hits"][:4]:
                print("     ", h)
        else:
            print(f"{'CLEAN   ' if r['clean'] else 'FALSE+  '} {'':24s} {r['case']}  ({r['seconds']}s)")
            for h in r["false_alarms"][:6]:
                print("     ", h)
    man = [r for r in results if r["manipulated"]]
    gen = [r for r in results if not r["manipulated"]]
    print(f"\nDetected {sum(r['detected'] for r in man)}/{len(man)} manipulated cases "
          f"({sum(r['best_tier'] == 'POTENTIAL_MANIPULATION' for r in man)} at POTENTIAL_MANIPULATION); "
          f"clean {sum(r['clean'] for r in gen)}/{len(gen)} genuine cases")
    if a.json:
        Path(a.json).write_text(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
