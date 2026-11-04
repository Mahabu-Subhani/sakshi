"""Minimal counterfactual repair (model-based diagnosis over document invariants).

Question asked for every cluster of broken rules:
    "What is the smallest, most plausible set of field values that, if they had
     been different, would make every rule hold again, and what would those
     values have been?"

Search: subsets of size 1, 2, 3 (Reiter-style minimal diagnoses, brute force is
enough at document scale, as agreed with Gemini). For each subset we solve the
linear system exactly. Cost of blaming a field = witness weight x confidence:
low-confidence OCR reads and self-declared claims are cheap to blame, a
high-confidence bank-statement figure is expensive. Ties are reported, never
hidden.
"""
from __future__ import annotations

import itertools
import re

import numpy as np

from ..models import WITNESS_COST
from .invariants import Equality, Linear

MAX_K = 3
MAX_SUBSETS = 6000


def blame_cost(meta: dict) -> float:
    return WITNESS_COST.get(meta["witness"], 2.0) * (0.25 + 0.75 * meta["conf"])


def _components(violated: list[Linear]) -> list[list[Linear]]:
    comps, seen = [], set()
    for inv in violated:
        if inv.id in seen:
            continue
        stack, comp = [inv], []
        seen.add(inv.id)
        while stack:
            cur = stack.pop()
            comp.append(cur)
            for o in violated:
                if o.id not in seen and set(o.coef) & set(cur.coef):
                    seen.add(o.id)
                    stack.append(o)
        comps.append(comp)
    return comps


def solve_subset(S, relevant: list[Linear], vals: dict):
    """Solve for new values of fields S so every relevant invariant holds. None if infeasible."""
    A = np.array([[inv.coef.get(k, 0.0) for k in S] for inv in relevant], dtype=float)
    b = np.array([inv.b - sum(c * vals[k] for k, c in inv.coef.items() if k not in S) for inv in relevant])
    if not np.any(A):
        return None
    x, *_ = np.linalg.lstsq(A, b, rcond=None)
    if np.max(np.abs(A @ x - b)) > 0.51:
        return None
    rank = np.linalg.matrix_rank(A)
    if rank < len(S):
        return None  # underdetermined: the rules cannot pin these values down
    x = np.round(x, 2)
    if any(abs(x[i] - vals[k]) < 0.5 for i, k in enumerate(S)):
        return None  # not a change: some field in the subset is not actually to blame
    return {k: float(x[i]) for i, k in enumerate(S)}


def diagnose(linear: list[Linear], vals: dict, meta: dict, max_k: int = MAX_K) -> list[dict]:
    hard = [inv for inv in linear if all(k in vals for k in inv.coef)]
    violated = [inv for inv in hard if inv.violated(vals)]
    out = []
    for comp in _components(violated):
        core = sorted({k for inv in comp for k in inv.coef})
        # one-hop expansion: fields tied to the core by rules that currently hold
        linked = [inv for inv in hard if set(inv.coef) & set(core)]
        cands = sorted({k for inv in linked for k in inv.coef} | set(core))
        # keep candidates manageable: core first, then cheapest neighbours
        if len(cands) > 22:
            extra = sorted(set(cands) - set(core), key=lambda k: blame_cost(meta[k]))
            cands = core + extra[: max(0, 22 - len(core))]
        best = []
        for k in range(1, max_k + 1):
            n = 0
            for S in itertools.combinations(cands, k):
                if not set(S) & set(core):
                    continue
                n += 1
                if n > MAX_SUBSETS:
                    break
                relevant = [inv for inv in hard if set(inv.coef) & set(S)] + [i for i in comp if not set(i.coef) & set(S)]
                if any(not set(i.coef) & set(S) for i in comp):
                    continue  # a broken rule in this cluster untouched by S stays broken
                sol = solve_subset(S, relevant, vals)
                if sol is None:
                    continue
                cost = sum(blame_cost(meta[f]) for f in S)
                best.append({"fields": sol, "cost": round(cost, 3), "k": k})
            if best:
                break
        best.sort(key=lambda d: d["cost"])
        diag = {"violated": [inv.id for inv in comp], "violated_text": [inv.text for inv in comp],
                "checks": sorted({inv.check for inv in comp}), "soft_only": all(inv.soft for inv in comp),
                "residuals": {inv.id: round(inv.residual(vals), 2) for inv in comp}, "candidates": len(cands)}
        if best:
            diag["best"] = best[0]
            diag["alternatives"] = best[1:4]
            diag["ambiguous"] = len(best) > 1 and best[1]["cost"] <= best[0]["cost"] * 1.1
        else:
            diag["best"] = None
            diag["alternatives"] = []
            diag["ambiguous"] = True
        out.append(diag)
    return out


# ----------------------------------------------------------------- categorical
TRANSLIT = {"MOHD": "MOHAMMED", "MOHAMMAD": "MOHAMMED", "MUHAMMAD": "MOHAMMED", "MUHAMMED": "MOHAMMED",
            "MOHAMED": "MOHAMMED", "MD": "MOHAMMED", "KR": "KUMAR", "SK": "SHAIKH", "SHEIKH": "SHAIKH",
            "LAKSHMI": "LAXMI", "LAKSMI": "LAXMI"}
OCR_MAP = str.maketrans({"O": "0", "Q": "0", "D": "0", "I": "1", "L": "1", "|": "1", "S": "5", "B": "8", "Z": "2",
                         "G": "6"})
STOP = {"PVT", "PRIVATE", "LTD", "LIMITED", "LLP", "THE", "INC", "CO"}


def name_key(v: str) -> str:
    toks = [TRANSLIT.get(t, t) for t in re.split(r"\s+", v.upper().strip()) if t]
    return " ".join(sorted(t for t in toks if t not in STOP))


def equality_key(kind: str, v):
    if kind == "name":
        return name_key(str(v))
    if kind == "text":
        return re.sub(r"[^a-z0-9]", "", str(v).lower())
    return str(v)


def levenshtein(a: str, b: str) -> int:
    if a == b:
        return 0
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def odd_one_out(eq: Equality, vals: dict, meta: dict) -> dict | None:
    """Cluster the values; the cluster with the least witness weight is the suspect."""
    clusters = {}
    for r in eq.refs:
        clusters.setdefault(equality_key(eq.kind, vals[r]), []).append(r)
    if eq.kind == "text" and len(clusters) > 1:
        # fuzzy merge for free text (addresses): >= 90% similar keys are the same
        keys = list(clusters)
        merged = {}
        for k in keys:
            tgt = next((m for m in merged if 1 - levenshtein(k, m) / max(len(k), len(m), 1) >= 0.9), None)
            if tgt:
                merged[tgt] += clusters[k]
            else:
                merged[k] = list(clusters[k])
        clusters = merged
    if len(clusters) <= 1:
        raw = {vals[r] for r in eq.refs}
        if len(raw) > 1:
            return {"status": "variant", "clusters": {k: v for k, v in clusters.items()}}
        return None
    weight = {k: sum(WITNESS_COST.get(meta[r]["witness"], 2.0) for r in rs) for k, rs in clusters.items()}
    ranked = sorted(weight, key=lambda k: weight[k])
    suspect = ranked[0]
    tie = len(ranked) > 1 and abs(weight[ranked[0]] - weight[ranked[1]]) < 1e-6
    return {"status": "conflict", "clusters": clusters, "weights": weight, "suspect_key": suspect,
            "suspect_refs": clusters[suspect], "majority_key": ranked[-1], "tie": tie}
