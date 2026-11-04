"""Verification coverage map: mutation testing of SAKSHI's own reasoning.

For every critical field we ask: if a forger changed only this value, would the
rules notice (detected), and would the repair solver point at this field
(localized)? Fields no rule touches are BLIND and are disclosed to the analyst.
The map is internal to the dossier and never shown to applicants (Gemini's
point that it is otherwise a roadmap for forgers).

Coordinated attacks (Gemini's red-team point that single-field mutation misses
correlated forgeries) are simulated as named recipes.
"""
from __future__ import annotations

import copy

from .invariants import Linear
from .repair import diagnose, equality_key


def _mutate(v):
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        return round(float(v) * 1.137 + 900.0, 2) if v else 1234.0
    s = str(v)
    if len(s) == 10 and s[4] == "-":  # ISO date
        y, m, d = s.split("-")
        return f"{y}-{(int(m) % 12) + 1:02d}-{d}"
    return s[:-1] + ("X" if s[-1:] != "X" else "Y")


def _broken(linear, equality, vals):
    b = {inv.id for inv in linear if all(k in vals for k in inv.coef) and inv.violated(vals)}
    for eq in equality:
        keys = {equality_key(eq.kind, vals[r]) for r in eq.refs}
        if len(keys) > 1:
            b.add(eq.id)
    return b


def coverage(ctx: dict, docs: dict) -> dict:
    rules, meta, fields = ctx["rules"], ctx["meta"], ctx["fields"]
    linear, equality = rules.linear, rules.equality
    # measure coverage on the counterfactually repaired case, so rules that are already broken
    # (because of the forgery itself) still count as watching their fields
    vals = dict(ctx["vals"])
    for dg in ctx.get("diagnoses", []):
        if dg.get("best"):
            vals.update(dg["best"]["fields"])
    from .repair import odd_one_out
    for eq in equality:
        r = odd_one_out(eq, vals, meta)
        if r and r["status"] == "conflict":
            maj = r["clusters"][r["majority_key"]][0]
            for k in r["suspect_refs"]:
                vals[k] = vals[maj]
    base = _broken(linear, equality, vals)
    critical = sorted({k for inv in linear for k in inv.coef} | {r for eq in equality for r in eq.refs})
    # add critical fields that no rule touches (the honest blind spots)
    for k, f in fields.items():
        if f.kind in ("amount", "date", "id", "name") and k not in critical and ".row" not in k:
            critical.append(k)
    rows = []
    for k in critical:
        anchors = [inv.id for inv in linear if k in inv.coef] + [eq.id for eq in equality if k in eq.refs]
        mv = dict(vals)
        mv[k] = _mutate(vals[k])
        new = _broken(linear, equality, mv) - base
        detected = bool(new)
        localized = False
        if detected:
            if any(eq.id in new for eq in equality if k in eq.refs):
                localized = True
            lin_new = [inv for inv in linear if inv.id in new]
            if lin_new:
                dg = diagnose(lin_new + [inv for inv in linear if inv.id not in base and inv.id not in new], mv, meta, max_k=2)
                for d in dg:
                    if d.get("best") and k in d["best"]["fields"] and not d.get("ambiguous"):
                        localized = True
        status = "STRONG" if detected and localized and len(anchors) >= 2 else (
            "WEAK" if detected else "BLIND")
        f = fields[k]
        rows.append({"field": k, "label": f.name, "doc": docs[f.doc_id].filename, "value": f.raw,
                     "anchors": len(anchors), "rules": anchors[:6], "detected": detected, "localized": localized,
                     "status": status})
    summary = {s: sum(1 for r in rows if r["status"] == s) for s in ("STRONG", "WEAK", "BLIND")}
    return {"fields": rows, "summary": summary, "attacks": attacks(ctx, docs, vals),
            "baseline": "measured on the counterfactually repaired values" if ctx.get("diagnoses") else "measured on the values as read"}


def attacks(ctx: dict, docs: dict, vals: dict | None = None) -> list[dict]:
    """Named coordinated forgeries applied in memory to the (repaired) case values."""
    rules, fields = ctx["rules"], ctx["fields"]
    vals = vals or ctx["vals"]
    linear, equality = rules.linear, rules.equality
    base = _broken(linear, equality, vals)
    res = []
    slips = [d for d in docs.values() if d.doc_type == "salary_slip"]
    stmts = [d for d in docs.values() if d.doc_type == "bank_statement"]
    by_id = {inv.id: inv for inv in linear}

    def outcome(name, story, mv):
        new = _broken(linear, equality, mv) - base
        caught = sorted(new)
        res.append({"attack": name, "story": story, "caught": bool(caught),
                    "caught_by": [by_id[i].text if i in by_id else next(e.text for e in equality if e.id == i)
                                  for i in caught][:5]})

    for s in slips:
        earn = [f.key() for f in s.tables.get("earnings", [])]
        g, td, n, nw = (s.fields[x].key() if x in s.fields else None for x in ("gross", "total_deductions", "net_pay", "net_pay_words"))
        if earn and g and td and n:
            mv = dict(vals)
            fac = 1.26
            for k in earn:
                mv[k] = round(vals[k] * fac, 0)
            mv[g] = sum(mv[k] for k in earn)
            mv[n] = mv[g] - vals[td]
            if nw:
                mv[nw] = mv[n]
            outcome("Internally consistent payslip inflation",
                    "Every earnings line, gross, net and the amount in words are raised together so the payslip's own "
                    "arithmetic still holds.", mv)
    for st in stmts:
        rows = st.tables.get("transactions", [])
        emi = [i for i, r in enumerate(rows) if r.get("debit") and "emi" in r["description"].lower()]
        if emi and rows[emi[-1]].get("balance"):
            i = emi[-1]
            mv = dict(vals)
            cut = 10000.0
            mv[rows[i]["debit"].key()] = vals[rows[i]["debit"].key()] - cut
            for r in rows[i:]:
                if r.get("balance"):
                    mv[r["balance"].key()] = vals[r["balance"].key()] + cut
            for k in ("summary_debits", "summary_closing"):
                if k in st.fields:
                    mv[st.fields[k].key()] = vals[st.fields[k].key()] + (cut if k == "summary_closing" else -cut)
            outcome("Hidden loan with a regenerated balance column",
                    "The latest EMI debit is reduced and every later balance and both totals are recomputed so the "
                    "statement's own arithmetic still holds.", mv)
        sal = [i for i, r in enumerate(rows) if r.get("credit") and "salary" in r["description"].lower()]
        if sal and rows[sal[-1]].get("balance"):
            i = sal[-1]
            mv = dict(vals)
            up = round(vals[rows[i]["credit"].key()] * 0.26, 0)
            mv[rows[i]["credit"].key()] += up
            for r in rows[i:]:
                if r.get("balance"):
                    mv[r["balance"].key()] = vals[r["balance"].key()] + up
            for k in ("summary_credits", "summary_closing"):
                if k in st.fields:
                    mv[st.fields[k].key()] = vals[st.fields[k].key()] + up
            outcome("Inflated salary credit with a regenerated statement",
                    "The salary credit and every later balance and total are raised consistently.", mv)
    return res
