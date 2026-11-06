"""Contextual intelligence: runs the invariant library, the repair solver and the
equality diagnosis, and turns the results into evidence-backed findings."""
from __future__ import annotations

import re

import numpy as np
from datetime import date

from ..extract import parse_date
from ..models import Document, Evidence, Finding, Tier
from . import invariants as INV
from .repair import diagnose, levenshtein, odd_one_out, OCR_MAP

FIELD_LABEL = {
    "net_pay": "Net Pay", "net_pay_words": "Net Pay in words", "gross": "Gross Earnings",
    "total_deductions": "Total Deductions", "declared_income": "Declared net monthly income",
    "declared_emi": "Declared monthly EMIs", "letter_salary": "Salary stated in letter", "debit": "Debit",
    "credit": "Credit", "balance": "Balance", "summary_debits": "Total Debits", "summary_credits": "Total Credits",
    "summary_opening": "Opening Balance", "summary_closing": "Closing Balance", "dob": "Date of birth",
    "date_of_joining": "Date of joining", "employee_id": "Employee ID", "account_no": "Account number",
}


def collect(docs: dict):
    fields, vals, meta = {}, {}, {}
    for d in docs.values():
        fs = list(d.fields.values())
        for t in ("earnings", "deductions"):
            fs += d.tables.get(t, [])
        for r in d.tables.get("transactions", []):
            fs += [r[c] for c in ("date", "debit", "credit", "balance") if r.get(c)]
        for f in fs:
            fields[f.key()] = f
            vals[f.key()] = f.value
            meta[f.key()] = {"witness": d.witness, "conf": f.conf, "doc": d.doc_id}
    return fields, vals, meta


def label(f, docs) -> str:
    base = f.name.split(".")[-1]
    nm = FIELD_LABEL.get(base, base.replace("_", " ").capitalize())
    if f.name.startswith("row"):
        rows = docs[f.doc_id].tables.get("transactions", [])
        i = int(re.match(r"row(\d+)", f.name).group(1))
        if i < len(rows):
            r = rows[i]
            nm = f"{nm} on {r['date'].raw if r.get('date') else '?'} ({r['description'][:28]})"
    return f"{nm} [{docs[f.doc_id].filename}]"


def fmt(v) -> str:
    if isinstance(v, float):
        from ..extract import parse_amount  # noqa
        s = f"{v:,.2f}"
        whole, frac = s.split(".")
        whole = whole.replace(",", "")
        if len(whole) > 3:
            head, tail = whole[:-3], whole[-3:]
            parts = []
            while len(head) > 2:
                parts.insert(0, head[-2:]); head = head[:-2]
            if head:
                parts.insert(0, head)
            whole = ",".join(parts + [tail])
        return f"{whole}.{frac}"
    return str(v)


