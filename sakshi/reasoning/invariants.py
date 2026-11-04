"""'Document as a program': the invariant library.

Every document type implies arithmetic and logical rules. Cross-document rules
connect them into one system. Linear rules (sum(c_i * x_i) = b) feed the
counterfactual repair solver; equality rules over text/dates/ids feed the
odd-one-out diagnosis; format/plausibility rules are plain checks.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date

from ..models import Document

MONTH_WORDS = r"\b(jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\b"
FIXED = r"\b(emi|loan|ln\d*|nach|ecs|rent|sip|premium|insurance|salary|payroll)\b"


@dataclass
class Linear:
    id: str
    text: str                    # human description
    coef: dict                   # field ref -> coefficient
    b: float = 0.0
    scope: str = "intra"         # "intra" | "cross"
    check: str = "arithmetic_break"
    soft: bool = False           # legitimately violated sometimes (e.g. salary revision)
    tol: float = 0.51

    def residual(self, vals: dict) -> float:
        return sum(c * vals[k] for k, c in self.coef.items()) - self.b

    def violated(self, vals: dict) -> bool:
        return abs(self.residual(vals)) > self.tol


@dataclass
class Equality:
    id: str
    text: str
    attr: str                    # canonical attribute, e.g. "dob"
    refs: list                   # field refs that should agree
    kind: str                    # "name" | "date" | "id" | "text"
    check: str = "cross_doc_mismatch"


@dataclass
class Rules:
    linear: list = field(default_factory=list)
    equality: list = field(default_factory=list)
    expectations: list = field(default_factory=list)  # (description, found: bool, evidence)
    statutory: list = field(default_factory=list)     # soft statutory payroll checks


def _by_type(docs: dict, t: str) -> list[Document]:
    return [d for d in docs.values() if d.doc_type == t]


def _ref(d: Document, name: str):
    f = d.fields.get(name)
    return f.key() if f else None


def build(docs: dict, fields: dict) -> Rules:
    R = Rules()
    slips, stmts = _by_type(docs, "salary_slip"), _by_type(docs, "bank_statement")
    apps, ids, letters = _by_type(docs, "application_form"), _by_type(docs, "identity_card"), _by_type(docs, "employment_letter")

    # ---------------- salary slip arithmetic
    for s in slips:
        earn = [f.key() for f in s.tables.get("earnings", [])]
        ded = [f.key() for f in s.tables.get("deductions", [])]
        g, td, n, nw = (_ref(s, x) for x in ("gross", "total_deductions", "net_pay", "net_pay_words"))
        if earn and g:
            R.linear.append(Linear(f"{s.doc_id}.P1", f"{s.filename}: earnings components add up to Gross Earnings",
                                   {**{k: 1 for k in earn}, g: -1}))
        if ded and td:
            R.linear.append(Linear(f"{s.doc_id}.P2", f"{s.filename}: deduction components add up to Total Deductions",
                                   {**{k: 1 for k in ded}, td: -1}))
        if g and td and n:
            R.linear.append(Linear(f"{s.doc_id}.P3", f"{s.filename}: Gross Earnings - Total Deductions = Net Pay",
                                   {g: 1, td: -1, n: -1}))
        if n and nw:
            R.linear.append(Linear(f"{s.doc_id}.P4", f"{s.filename}: Net Pay in figures equals Net Pay in words",
                                   {n: 1, nw: -1}, check="amount_words_mismatch"))

    # ---------------- bank statement arithmetic
    for st in stmts:
        rows = st.tables.get("transactions", [])
        prev = None
        pending = []  # rows with readable amounts but no printed balance: bridged into the next check
        for i, r in enumerate(rows):
            bal = r.get("balance")
            if r.get("unreadable"):
                prev, pending = None, []  # an amount could not be read: the chain restarts honestly
                continue
            if not bal:
                if prev is not None:
                    pending.append(r)
                continue
            if prev is not None:
                coef = {prev.key(): 1, bal.key(): -1}
                for x in pending + [r]:
                    if x.get("debit"):
                        coef[x["debit"].key()] = -1
                    if x.get("credit"):
                        coef[x["credit"].key()] = 1
                d = r["date"].value if r.get("date") else "?"
                span = f" (bridging {len(pending)} row(s) without a printed balance)" if pending else ""
                R.linear.append(Linear(f"{st.doc_id}.B1.row{i}", f"{st.filename}: running balance on {d} "
                                       f"(previous balance - debit + credit = balance){span}", coef, check="balance_chain_break"))
            prev, pending = bal, []
        bals = [r["balance"] for r in rows if r.get("balance")]
        drs = [r["debit"].key() for r in rows if r.get("debit")]
        crs = [r["credit"].key() for r in rows if r.get("credit")]
        so, sd, sc, scl = (_ref(st, x) for x in ("summary_opening", "summary_debits", "summary_credits", "summary_closing"))
        if so and bals:
            R.linear.append(Linear(f"{st.doc_id}.B2.open", f"{st.filename}: summary opening balance equals first balance",
                                   {so: 1, bals[0].key(): -1}, check="statement_totals_mismatch"))
        if sd and drs:
            R.linear.append(Linear(f"{st.doc_id}.B2.dr", f"{st.filename}: Total Debits equals the sum of debit rows",
                                   {**{k: 1 for k in drs}, sd: -1}, check="statement_totals_mismatch"))
        if sc and crs:
            R.linear.append(Linear(f"{st.doc_id}.B2.cr", f"{st.filename}: Total Credits equals the sum of credit rows",
                                   {**{k: 1 for k in crs}, sc: -1}, check="statement_totals_mismatch"))
        if scl and bals:
            R.linear.append(Linear(f"{st.doc_id}.B2.close", f"{st.filename}: summary closing balance equals last balance",
                                   {scl: 1, bals[-1].key(): -1}, check="statement_totals_mismatch"))
        # recurring transactions with the same narration should carry the same amount
        groups = {}
        for i, r in enumerate(rows):
            for col in ("debit", "credit"):
                if r.get(col):
                    key = re.sub(MONTH_WORDS, "", r["description"].lower())
                    key = re.sub(r"[^a-z0-9]+", " ", key)
                    # drop cheque/reference numbers and OCR specks so the same obligation groups together
                    key = " ".join(t for t in key.split() if not t.isdigit() and len(t) > 1)
                    # only fixed obligations recur at a fixed amount (utility bills, shopping do not)
                    if len(key) >= 6 and re.search(FIXED, key):
                        groups.setdefault((col, key), []).append((i, r))
        st.structure["recurring"] = {f"{c}:{k}": [i for i, _ in v] for (c, k), v in groups.items() if len(v) > 1}
        for (col, key), occ in groups.items():
            if len(occ) < 2:
                continue
            for (i, a), (j, b) in zip(occ, occ[1:]):
                R.linear.append(Linear(
                    f"{st.doc_id}.B3.{i}.{j}", f"{st.filename}: recurring '{a['description']}' carries the same amount "
                    f"on {a['date'].value if a.get('date') else '?'} and {b['date'].value if b.get('date') else '?'}",
                    {a[col].key(): 1, b[col].key(): -1}, check="recurring_amount_mismatch",
                    soft="salary" in key))

        # a fixed obligation seen in one full month but absent in a later full month of the period
        per = st.structure.get("period")
        if per:
            months = sorted({r["date"].value[:7] for r in rows if r.get("date")})
            full = [m for m in months if per[0] <= m + "-01" and (m + "-28") <= per[1]]
            for (col, key), occ in groups.items():
                if col != "debit" or "salary" in key:
                    continue
                seen = {r["date"].value[:7] for _, r in occ}
                same = [r for _, r in occ]
                if not seen:
                    continue
                for m in full:
                    if m > min(seen) and m not in seen:
                        R.expectations.append({"text": f"Recurring '{same[0]['description'][:40]}' "
                                               f"({same[0]['debit'].raw}) seen in {min(seen)} but missing in {m} in "
                                               f"{st.filename}", "found": False, "doc": st.doc_id, "kind": "recurring",
                                               "amount": same[0]["debit"].value, "month": m,
                                               "ref": same[0]["debit"].key()})
            # single fixed obligations: one occurrence, so no recurring group yet
            for i, r in enumerate(rows):
                if r.get("debit") and re.search(FIXED, r["description"].lower()) and "salary" not in r["description"].lower():
                    key = " ".join(t for t in re.sub(r"[^a-z0-9]+", " ", re.sub(MONTH_WORDS, "", r["description"].lower())).split()
                                   if not t.isdigit() and len(t) > 1)
                    if ("debit", key) in groups and len(groups[("debit", key)]) > 1:
                        continue
                    m = r["date"].value[:7] if r.get("date") else None
                    later = [x for x in full if m and x > m]
                    if later and re.search(r"\b(emi|loan|ln\d*|nach|ecs|sip|premium)\b", key):
                        R.expectations.append({"text": f"Recurring '{r['description'][:40]}' ({r['debit'].raw}) seen in "
                                               f"{m} but missing in {later[0]} in {st.filename}", "found": False,
                                               "doc": st.doc_id, "kind": "recurring", "amount": r["debit"].value,
                                               "month": later[0], "ref": r["debit"].key()})

    # ---------------- statutory payroll rules (soft checks, Indian payroll conventions)
    for s in slips:
        earn = {f.name: f for f in s.tables.get("earnings", [])}
        ded = {f.name: f for f in s.tables.get("deductions", [])}
        basic = next((f for n, f in earn.items() if n.startswith("basic")), None)
        da = next((f for n, f in earn.items() if n in ("dearness_allowance", "da")), None)
        pf = next((f for n, f in ded.items() if "provident" in n or n in ("pf", "epf")), None)
        if basic and pf:
            wage = basic.value + (da.value if da else 0.0)
            # Only a PF BELOW 12% of the printed basic is a contradiction (the direction an inflated basic leaves).
            # PF above 12% is legitimate: voluntary PF (VPF) or a PF wage that includes allowances (v1.0, Argon review).
            ok = pf.value >= 0.12 * wage - 1.0 or abs(pf.value - 1800.0) <= 1.0 or abs(pf.value - 3600.0) <= 1.0
            R.statutory.append({"id": f"{s.doc_id}.S1", "ok": ok, "fields": [basic.key(), pf.key()],
                                "text": f"{s.filename}: employee PF is at least 12% of basic (+DA) = {0.12 * wage:,.2f}, "
                                        f"or the statutory 1,800 cap (VPF above 12% is allowed); slip shows {pf.raw}",
                                "expected": [round(0.12 * wage, 2), 1800.0], "actual": pf.value})
        pt = next((f for n, f in ded.items() if "professional" in n), None)
        g = s.fields.get("gross")
        addr = " ".join(w.text for w in s.pages[0].words[:60]).lower()
        month = s.structure.get("pay_month", "")
        if pt and g and ("bengaluru" in addr or "karnataka" in addr or "bangalore" in addr) and g.value > 25000:
            exp = 300.0 if month.endswith("-02") else 200.0
            R.statutory.append({"id": f"{s.doc_id}.S2", "ok": abs(pt.value - exp) <= 0.5, "fields": [pt.key()],
                                "text": f"{s.filename}: Karnataka professional tax is {exp:,.0f} for this month above "
                                        f"25,000 gross; slip shows {pt.raw}", "expected": [exp], "actual": pt.value})

    # ---------------- cross-document numeric links
    for s in slips:
        n = _ref(s, "net_pay")
        if not n:
            continue
        pay = s.fields.get("pay_date")
        month = s.structure.get("pay_month")
        for st in stmts:
            per = st.structure.get("period")
            emp = (s.fields["employer"].value.split()[0] if "employer" in s.fields else "").lower()
            cands = []
            for i, r in enumerate(st.tables.get("transactions", [])):
                if not r.get("credit") or not r.get("date"):
                    continue
                d = r["date"].value
                desc = r["description"].lower()
                salaryish = "salary" in desc or "payroll" in desc or (emp and emp in desc)
                in_window = (month and d.startswith(month)) or (pay and _days(pay.value, d) is not None
                                                                 and 0 <= _days(pay.value, d) <= 7)
                if salaryish and in_window:
                    cands.append(r)
            if cands:
                r = cands[-1]
                R.linear.append(Linear(f"X1.{s.doc_id}.{st.doc_id}", f"Net Pay on {s.filename} equals the salary "
                                       f"credit on {r['date'].value} in {st.filename}", {n: 1, r["credit"].key(): -1},
                                       scope="cross", check="cross_doc_value_mismatch"))
                R.expectations.append({"text": f"Expected a salary credit near {pay.value if pay else month} in "
                                       f"{st.filename}", "found": True, "ref": r["credit"].key()})
            elif per and pay and per[0] <= pay.value <= per[1]:
                R.expectations.append({"text": f"Expected a salary credit near {pay.value} in {st.filename} "
                                       "(statement period covers the pay date)", "found": False, "doc": st.doc_id})
        for a in apps:
            di = _ref(a, "declared_income")
            if di:
                R.linear.append(Linear(f"X2.{a.doc_id}.{s.doc_id}", f"Declared net monthly income on {a.filename} "
                                       f"equals Net Pay on {s.filename}", {di: 1, n: -1}, scope="cross",
                                       check="claim_vs_evidence"))
        for l in letters:
            ls = _ref(l, "letter_salary")
            if ls:
                basis = l.structure.get("salary_basis", "net")
                tgt = _ref(s, "gross") if basis == "gross" else n
                if tgt:
                    R.linear.append(Linear(f"X3.{l.doc_id}.{s.doc_id}", f"Salary stated in {l.filename} ({basis}) "
                                           f"equals the {basis} pay on {s.filename}", {ls: 1, tgt: -1}, scope="cross",
                                           check="cross_doc_value_mismatch"))
    for a in apps:
        de = _ref(a, "declared_emi")
        if not de:
            continue
        for st in stmts:
            rows = st.tables.get("transactions", [])
            by_month = {}
            for r in rows:
                if r.get("debit") and r.get("date") and re.search(r"\bemi\b|\bloan\b|\bln\d+|\bnach\b|\becs\b",
                                                                  r["description"], re.I):
                    by_month.setdefault(r["date"].value[:7], []).append(r)
            for m, rs in sorted(by_month.items()):
                R.linear.append(Linear(f"X4.{a.doc_id}.{st.doc_id}.{m}", f"Declared monthly EMIs on {a.filename} "
                                       f"equal the EMI debits for {m} in {st.filename}",
                                       {de: 1, **{r['debit'].key(): -1 for r in rs}}, scope="cross",
                                       check="claim_vs_evidence"))

    # ---------------- equality groups (who is this person, where do they work)
    def group(attr, kind, pairs, text):
        refs = [d.fields[n].key() for d, n in pairs if n in d.fields]
        if len(refs) >= 2:
            R.equality.append(Equality(f"E.{attr}", text, attr, refs, kind))

    group("name", "name", [(d, "applicant_name") for d in apps] + [(d, "employee_name") for d in slips + letters]
          + [(d, "name") for d in ids] + [(d, "account_holder") for d in stmts], "Applicant name is the same everywhere")
    group("dob", "date", [(d, "dob") for d in apps + ids], "Date of birth is the same everywhere")
    group("pan", "id", [(d, "pan") for d in apps + slips], "PAN is the same everywhere")
    group("account_no", "id", [(d, "account_no") for d in apps + slips + stmts], "Salary account number is the same everywhere")
    group("ifsc", "id", [(d, "ifsc") for d in apps + stmts], "IFSC is the same everywhere")
    group("employer", "name", [(d, "employer") for d in apps + slips + letters], "Employer is the same everywhere")
    group("designation", "text", [(d, "designation") for d in apps + slips + letters], "Designation is the same everywhere")
    group("date_of_joining", "date", [(d, "date_of_joining") for d in apps + slips + letters], "Date of joining is the same everywhere")
    group("employee_id", "id", [(d, "employee_id") for d in slips + letters], "Employee ID is the same everywhere")
    group("address", "text", [(d, "address") for d in apps + ids], "Residential address is the same everywhere")
    return R


def _days(a: str, b: str):
    try:
        return (date.fromisoformat(b) - date.fromisoformat(a)).days
    except Exception:
        return None
