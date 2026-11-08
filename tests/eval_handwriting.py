"""Who reads real handwriting better, Tesseract or TrOCR? Measured on FUNSD's real scanned forms.

FUNSD (Jaume et al., 2019) annotates every text entity on 199 real scanned forms with its box and its true text,
handwritten entries included. Its terms allow non-commercial research use and forbid redistribution: it is not
bundled, and only aggregate numbers are published.

For every single-line entity of the 50 test forms, the same crop is read by Tesseract (one line, as SAKSHI reads it)
and by TrOCR, and each is scored by character error rate (CER: edit distance / length of the true text, case and
spacing ignored). Reported for all lines, and for the lines SAKSHI would actually hand to TrOCR: those Tesseract
read with mean word confidence below 0.5.

    python tests/eval_handwriting.py --funsd PATH/TO/funsd [--json out.json]
"""
from __future__ import annotations

import argparse
import json
import re
import statistics
import sys
from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from sakshi import handwriting  # noqa: E402
from sakshi.reasoning.repair import levenshtein  # noqa: E402


def norm(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip().lower()


def cer(pred: str, truth: str) -> float:
    t = norm(truth)
    return levenshtein(norm(pred), t) / max(1, len(t))


def tesseract_line(img: Image.Image) -> tuple[str, float]:
    import pytesseract
    d = pytesseract.image_to_data(img, config="--oem 1 --psm 7", output_type=pytesseract.Output.DICT)
    words = [(t, float(c)) for t, c in zip(d["text"], d["conf"]) if str(t).strip() and float(c) >= 0]
    if not words:
        return "", 0.0
    return " ".join(t for t, _ in words), float(np.mean([c for _, c in words])) / 100


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--funsd", required=True, help="folder holding images/ and annotations/test/")
    ap.add_argument("--json", default="")
    a = ap.parse_args()
    if handwriting.status() != "ok":
        print("TrOCR not available:", handwriting.status())
        return 2
    root = Path(a.funsd)
    rows = []
    for ann in sorted((root / "annotations" / "test").glob("*.json")):
        img = Image.open(root / "images" / (ann.stem + ".png")).convert("RGB")
        form = json.loads(ann.read_text(encoding="utf-8"))["form"]
        hs = [w["box"][3] - w["box"][1] for e in form for w in e["words"]]
        med = statistics.median(hs) if hs else 10
        for e in form:
            x0, y0, x1, y1 = e["box"]
            if not norm(e["text"]) or (y1 - y0) > 2.2 * med or (x1 - x0) < 4:
                continue  # single-line entities only: TrOCR reads one line at a time
            pad = max(3, (y1 - y0) // 4)
            crop = img.crop((max(0, x0 - pad), max(0, y0 - pad), x1 + pad, y1 + pad))
            tt, tc = tesseract_line(crop)
            rows.append({"form": ann.stem, "truth": e["text"], "tesseract": tt, "tesseract_conf": tc, "crop": crop})
    print(f"{len(rows)} single-line entities on {len(list((root / 'annotations' / 'test').glob('*.json')))} forms; "
          "reading them with TrOCR...", flush=True)
    for r, (text, conf) in zip(rows, handwriting.read_lines([r["crop"] for r in rows])):
        r["trocr"], r["trocr_conf"] = text, conf

    def summary(sel):
        if not sel:
            return {"lines": 0}
        te = [cer(r["tesseract"], r["truth"]) for r in sel]
        tr = [cer(r["trocr"], r["truth"]) for r in sel]
        better = sum(b < c for b, c in zip(tr, te))
        return {"lines": len(sel), "tesseract_cer_mean": round(float(np.mean(te)), 3),
                "trocr_cer_mean": round(float(np.mean(tr)), 3),
                "tesseract_exact": sum(c == 0 for c in te), "trocr_exact": sum(c == 0 for c in tr),
                "trocr_better_lines": better, "tesseract_better_lines": sum(c < b for b, c in zip(tr, te))}

    low = [r for r in rows if r["tesseract_conf"] < handwriting.LOW_CONF]
    res = {"dataset": "FUNSD test split (50 real scanned forms)", "all_lines": summary(rows),
           "lines_sakshi_hands_to_trocr": summary(low), "trigger": f"Tesseract mean word confidence < {handwriting.LOW_CONF}"}
    # SAKSHI's actual behaviour: TrOCR's reading shown only for low-confidence lines
    combined = [cer(r["trocr"] if r["tesseract_conf"] < handwriting.LOW_CONF else r["tesseract"], r["truth"]) for r in rows]
    res["all_lines"]["cer_mean_with_trocr_on_low_confidence_lines"] = round(float(np.mean(combined)), 3)
    print(json.dumps(res, indent=1))
    if a.json:
        Path(a.json).write_text(json.dumps(res, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