def run(docs: dict, new_id) -> tuple[list[Finding], dict]:
    fields, vals, meta = collect(docs)
    rules = INV.build(docs, fields)
    out: list[Finding] = []
    ctx = {"fields": fields, "vals": vals, "meta": meta, "rules": rules, "diagnoses": []}

    # ------------------------------------------------------------ linear diagnosis
    diags = diagnose(rules.linear, vals, meta)
    by_id = {inv.id: inv for inv in rules.linear}
    missing_rec = [e for e in rules.expectations if not e["found"] and e.get("kind") == "recurring"]
    used_missing = set()
    for di, dg in enumerate(diags):
        dg["id"] = f"DX{di + 1}"
        ctx["diagnoses"].append(dg)
        broken = [by_id[i] for i in dg["violated"]]
        # structural counterfactual: is the chain consistent if one recurring row had not been removed?
        drow = None
        for inv in broken:
            if inv.check != "balance_chain_break":
                continue
            r = inv.residual(vals)
            bal_ref = next(k for k, c in inv.coef.items() if c == -1 and k.endswith(".balance"))
            month = None
            row_date_ref = bal_ref.replace(".balance", ".date")
            if row_date_ref in vals:
                month = str(vals[row_date_ref])[:7]
            for j, e in enumerate(missing_rec):
                if abs(r - e["amount"]) <= 0.51 and (month is None or month == e["month"]):
                    drow = (inv, e, bal_ref, j)
                    break
            if drow:
                break
        if drow and (dg["best"] is None or dg["best"]["k"] >= 2):
            inv, e, bal_ref, j = drow
            used_missing.add(j)
            f = fields[bal_ref]
            dg["best_structural"] = {"deleted_row_amount": e["amount"], "month": e["month"], "at": bal_ref}
            out.append(Finding(
                id=new_id(), check="deleted_row", family="logical", sensor="repair_solver",
                title=(f"A {fmt(e['amount'])} debit appears to have been removed from {docs[f.doc_id].filename}: "
                       f"the balance {f.raw} holds only if that row existed"),
                detail=(f"{inv.text} is off by exactly {fmt(e['amount'])}. The statement's own recurring "
                        f"obligation {e['text'].split(' seen in ')[0]} appears in earlier months but not in {e['month']}. "
                        "Two independent facts agree: the running balance drops by exactly that amount at a point where "
                        "no row is printed, and the recurring debit of that amount is missing in that month. The value "
                        "solver cannot express a deleted row, so this structural explanation is reported instead."),
                confidence=0.9, localized=True,
                evidence=[Evidence(f.doc_id, f.page, f.bbox, f"balance {f.raw} does not follow from the row above",
                                   kind="field", value=f.raw),
                          Evidence(fields[e["ref"]].doc_id, fields[e["ref"]].page, fields[e["ref"]].bbox,
                                   f"the same obligation in an earlier month ({fields[e['ref']].raw})", kind="field",
                                   value=fields[e["ref"]].raw)],
                fields=[bal_ref], docs=[f.doc_id],
                repair={"diagnosis": dg["id"], "families": ["logical", "pattern"], "checks": ["balance_chain_break",
                        "recurring_missing"], "deleted_amount": e["amount"], "month": e["month"]},
                verify_next="Ask the bank for the statement directly (or via Account Aggregator) and check for the "
                            f"{e['month']} debit."))
            continue
        if dg["best"] is None:
            refs = sorted({k for inv in broken for k in inv.coef})
            out.append(Finding(
                id=new_id(), check=broken[0].check, family="cross_document" if any(b.scope == "cross" for b in broken) else "logical",
                sensor="invariants",
                title=f"{len(broken)} rule(s) broken with no unique explanation: {broken[0].text}",
                detail="No set of up to 3 field changes restores consistency. Several fields may be wrong, or a row was not parsed.",
                confidence=0.6, evidence=[Evidence(fields[r].doc_id, fields[r].page, fields[r].bbox, label(fields[r], docs),
                                                   kind="field", value=fields[r].raw) for r in refs[:8]],
                fields=refs, docs=sorted({fields[r].doc_id for r in refs}), repair={"diagnosis": dg["id"]}))
            continue
        fix = dg["best"]["fields"]
        alt_txt = ""
        if dg["alternatives"]:
            a = dg["alternatives"][0]
            alt_txt = (" Next most plausible explanation (cost " f"{a['cost']:.2f} vs {dg['best']['cost']:.2f}): change "
                       + ", ".join(f"{label(fields[k], docs)} to {fmt(v)}" for k, v in a["fields"].items()) + ".")
        for ref, newv in fix.items():
            f = fields[ref]
            mine = [inv for inv in rules.linear if ref in inv.coef and all(k in vals for k in inv.coef)]
            mine_broken = [inv for inv in mine if inv.violated(vals)]
            fixed_by = [inv for inv in mine if inv.id in dg["violated"]]
            checks = sorted({inv.check for inv in (mine_broken or fixed_by or mine)})
            fams = sorted({"cross_document" if inv.scope == "cross" else "logical" for inv in (mine_broken or mine)})
            is_claim = docs[f.doc_id].witness == 0
            others = [k for k in fix if k != ref]
            title = (f"{label(f, docs)} reads {fmt(f.value)}; the documents are consistent only if it were {fmt(newv)}")
            detail = (f"Broken rules in this cluster: " + "; ".join(inv.text + f" (off by {fmt(abs(inv.residual(vals)))})"
                                                                   for inv in broken) + ". "
                      f"Searching every combination of up to {dg['best']['k']} field change(s), the cheapest set that makes "
                      f"every rule hold again changes {len(fix)} value(s)"
                      + (": this one, plus " + ", ".join(f"{label(fields[k], docs)} to {fmt(fix[k])}" for k in others)
                         if others else ": this one alone") + ". " + alt_txt)
            if is_claim:
                detail += " This document is a self-declaration (witness level L0), so the mismatch describes what the applicant claimed, not a forged record."
            out.append(Finding(
                id=new_id(), check=checks[0] if checks else "arithmetic_break", family=fams[0] if len(fams) == 1 else "logical",
                sensor="repair_solver", title=title, detail=detail,
                confidence=0.9 if not dg.get("ambiguous") else 0.6, localized=not dg.get("ambiguous"),
                evidence=[Evidence(f.doc_id, f.page, f.bbox, f"reads {fmt(f.value)}; consistent value {fmt(newv)}",
                                   kind="field", value=f.raw)] +
                         [Evidence(fields[k].doc_id, fields[k].page, fields[k].bbox, label(fields[k], docs), kind="field",
                                   value=fields[k].raw) for inv in broken for k in inv.coef if k != ref
                          and abs(inv.coef[k]) > 0][:6],
                fields=[ref], docs=sorted({fields[k].doc_id for inv in broken for k in inv.coef} | {f.doc_id}),
                repair={"diagnosis": dg["id"], "current": f.value, "proposed": newv, "families": fams,
                        "checks": checks, "rules": [inv.text for inv in broken], "cost": dg["best"]["cost"],
                        "ambiguous": dg.get("ambiguous", False), "soft_only": dg.get("soft_only", False),
                        "claim": is_claim},
                verify_next=("Ask the applicant to explain the declared figure." if is_claim else
                             "Obtain this record directly from its issuer and compare the value.")))

    # ------------------------------------------------------------ equality diagnosis
    for eq in rules.equality:
        res = odd_one_out(eq, vals, meta)
        if not res:
            continue
        refs = eq.refs
        if res["status"] == "variant":
            out.append(Finding(
                id=new_id(), check="name_mismatch" if eq.kind == "name" else "cross_doc_mismatch", family="identity",
                sensor="equality", title=f"{eq.attr.replace('_', ' ').title()} written differently but equivalent: "
                + " / ".join(sorted({str(fields[r].raw) for r in refs})),
                detail=f"{eq.text}: the spellings differ but resolve to the same value after normalization "
                       "(transliteration, punctuation, word order).",
                tier=Tier.OBSERVATION, confidence=0.4,
                evidence=[Evidence(fields[r].doc_id, fields[r].page, fields[r].bbox, docs[fields[r].doc_id].filename,
                                   kind="field", value=fields[r].raw) for r in refs],
                fields=list(refs), docs=sorted({fields[r].doc_id for r in refs}),
                repair={"equivalent": True}))
            continue
        sus = res["suspect_refs"]
        maj = res["clusters"][res["majority_key"]]
        check = {"name": "name_mismatch", "date": "date_mismatch", "id": "id_mismatch"}.get(eq.kind, "cross_doc_mismatch")
        sv = fields[sus[0]].raw
        mv = fields[maj[0]].raw
        out.append(Finding(
            id=new_id(), check=check, family="cross_document", sensor="equality",
            title=(f"{eq.attr.replace('_', ' ').title()} conflict: {docs[fields[sus[0]].doc_id].filename} says '{sv}', "
                   f"{', '.join(docs[fields[r].doc_id].filename for r in maj)} say{'s' if len(maj) == 1 else ''} '{mv}'"),
            detail=(f"{eq.text}. Values group into {len(res['clusters'])} versions. Weighted by witness reliability "
                    f"({', '.join(f'{k}: {w:.1f}' for k, w in res['weights'].items())}), the least-supported version is the "
                    f"one on {docs[fields[sus[0]].doc_id].filename}." + (" The weights tie, so the suspect is uncertain." if res["tie"] else "")),
            confidence=0.55 if res["tie"] else 0.8, localized=not res["tie"],
            evidence=[Evidence(fields[r].doc_id, fields[r].page, fields[r].bbox,
                               ("suspect: " if r in sus else "") + docs[fields[r].doc_id].filename, kind="field",
                               value=fields[r].raw) for r in refs],
            fields=list(sus), docs=sorted({fields[r].doc_id for r in refs}),
            repair={"suspect": sv, "majority": mv, "attr": eq.attr, "tie": res["tie"], "kind": eq.kind,
                    "all_refs": list(refs)},
            verify_next="Check the original of the suspect document, or ask the issuer to confirm the value."))

    # ------------------------------------------------------------ expectations (counterfactual, deterministic)
    for j, ex in enumerate(rules.expectations):
        if ex["found"]:
            continue
        d = docs[ex["doc"]]
        if ex.get("kind") == "recurring":
            if any(missing_rec[k] is ex for k in used_missing):
                continue  # already explained as a deleted row
            ref = fields.get(ex["ref"])
            out.append(Finding(
                id=new_id(), check="recurring_missing", family="pattern", sensor="expectations",
                title=ex["text"], detail="A fixed obligation (EMI, loan, rent, SIP, premium) normally repeats every month. "
                "Its absence can mean the loan closed or was prepaid, or that the row was removed.",
                confidence=0.6, localized=bool(ref),
                evidence=[Evidence(ref.doc_id, ref.page, ref.bbox, "earlier occurrence", kind="field", value=ref.raw)] if ref
                else [Evidence(d.doc_id, 0, (0, 0, d.pages[0].width, 60), "statement")],
                docs=[d.doc_id], fields=[],
                verify_next="Ask whether the loan was closed or prepaid; request the lender's loan statement."))
            continue
        out.append(Finding(
            id=new_id(), check="missing_expected_record", family="cross_document", sensor="expectations",
            title=ex["text"] + ": not found", detail="The statement covers the pay date but contains no credit that "
            "looks like salary (narration with SALARY/payroll/employer name) in the expected window.",
            confidence=0.7, evidence=[Evidence(d.doc_id, 0, (0, 0, d.pages[0].width, 60), "statement")],
            docs=[d.doc_id]))

    for st in rules.statutory:
        if st["ok"]:
            continue
        fs = [fields[k] for k in st["fields"]]
        implied = ""
        if st["id"].endswith("S1"):
            pf = st["actual"]
            implied = f" The PF actually deducted corresponds to a basic of {fmt(round(pf / 0.12, 2))}."
        out.append(Finding(
            id=new_id(), check="statutory_mismatch", family="statutory", sensor="statutory",
            title=st["text"], detail=("Payroll software computes statutory deductions from the same figures it prints. "
                                      "A deduction that does not match the printed basic suggests the basic (and what "
                                      "depends on it) was changed after the payroll run." + implied),
            confidence=0.75, localized=True,
            evidence=[Evidence(f.doc_id, f.page, f.bbox, f.name.replace("_", " "), kind="field", value=f.raw) for f in fs],
            fields=[f.key() for f in fs], docs=[fs[0].doc_id],
            repair={"expected": st["expected"], "actual": st["actual"]},
            verify_next="Ask the employer for the EPF passbook entry (UAN) for this month."))

    for d in docs.values():
        for h in d.structure.get("healed", []):
            rows = d.tables.get("transactions", [])
            out.append(Finding(
                id=new_id(), check="ocr_self_heal", family="logical", sensor="table_parser",
                title=f"OCR re-read corrected a statement cell: '{h['first_read']}' -> '{h['second_read']}'",
                detail=("The first OCR read broke the running balance; an independent second read of the same pixels "
                        "(crop only, digits whitelist, blind to the expected value) produced a value that makes this row "
                        "and the next row balance. Both reads are kept here so a human can check the pixels."),
                tier=Tier.OBSERVATION, confidence=round(float(h["conf"]), 2),
                evidence=[Evidence(d.doc_id, 0, (0, 0, d.pages[0].width, 40), f"row {h['row']} {h['field']}")],
                docs=[d.doc_id]))
        if d.doc_type == "bank_statement":
            from ..forensics.table_parser import behavioral_checks
            rows = d.tables.get("transactions", [])
            simple = [{"kind": "txn" if r.get("date") and not r.get("opening") else "opening",
                       "date": {"iso": r["date"].value} if r.get("date") else None,
                       "description": r["description"],
                       **{c: ({"value": r[c].value} if r.get(c) else None) for c in ("debit", "credit", "balance")}}
                      for r in rows]
            for b in behavioral_checks(simple):
                ev = [Evidence(d.doc_id, rows[i]["page"], rows[i]["bbox"], rows[i]["description"][:40]) for i in b["rows"]
                      if i < len(rows)]
                out.append(Finding(
                    id=new_id(), check=b["check"], family="pattern", sensor="behavioral", title=b["title"],
                    detail=b["detail"], tier=Tier.OBSERVATION, confidence=0.5, localized=bool(ev),
                    evidence=ev or [Evidence(d.doc_id, 0, (0, 0, d.pages[0].width, 40), "statement")], docs=[d.doc_id],
                    repair={"tier_hint": b["tier_hint"]}))

    out += income_triangulation(docs, rules, fields, vals, out, new_id)
    out += format_checks(docs, new_id)
    out += missing_fields(docs, new_id)
    out += statement_verifiability(docs, new_id)
    return out, ctx


