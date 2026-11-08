"""A learned layer on real forgeries: does what SAKSHI's sensors report carry signal on real receipts?

Data: the public "Find it again!" receipts (ICDAR 2023), investigated by SAKSHI unchanged
(tests/run_findit.py --json ...). Each receipt becomes a fixed feature vector of what the sensors reported:
for every pixel sensor whether it fired, its highest confidence and how often; which sensors were blind; page size
and measured noise; how many numbers there were to compare. The feature list below was fixed before any model saw
data and was not changed after looking at results.

Protocol:
* the model is an L2-regularised logistic regression (numpy only, coefficients readable);
* the regularisation strength is chosen by 5-fold cross-validation on the TRAIN split only (577 receipts);
* the model is fitted once on the whole train split and scored once on the test (218) and val (193) splits;
* reported: ROC AUC with a 2,000-sample bootstrap 95% interval, compared with SAKSHI's own flag (any finding above
  OBSERVATION), and the forged/genuine flag rates at the threshold that keeps the train split's genuine flag rate
  at 10%.

Caveat stated with the result: the sensors' thresholds were designed before this dataset was used and are not
changed here, but the test and val splits had already been looked at with the rule-based system.

    python tests/learn_receipts.py --runs out/findit_v105 [--json docs/receipt_model.json]
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

import numpy as np

CHECKS = ["glyph_outlier", "intra_token_font", "noise_inconsistency", "compression_ghost", "copy_move",
          "optics_outlier", "zero_variance_patch", "layout_rhythm_break"]
SENSORS = ["noise", "copy_move", "glyphs", "compression", "intra_token_font", "optics"]


def features(dossier: dict) -> list[float]:
    doc = dossier["documents"][0] if dossier["documents"] else {}
    page = (doc.get("pages") or [{}])[0]
    caps = doc.get("capabilities", {})
    fs = dossier.get("findings", [])
    v = []
    for c in CHECKS:
        mine = [f for f in fs if f["check"] == c]
        v += [1.0 if mine else 0.0, max((f["confidence"] for f in mine), default=0.0), float(len(mine))]
    for s in SENSORS:
        v.append(1.0 if str(caps.get(s, "")).startswith("blind") else 0.0)
    w, h = float(page.get("width") or 1), float(page.get("height") or 1)
    m = re.search(r"\((\d+) numeric tokens\)", str(caps.get("glyphs", "")))
    v += [np.log(w * h), np.log(w), float(page.get("noise_sigma") or 0.0), np.log1p(int(m[1]) if m else 0)]
    return v


NAMES = [f"{c}:{k}" for c in CHECKS for k in ("fired", "max_conf", "count")] + [f"blind:{s}" for s in SENSORS] + \
        ["log_area", "log_width", "noise_sigma", "log_numeric_tokens"]


def load(runs: Path, split: str):
    rows = json.loads((runs / f"{split}.json").read_text())
    X, y, flag = [], [], []
    for r in rows:
        p = runs / split / Path(r["image"]).stem / "dossier.json"
        if not p.exists():
            continue
        X.append(features(json.loads(p.read_text(encoding="utf-8"))))
        y.append(1 if r["forged"] else 0)
        flag.append(1 if r["flagged"] else 0)
    return np.array(X, float), np.array(y), np.array(flag)


def fit(X, y, lam, iters=3000, lr=0.1):
    w, b = np.zeros(X.shape[1]), 0.0
    for _ in range(iters):  # full-batch gradient descent on the penalised log-loss (convex)
        p = 1 / (1 + np.exp(-(X @ w + b)))
        g = X.T @ (p - y) / len(y) + lam * w
        w -= lr * g
        b -= lr * float(np.mean(p - y))
    return w, b


def auc(score, y):
    pos, neg = score[y == 1], score[y == 0]
    if not len(pos) or not len(neg):
        return float("nan")
    order = np.argsort(np.concatenate([pos, neg]), kind="mergesort")
    ranks = np.empty(len(order))
    allv = np.concatenate([pos, neg])[order]
    i = 0
    while i < len(allv):  # average ranks for ties
        j = i
        while j + 1 < len(allv) and allv[j + 1] == allv[i]:
            j += 1
        ranks[order[i:j + 1]] = (i + j) / 2 + 1
        i = j + 1
    return float((ranks[:len(pos)].sum() - len(pos) * (len(pos) + 1) / 2) / (len(pos) * len(neg)))


def boot(score, y, n=2000, seed=0):
    rng = np.random.default_rng(seed)
    vals = []
    for _ in range(n):
        i = rng.integers(0, len(y), len(y))
        if y[i].min() != y[i].max():
            vals.append(auc(score[i], y[i]))
    return float(np.percentile(vals, 2.5)), float(np.percentile(vals, 97.5))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", default="out/findit_v105")
    ap.add_argument("--json", default="")
    a = ap.parse_args()
    runs = Path(a.runs)
    Xtr, ytr, _ = load(runs, "train")
    mu, sd = Xtr.mean(0), Xtr.std(0)
    sd[sd == 0] = 1
    z = lambda X: (X - mu) / sd  # noqa: E731
    # regularisation by 5-fold cross-validation on the train split only
    rng = np.random.default_rng(42)
    folds = np.array_split(rng.permutation(len(ytr)), 5)
    cv = {}
    for lam in (0.3, 0.1, 0.03, 0.01, 0.003):
        s = []
        for k in range(5):
            te = folds[k]
            tr = np.concatenate([folds[j] for j in range(5) if j != k])
            w, b = fit(z(Xtr[tr]), ytr[tr], lam)
            s.append(auc(z(Xtr[te]) @ w + b, ytr[te]))
        cv[lam] = float(np.nanmean(s))
    lam = max(cv, key=cv.get)
    w, b = fit(z(Xtr), ytr, lam)
    thr = float(np.percentile((z(Xtr) @ w + b)[ytr == 0], 90))  # train genuine flag rate held at 10%
    print(f"train: {len(ytr)} receipts ({ytr.sum()} forged); CV AUC by lambda: "
          + ", ".join(f"{k}: {v:.3f}" for k, v in cv.items()) + f"; chosen {lam}")
    report = {"protocol": __doc__.split("Protocol:")[1].split("Caveat")[0].strip(), "lambda": lam,
              "cv_auc_train": cv, "features": NAMES, "splits": {}}
    for split in ("test", "val"):
        X, y, flag = load(runs, split)
        s = z(X) @ w + b
        lo, hi = boot(s, y)
        fl_lo, fl_hi = boot(flag.astype(float), y)
        hit = s >= thr
        r = {"receipts": int(len(y)), "forged": int(y.sum()),
             "model_auc": round(auc(s, y), 3), "model_auc_95ci": [round(lo, 3), round(hi, 3)],
             "sakshi_flag_auc": round(auc(flag.astype(float), y), 3),
             "sakshi_flag_auc_95ci": [round(fl_lo, 3), round(fl_hi, 3)],
             "at_train_10pct_threshold": {"forged_flagged": f"{int(hit[y == 1].sum())}/{int(y.sum())}",
                                          "genuine_flagged": f"{int(hit[y == 0].sum())}/{int((y == 0).sum())}"},
             "sakshi_flag": {"forged_flagged": f"{int(flag[y == 1].sum())}/{int(y.sum())}",
                             "genuine_flagged": f"{int(flag[y == 0].sum())}/{int((y == 0).sum())}"}}
        report["splits"][split] = r
        print(f"{split}: model AUC {r['model_auc']} (95% CI {lo:.3f}-{hi:.3f}) vs SAKSHI flag AUC "
              f"{r['sakshi_flag_auc']} (95% CI {fl_lo:.3f}-{fl_hi:.3f}); at the train-chosen threshold: forged "
              f"{r['at_train_10pct_threshold']['forged_flagged']}, genuine {r['at_train_10pct_threshold']['genuine_flagged']}")
    top = sorted(zip(NAMES, w), key=lambda t: -abs(t[1]))[:8]
    report["largest_weights"] = [[n, round(float(v), 3)] for n, v in top]
    report["model"] = {"weights": [round(float(x), 6) for x in w], "bias": round(float(b), 6),
                       "mean": [round(float(x), 6) for x in mu], "scale": [round(float(x), 6) for x in sd],
                       "threshold": round(thr, 6)}
    print("largest weights:", ", ".join(f"{n} {v:+.2f}" for n, v in top))
    if a.json:
        Path(a.json).write_text(json.dumps(report, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
