"""Did SAKSHI box the tampered region, or just flag the image? (for datasets with tamper masks, e.g. RTM)

For every tampered image SAKSHI flagged above OBSERVATION, the evidence boxes of those findings (whole-page boxes
excluded) are scaled to the original image and compared with the ground-truth mask. A box counts as on target when
at least 10% of its area is tampered pixels, or it covers at least 25% of the tampered pixels.

    python tests/score_localization.py --bench out/bench_rtm --masks PATH/TO/masks
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--bench", required=True)
    ap.add_argument("--masks", required=True)
    a = ap.parse_args()
    bench = Path(a.bench)
    res = json.loads((bench / "results.json").read_text())
    flagged = on_target = 0
    by_type = {}
    for r in res["rows"]:
        if not r["tampered"] or r["best"] == "NONE" or not r.get("job_id"):
            continue
        flagged += 1
        d = json.loads((bench / "runs" / r["job_id"] / "dossier.json").read_text(encoding="utf-8"))
        page = d["documents"][0]["pages"][0]
        mask = np.array(Image.open(Path(a.masks) / (Path(r["image"]).stem + ".png")).convert("L")) > 0
        H, W = mask.shape
        sx, sy = W / page["width"], H / page["height"]
        hit = False
        for f in d["findings"]:
            if f["tier"] == "OBSERVATION":
                continue
            for e in f["evidence"]:
                if e.get("page", 0) != 0:
                    continue
                x0, y0, x1, y1 = e["bbox"]
                if (x1 - x0) * (y1 - y0) > 0.6 * page["width"] * page["height"]:
                    continue  # a whole-page box localizes nothing
                X0, Y0 = max(0, int(x0 * sx)), max(0, int(y0 * sy))
                X1, Y1 = min(W, int(np.ceil(x1 * sx))), min(H, int(np.ceil(y1 * sy)))
                if X1 <= X0 or Y1 <= Y0:
                    continue
                inter = mask[Y0:Y1, X0:X1].sum()
                if inter >= 0.10 * (X1 - X0) * (Y1 - Y0) or (mask.sum() and inter >= 0.25 * mask.sum()):
                    hit = True
        on_target += hit
        t = Path(r["image"]).stem.rsplit("_", 1)[0]
        by_type.setdefault(t, [0, 0])
        by_type[t][0] += 1
        by_type[t][1] += hit
    tam = sum(1 for r in res["rows"] if r["tampered"] and r["status"] == "done")
    out = {"tampered_images": tam, "flagged": flagged, "flagged_with_a_box_on_the_tampered_region": on_target,
           "by_type_flagged_and_on_target": by_type}
    print(json.dumps(out, indent=1))
    (bench / "localization.json").write_text(json.dumps(out, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