def income_triangulation(docs, rules, fields, vals, findings, new_id) -> list:
    """Competing hypotheses for monthly income, with witness impeachment.

    The repair solver prefers the fewest changes, so a coordinated forgery (payslip, statement
    and application all inflated together) can make it blame the one honest document. Here every
    independent witness to monthly income is listed; a document that contradicts itself (a failed
    statutory or arithmetic rule) is impeached and counts less. If no hypothesis is clearly better
    supported, SAKSHI says so instead of picking one."""
    W = []
    slips = [d for d in docs.values() if d.doc_type == "salary_slip"]
    impeached = {st["fields"][0].split(".")[0] for st in rules.statutory if not st["ok"]}
    for inv in rules.linear:
        if inv.check == "arithmetic_break" and all(k in vals for k in inv.coef) and inv.violated(vals):
            impeached.add(next(iter(inv.coef)).split(".")[0])
    for s in slips:
        if "net_pay" in s.fields:
            f = s.fields["net_pay"]
            W.append({"ref": f.key(), "value": f.value, "who": f"Net Pay on {s.filename}", "weight": 2.0})
            for st in rules.statutory:
                if st["id"] == f"{s.doc_id}.S1" and not st["ok"]:
                    basic = fields[st["fields"][0]]
                    implied_basic = st["actual"] / 0.12
                    g = s.fields.get("gross")
                    td = s.fields.get("total_deductions")
                    if g and td:
                        v = round(g.value - basic.value + implied_basic - td.value, 2)
                        W.append({"ref": st["fields"][1], "value": v, "who": f"Net pay implied by the PF actually deducted on {s.filename}",
                                  "weight": 2.0, "confession": True})
        month = s.structure.get("pay_month")
        for inv in rules.linear:
            if inv.id.startswith("X1.") and s.fields.get("net_pay") and s.fields["net_pay"].key() in inv.coef:
                for k in inv.coef:
                    if k != s.fields["net_pay"].key():
                        W.append({"ref": k, "value": vals[k], "who": f"Salary credit for the pay month in {docs[fields[k].doc_id].filename}",
                                  "weight": 2.0})
        for st in docs.values():
            if st.doc_type != "bank_statement":
                continue
            for r in st.tables.get("transactions", []):
                if r.get("credit") and "salary" in r["description"].lower() and r.get("date") and month \
                        and not r["date"].value.startswith(month):
                    W.append({"ref": r["credit"].key(), "value": r["credit"].value,
                              "who": f"Salary credit of {r['date'].raw} (another month) in {st.filename}", "weight": 1.0})
    for d in docs.values():
        if d.doc_type == "employment_letter" and "letter_salary" in d.fields and d.structure.get("salary_basis") == "net":
            f = d.fields["letter_salary"]
            W.append({"ref": f.key(), "value": f.value, "who": f"Salary stated in {d.filename}", "weight": 1.0 if d.witness <= 1 else 2.0})
        if d.doc_type == "application_form" and "declared_income" in d.fields:
            f = d.fields["declared_income"]
            W.append({"ref": f.key(), "value": f.value, "who": f"Declared income on {d.filename} (claim)", "weight": 0.6})
    for d in docs.values():
        for pk in d.structure.get("peeled", []):
            if pk["ref"] in fields and fields[pk["ref"]].name in ("net_pay", "letter_salary", "declared_income"):
                W.append({"ref": pk["ref"], "value": pk["value"], "weight": 2.0,
                          "who": f"Value printed on the scanned paper underneath the PDF overlay in {d.filename}",
                          "raw": fmt(pk["value"]), "confession": True})
    for w in W:
        w["doc"] = fields[w["ref"]].doc_id if w["ref"] in fields else w["ref"].split(".")[0]
        # a self-contradicting document's printed value is impeached; the part of it that exposes the contradiction
        # (PF actually deducted, the scan under an overlay) is its confession and keeps full weight
        if w["doc"] in impeached and not w.get("confession"):
            w["weight"] = round(w["weight"] * 0.5, 2)
            w["who"] += " [impeached: this document contradicts itself]"
            w["impeached"] = True
    clusters = {}
    for w in W:
        key = next((k for k in clusters if abs(k - w["value"]) <= 1.0), w["value"])
        clusters.setdefault(key, []).append(w)
    if len(clusters) < 2 or len(W) < 3:
        return []

    def support(c):
        # one physical document can add at most 2.0 to one value, however many months it repeats it
        # (a 3-month forged statement must not outvote an honest letter on its own)
        per = {}
        for x in c:
            per[x["doc"]] = per.get(x["doc"], 0.0) + x["weight"]
        return round(sum(min(2.0, v) for v in per.values()), 2)

    ranked = sorted(clusters.items(), key=lambda kv: -support(kv[1]))
    (v1, c1), (v2, c2) = ranked[0], ranked[1]
    w1, w2 = support(c1), support(c2)
    # a value carried by a self-contradicting document can never win outright: SAKSHI refuses to pick it
    decisive = w1 >= 1.5 * w2 and not any(x.get("impeached") for x in c1)
    # salary that only differs in OTHER months (increment, loss-of-pay, variable pay) is normal, not a conflict
    if decisive and all("another month" in x["who"] for x in c2):
        return [Finding(
            id=new_id(), check="salary_variation", family="pattern", sensor="triangulation",
            title=f"Salary credits differ between months ({fmt(v1)} in the pay month, {fmt(v2)} in another month)",
            detail="Every same-period witness agrees on " + fmt(v1) + ". Salary credits in other months differ, which is "
                   "common after an increment, loss-of-pay days or variable pay. Recorded, not flagged.",
            confidence=0.5, localized=True,
            evidence=[Evidence(fields[x["ref"]].doc_id, fields[x["ref"]].page, fields[x["ref"]].bbox, x["who"], kind="field",
                               value=fields[x["ref"]].raw) for x in c2 if x["ref"] in fields][:4],
            fields=[x["ref"] for x in c2], docs=sorted({x["doc"] for x in c2}))]
    lines = "; ".join(f"{fmt(v)} <- " + ", ".join(f"{x['who']} ({x['weight']})" for x in c) for v, c in ranked)
    # a repair that blamed a member of a competitive cluster is contested
    contested = []
    for f in findings:
        if f.sensor == "repair_solver" and f.repair.get("proposed") is not None and f.fields:
            k = f.fields[0]
            for v, c in ranked:
                if any(x["ref"] == k for x in c) and not decisive:
                    f.repair["contested"] = True
                    contested.append(f.id)
    refs = [x["ref"] for x in (c2 if decisive else c1 + c2)]
    return [Finding(
        id=new_id(), check="income_triangulation", family="cross_document", sensor="triangulation",
        title=(f"Independent witnesses disagree on monthly income: {fmt(v1)} vs {fmt(v2)}"
               + ("" if decisive else ", and neither is clearly better supported")),
        detail=(f"Witnesses (weight in brackets): {lines}. Support {w1:.1f} vs {w2:.1f}. "
                + (f"The better-supported value is {fmt(v1)}." if decisive else
                   ("The larger group includes a document that contradicts itself, so SAKSHI does not let it win. "
                    if w1 >= 1.5 * w2 else "Because the support is close, SAKSHI does not pick a side. ")
                   + "A coordinated forgery can make several documents agree with each other. ")
                + (f" The cheapest single-value repair ({', '.join(contested)}) is therefore marked contested." if contested else "")),
        confidence=0.8, localized=True,
        evidence=[Evidence(fields[x["ref"]].doc_id, fields[x["ref"]].page, fields[x["ref"]].bbox, x["who"], kind="field",
                           value=x.get("raw", fields[x["ref"]].raw)) for v, c in ranked for x in c if x["ref"] in fields][:8],
        fields=refs, docs=sorted({fields[r].doc_id for r in refs if r in fields}),
        repair={"clusters": {fmt(v): [x["who"] for x in c] for v, c in ranked}, "decisive": decisive,
                "families": ["cross_document", "statutory"] if any("PF" in x["who"] for x in W) else ["cross_document"]},
        verify_next="Confirm the salary directly with the employer's HR or from Form 26AS / AIS (TDS records).")]


PAN_RE = re.compile(r"^[A-Z]{5}\d{4}[A-Z]$")
IFSC_RE = re.compile(r"^[A-Z]{4}0[A-Z0-9]{6}$")


def format_checks(docs: dict, new_id) -> list[Finding]:
    out = []
    for d in docs.values():
        for name, f in d.fields.items():
            if name == "pan":
                v = f.value
                problems = []
                if not PAN_RE.match(v):
                    problems.append("does not match the AAAAA9999A pattern")
                else:
                    if v[3] != "P":
                        problems.append(f"4th character '{v[3]}' marks a non-individual holder (P = person)")
                    holder = next((x.value for x in d.fields.values() if x.kind == "name" and "name" in x.name), None)
                    if holder:
                        sur = holder.split()[-1]
                        if v[4] != sur[0]:
                            problems.append(f"5th character '{v[4]}' should be the surname initial '{sur[0]}'")
                if problems:
                    out.append(Finding(
                        id=new_id(), check="format_violation", family="identity", sensor="format",
                        title=f"PAN '{f.raw}' on {d.filename}: " + "; ".join(problems),
                        detail="Indian PAN structure: 5 letters, 4 digits, 1 letter; the 4th letter is the holder type "
                               "(P for an individual) and the 5th is the first letter of the surname.",
                        confidence=0.6 if f.conf < 0.6 else 0.8, localized=True,
                        evidence=[Evidence(d.doc_id, f.page, f.bbox, "PAN", kind="field", value=f.raw)],
                        fields=[f.key()], docs=[d.doc_id]))
            if name == "ifsc" and not IFSC_RE.match(f.value):
                fixed = f.value
                out.append(Finding(
                    id=new_id(), check="format_violation", family="identity", sensor="format",
                    title=f"IFSC '{f.raw}' on {d.filename} is not a valid IFSC pattern",
                    detail="IFSC is 4 letters, a zero, then 6 letters or digits (11 characters). "
                           f"Read with OCR confidence {f.conf:.2f}.",
                    confidence=0.4 if f.conf < 0.6 else 0.75, localized=True,
                    evidence=[Evidence(d.doc_id, f.page, f.bbox, "IFSC", kind="field", value=f.raw)],
                    fields=[f.key()], docs=[d.doc_id]))
        if d.doc_type == "identity_card":
            vt, iss = d.fields.get("valid_till"), d.fields.get("issued")
            app_date = next((x.fields["application_date"].value for x in docs.values()
                             if "application_date" in x.fields), None)
            ref = app_date or date.today().isoformat()
            if vt and vt.value < ref:
                out.append(Finding(id=new_id(), check="date_plausibility", family="identity", sensor="format",
                                   title=f"Identity card expired on {vt.raw}", detail=f"Reference date {ref}.",
                                   confidence=0.8, localized=True,
                                   evidence=[Evidence(d.doc_id, vt.page, vt.bbox, "valid till", kind="field", value=vt.raw)],
                                   fields=[vt.key()], docs=[d.doc_id]))
            if iss and iss.value > ref:
                out.append(Finding(id=new_id(), check="date_plausibility", family="identity", sensor="format",
                                   title=f"Identity card issued in the future ({iss.raw})", detail=f"Reference date {ref}.",
                                   confidence=0.8, localized=True,
                                   evidence=[Evidence(d.doc_id, iss.page, iss.bbox, "issued", kind="field", value=iss.raw)],
                                   fields=[iss.key()], docs=[d.doc_id]))
        if d.doc_type == "bank_statement":
            rows = [r for r in d.tables.get("transactions", []) if r.get("date")]
            per = d.structure.get("period")
            for a, b in zip(rows, rows[1:]):
                if b["date"].value < a["date"].value:
                    out.append(Finding(id=new_id(), check="date_plausibility", family="logical", sensor="format",
                                       title=f"Transactions out of order: {b['date'].raw} after {a['date'].raw}",
                                       detail="Statement rows are printed in date order.", confidence=0.7, localized=True,
                                       evidence=[Evidence(d.doc_id, b["page"], b["bbox"], "row out of order")],
                                       fields=[b["date"].key()], docs=[d.doc_id]))
            if per:
                for r in rows:
                    if not (per[0] <= r["date"].value <= per[1]):
                        out.append(Finding(id=new_id(), check="date_plausibility", family="logical", sensor="format",
                                           title=f"Transaction dated {r['date'].raw} lies outside the statement period",
                                           detail=f"Period {per[0]} to {per[1]}.", confidence=0.7, localized=True,
                                           evidence=[Evidence(d.doc_id, r["page"], r["bbox"], "out-of-period row")],
                                           fields=[r["date"].key()], docs=[d.doc_id]))
    return out


def statement_verifiability(docs: dict, new_id) -> list[Finding]:
    """Never go silent: a statement whose arithmetic SAKSHI cannot verify says so, with what to do next."""
    out = []
    for d in docs.values():
        if d.doc_type != "bank_statement":
            continue
        st = d.structure
        fit = st.get("confident_fit") if st.get("confident_transitions", 0) >= 5 else st.get("transition_fit")
        if fit is not None and fit < 0.8:
            out.append(Finding(
                id=new_id(), check="statement_unverified", family="logical", sensor="structure",
                title=f"{d.filename}: the running balance holds on only {fit:.0%} of rows, so this statement's arithmetic "
                      "could not be verified",
                detail=("Either the layout is unfamiliar to SAKSHI or many rows are wrong. Statement arithmetic findings on "
                        "this document cannot escalate, but pixel and file-structure checks still run. Obtain the statement "
                        "directly from the bank (net banking download or Account Aggregator) before relying on it."),
                confidence=0.5, evidence=[Evidence(d.doc_id, 0, (0, 0, d.pages[0].width, 60), "document")], docs=[d.doc_id],
                verify_next="Fetch the statement from the bank through an independent channel."))
    return out


def missing_fields(docs: dict, new_id) -> list[Finding]:
    out = []
    for d in docs.values():
        hs = [w.bbox[3] - w.bbox[1] for P in d.pages for w in P.words if w.conf >= 0.5 and len(w.text) >= 3]
        small = d.modality != "digital_pdf" and bool(hs) and float(np.median(hs)) < 18
        for m in d.structure.get("missing", []):
            if d.structure.get("redacted"):
                out.append(Finding(id=new_id(), check="unreadable_field", family="logical", sensor="structure",
                                   title=f"{d.filename}: '{m.replace('_', ' ')}' not found; part of this document is redacted",
                                   detail="The submitter masked part of this document, so a missing field may simply be "
                                          "under the redaction. Ask for the unredacted copy if it matters.",
                                   confidence=0.4, evidence=[Evidence(d.doc_id, 0, (0, 0, d.pages[0].width, 60), "document")],
                                   docs=[d.doc_id]))
                continue
            if small:
                # a field that cannot be READ is not a field that is ABSENT (safe failure on forwarded photos)
                out.append(Finding(id=new_id(), check="unreadable_field", family="logical", sensor="structure",
                                   title=f"{d.filename}: '{m.replace('_', ' ')}' could not be read (image resolution too low)",
                                   detail=f"Text on this image is about {float(np.median(hs)):.0f}px tall, below what OCR reads "
                                          "reliably. Absence cannot be concluded; ask for the original file or a clearer scan.",
                                   confidence=0.4, evidence=[Evidence(d.doc_id, 0, (0, 0, d.pages[0].width, 60), "document")],
                                   docs=[d.doc_id]))
                continue
            out.append(Finding(id=new_id(), check="missing_field", family="logical", sensor="structure",
                               title=f"{d.filename}: expected field '{m.replace('_', ' ')}' not found",
                               detail="The field is required for this document type but could not be located. Either it "
                                      "is absent or extraction failed; both need a human look.",
                               confidence=0.5, evidence=[Evidence(d.doc_id, 0, (0, 0, d.pages[0].width, 60), "document")],
                               docs=[d.doc_id]))
        for dup in d.structure.get("duplicates", []):
            out.append(Finding(id=new_id(), check="duplicate_field", family="logical", sensor="structure",
                               title=f"{d.filename}: field '{dup.replace('_', ' ')}' appears more than once",
                               detail="Only the first occurrence was used.", confidence=0.4,
                               evidence=[Evidence(d.doc_id, 0, (0, 0, d.pages[0].width, 60), "document")],
                               docs=[d.doc_id]))
    return out
