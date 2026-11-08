"""Issuer witness (L4): Account Aggregator data for a deposit account, reconciled against the uploaded statement.

A regenerated bank statement with consistent arithmetic cannot be caught from the documents alone: nothing inside
them contradicts it. The bank's own record can. In India that record reaches a lender through the Account
Aggregator (AA) framework as FI data in the ReBIT deposit schema (Profile/Holders, Summary, Transactions).

SAKSHI is not an FIU and does not fetch anything from the AA network. It reads FI data the lender already holds,
supplied as a file next to the documents (XML or its JSON rendering), treats it as an L4 witness and reconciles
every row of the uploaded statement against it:

* pass 1: same direction, same amount, same date (transaction or value date);
* pass 2: the same, one day apart (posting vs value date);
* pass 3: one statement credit equal to two or three bank credits on the same day (a split salary credit);
* pass 4: a statement row and a bank transaction on the same date and direction whose amounts differ.

What is left over is reported: rows the bank has no record of, bank transactions missing from the statement,
amounts that differ, and balances that drift from the bank's. Every finding is boxed on the uploaded statement.
Only transactions inside both the bank data's period and the statement's period are compared; anything outside
is reported as not covered. If the bank data belongs to a different account, no row is compared at all.
"""
from __future__ import annotations

import itertools
import json
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path

from .models import BenignTest, Evidence, Finding
from .reasoning.repair import name_key

AA_SUFFIXES = {".xml", ".json"}


class NotIssuerData(ValueError):
    pass


@dataclass
class BankTxn:
    txn_id: str
    direction: str              # "debit" | "credit"
    amount: float
    balance: float | None
    dates: tuple                # (transaction date, value date) as date objects, deduplicated
    narration: str
    mode: str = ""


@dataclass
class IssuerAccount:
    source: str
    fmt: str                    # "rebit-xml" | "rebit-json"
    masked_account: str
    holders: list
    pans: list
    ifsc: str
    start: date | None
    end: date | None
    current_balance: float | None
    txns: list = field(default_factory=list)

    def summary(self) -> dict:
        return {"source": self.source, "format": self.fmt, "masked_account": self.masked_account,
                "holders": self.holders, "ifsc": self.ifsc,
                "period": [self.start.isoformat() if self.start else None, self.end.isoformat() if self.end else None],
                "transactions": len(self.txns), "witness_level": 4,
                "note": "FI data supplied as a file; SAKSHI is not an FIU and did not fetch it from the AA network."}


# ---------------------------------------------------------------- parsing

def _d(v) -> date | None:
    if not v:
        return None
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})", str(v).strip())
    return date(int(m[1]), int(m[2]), int(m[3])) if m else None


def _f(v) -> float | None:
    try:
        return round(float(str(v).replace(",", "")), 2)
    except (TypeError, ValueError):
        return None


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _from_tree(acc: dict, source: str, fmt: str) -> IssuerAccount:
    """acc: the Account element as nested dicts (attributes merged with children), XML or JSON alike."""
    def get(d, *names):
        for n in names:
            for k, v in (d or {}).items():
                if k.lower() == n.lower():
                    return v
        return None

    def as_list(v):
        return v if isinstance(v, list) else ([v] if v else [])

    if str(get(acc, "type") or "deposit").lower() != "deposit":
        raise NotIssuerData(f"{source}: account type {get(acc, 'type')!r}; only deposit accounts are supported")
    profile = get(acc, "Profile") or {}
    holders_el = get(profile, "Holders") or {}
    holders = as_list(get(holders_el, "Holder"))
    summ = get(acc, "Summary") or {}
    tx_el = get(acc, "Transactions") or {}
    txns = []
    for t in as_list(get(tx_el, "Transaction")):
        kind = str(get(t, "type") or "").upper()
        if kind not in ("DEBIT", "CREDIT"):
            continue  # OPENING / INTEREST markers etc. without a direction are not rows
        amt = _f(get(t, "amount"))
        if amt is None:
            continue
        dts = []
        for k in ("transactionTimestamp", "valueDate"):
            dv = _d(get(t, k))
            if dv and dv not in dts:
                dts.append(dv)
        if not dts:
            continue
        txns.append(BankTxn(str(get(t, "txnId") or len(txns)), kind.lower(), amt, _f(get(t, "currentBalance")),
                            tuple(dts), str(get(t, "narration") or ""), str(get(t, "mode") or "")))
    if not txns:
        raise NotIssuerData(f"{source}: no DEBIT or CREDIT transactions found")
    return IssuerAccount(
        source=source, fmt=fmt, masked_account=str(get(acc, "maskedAccNumber") or ""),
        holders=[str(get(h, "name") or "") for h in holders if get(h, "name")],
        pans=[str(get(h, "pan") or "").upper() for h in holders if get(h, "pan")],
        ifsc=str(get(summ, "ifscCode") or "").upper(), start=_d(get(tx_el, "startDate")), end=_d(get(tx_el, "endDate")),
        current_balance=_f(get(summ, "currentBalance")), txns=txns)


def _xml_to_dict(el) -> dict:
    d = {k: v for k, v in el.attrib.items()}
    for ch in el:
        name = _local(ch.tag)
        val = _xml_to_dict(ch)
        if name in d:
            d[name] = d[name] if isinstance(d[name], list) else [d[name]]
            d[name].append(val)
        else:
            d[name] = val
    return d


def _find_account(obj):
    """The Account object inside an FI payload, whatever envelope wraps it."""
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k.lower() == "account" and isinstance(v, dict) and any(x.lower() == "transactions" for x in v):
                return v
        if any(k.lower() == "transactions" for k in obj) and any(k.lower() in ("profile", "summary") for k in obj):
            return obj
        for v in obj.values():
            r = _find_account(v)
            if r is not None:
                return r
    elif isinstance(obj, list):
        for v in obj:
            r = _find_account(v)
            if r is not None:
                return r
    return None


def load(path: str | Path) -> IssuerAccount:
    p = Path(path)
    raw = p.read_bytes()
    if p.suffix.lower() == ".xml" or raw.lstrip()[:1] == b"<":
        try:
            root = ET.fromstring(raw)  # ElementTree does not resolve external entities
        except ET.ParseError as e:
            raise NotIssuerData(f"{p.name}: not readable XML ({e})") from None
        acc = root if _local(root.tag).lower() == "account" else next(
            (el for el in root.iter() if _local(el.tag).lower() == "account"), None)
        if acc is None:
            raise NotIssuerData(f"{p.name}: no Account element")
        return _from_tree(_xml_to_dict(acc), p.name, "rebit-xml")
    try:
        obj = json.loads(raw.decode("utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError) as e:
        raise NotIssuerData(f"{p.name}: not readable JSON ({e})") from None
    acc = _find_account(obj)
    if acc is None:
        raise NotIssuerData(f"{p.name}: no Account with Transactions")
    return _from_tree(acc, p.name, "rebit-json")


def is_issuer_file(path: str | Path) -> bool:
    return Path(path).suffix.lower() in AA_SUFFIXES


# ---------------------------------------------------------------- reconciliation

def _row_date(r) -> date | None:
    f = r.get("date")
    return _d(f.value) if f is not None else None


def _statement_rows(st) -> list[dict]:
    out = []
    for i, r in enumerate(st.tables.get("transactions", [])):
        if r.get("opening"):
            continue
        dt = _row_date(r)
        for col in ("debit", "credit"):
            f = r.get(col)
            if f is not None and f.value:
                out.append({"i": i, "row": r, "date": dt, "direction": col, "amount": round(float(f.value), 2),
                            "field": f, "balance": r.get("balance")})
                break
    return out


def _period(rows) -> tuple:
    ds = [x["date"] for x in rows if x["date"]]
    return (min(ds), max(ds)) if ds else (None, None)


def _last4(s: str) -> str:
    digits = re.sub(r"\D", "", s or "")
    return digits[-4:] if len(digits) >= 4 else ""


def _fmt(x: float) -> str:
    return f"{x:,.2f}"


def reconcile(acc: IssuerAccount, docs: dict, new_id) -> tuple[list[Finding], dict]:
    statements = [d for d in docs.values() if d.doc_type == "bank_statement"]
    report = {"issuer": acc.summary(), "statements": []}
    findings: list[Finding] = []
    if not statements:
        report["note"] = "no bank statement among the documents; issuer data recorded but not compared"
        return findings, report
    for st in statements:
        rep = {"doc_id": st.doc_id, "filename": st.filename}
        report["statements"].append(rep)
        acct = st.fields.get("account_no")
        st_last4, aa_last4 = _last4(acct.value if acct else ""), _last4(acc.masked_account)
        holder = st.fields.get("account_holder")
        same_holder = bool(holder) and any(name_key(str(holder.value)) == name_key(h) for h in acc.holders)
        page0 = st.pages[0] if st.pages else None
        whole = Evidence(st.doc_id, 0, (0, 0, page0.width, page0.height) if page0 else (0, 0, 10, 10),
                         "uploaded statement")
        if st_last4 and aa_last4 and st_last4 != aa_last4:
            rep["compared"] = False
            rep["reason"] = f"account ending {st_last4} on the statement, {aa_last4} in the bank data"
            findings.append(Finding(
                id=new_id(), check="issuer_account_mismatch", family="issuer", sensor="issuer",
                title=f"Bank data is for a different account: the statement shows an account ending {st_last4}, "
                      f"the Account Aggregator data an account ending {aa_last4}",
                detail="No row was compared. Either the wrong FI data was attached or the statement is not for the "
                       "account the applicant consented to share.",
                confidence=0.9, localized=bool(acct), evidence=[Evidence(st.doc_id, acct.page, acct.bbox,
                                                                         "account number on the statement", kind="field")]
                if acct else [whole], fields=[acct.key()] if acct else [], docs=[st.doc_id]))
            continue
        if not st_last4 or not aa_last4:
            rep["account_check"] = "account number not readable on one side; holder name used instead"
            if not same_holder:
                rep["compared"] = False
                rep["reason"] = "neither the account number nor the holder name could be matched to the bank data"
                continue
        rows = _statement_rows(st)
        s_start, s_end = _period(rows)
        lo = max(x for x in (acc.start, s_start) if x) if (acc.start or s_start) else None
        hi = min(x for x in (acc.end, s_end) if x) if (acc.end or s_end) else None
        inside = lambda dd: dd is not None and (lo is None or dd >= lo) and (hi is None or dd <= hi)  # noqa: E731
        S = [x for x in rows if inside(x["date"])]
        B = [t for t in acc.txns if any(inside(dd) for dd in t.dates)]
        rep.update(compared=True, period=[lo.isoformat() if lo else None, hi.isoformat() if hi else None],
                   statement_rows=len(rows), statement_rows_compared=len(S),
                   statement_rows_not_covered=len(rows) - len(S), bank_transactions_compared=len(B))
        unmatched_s, unmatched_b = list(range(len(S))), list(range(len(B)))
        pairs = []  # (s index, [b indices], how)

        def take(si, bis, how):
            pairs.append((si, bis, how))
            unmatched_s.remove(si)
            for b in bis:
                unmatched_b.remove(b)

        for tol, how in ((0, "same date"), (1, "one day apart")):
            for si in list(unmatched_s):
                s = S[si]
                cands = [bi for bi in unmatched_b if B[bi].direction == s["direction"]
                         and abs(B[bi].amount - s["amount"]) < 0.005
                         and any(abs((dd - s["date"]).days) <= tol for dd in B[bi].dates)]
                if cands:
                    take(si, [min(cands, key=lambda bi: min(abs((dd - s["date"]).days) for dd in B[bi].dates))], how)
        for si in list(unmatched_s):  # split credits: 2-3 bank credits on the same day sum to one statement credit
            s = S[si]
            if s["direction"] != "credit":
                continue
            same_day = [bi for bi in unmatched_b if B[bi].direction == "credit" and s["date"] in B[bi].dates]
            hit = next((c for k in (2, 3) for c in itertools.combinations(same_day, k)
                        if abs(sum(B[bi].amount for bi in c) - s["amount"]) < 0.005), None)
            if hit:
                take(si, list(hit), "split credit")
        altered = []
        for si in list(unmatched_s):  # same date and direction, different amount: an altered amount
            s = S[si]
            sd = [bi for bi in unmatched_b if B[bi].direction == s["direction"] and s["date"] in B[bi].dates]
            others = [sj for sj in unmatched_s if S[sj]["direction"] == s["direction"] and S[sj]["date"] == s["date"]]
            if len(sd) == 1 and len(others) == 1:
                altered.append((si, sd[0]))
                unmatched_s.remove(si)
                unmatched_b.remove(sd[0])
        rep.update(matched=len(pairs), amounts_differ=len(altered), only_on_statement=len(unmatched_s),
                   only_in_bank_data=len(unmatched_b))

        def ev(s, note):
            r = s["row"]
            return [Evidence(st.doc_id, r["page"], r["bbox"], note), Evidence(st.doc_id, s["field"].page,
                                                                              s["field"].bbox, "amount", kind="field")]

        for si, bi in altered:
            s, b = S[si], B[bi]
            findings.append(Finding(
                id=new_id(), check="issuer_amount_differs", family="issuer", sensor="issuer",
                title=f"The bank's own record shows {_fmt(b.amount)} where the uploaded statement shows "
                      f"{_fmt(s['amount'])} ({s['direction']} on {s['date'].strftime('%d-%m-%Y')})",
                detail=f"Account Aggregator transaction {b.txn_id} ({b.narration or 'no narration'}) is the same "
                       f"{s['direction']} on the same date; only the amount differs.",
                confidence=0.95, localized=True, smoking_gun=True, evidence=ev(s, "row that differs from the bank's record"),
                fields=[s["field"].key()], docs=[st.doc_id],
                repair={"issuer_value": b.amount, "statement_value": s["amount"], "txn_id": b.txn_id}))
        for si in unmatched_s:
            s = S[si]
            findings.append(Finding(
                id=new_id(), check="issuer_row_missing", family="issuer", sensor="issuer",
                title=f"The bank has no record of this {s['direction']} of {_fmt(s['amount'])} on "
                      f"{s['date'].strftime('%d-%m-%Y')} shown on the uploaded statement",
                detail="No transaction with this amount and direction within a day of this date in the Account "
                       "Aggregator data for the same account and period.",
                confidence=0.9, localized=True, smoking_gun=True, evidence=ev(s, "row with no match in the bank's record"),
                fields=[s["field"].key()], docs=[st.doc_id]))
        for bi in unmatched_b:
            b = B[bi]
            when = b.dates[0]
            near = min(S, key=lambda s: abs((s["date"] - when).days)) if S else None
            findings.append(Finding(
                id=new_id(), check="issuer_row_absent", family="issuer", sensor="issuer",
                title=f"The bank's record has a {b.direction} of {_fmt(b.amount)} on {when.strftime('%d-%m-%Y')} "
                      f"({b.narration or 'no narration'}) that the uploaded statement does not show",
                detail=f"Account Aggregator transaction {b.txn_id}. Boxed: the statement row nearest that date, "
                       "where the transaction would appear.",
                confidence=0.9, localized=bool(near), smoking_gun=True,
                evidence=[Evidence(st.doc_id, near["row"]["page"], near["row"]["bbox"],
                                   "where the bank's transaction would appear")] if near else [whole],
                fields=[], docs=[st.doc_id], repair={"issuer_value": b.amount, "txn_id": b.txn_id,
                                                     "issuer_date": when.isoformat()}))
        drift = []
        for si, bis, _ in sorted(pairs, key=lambda p: (S[p[0]]["date"], S[p[0]]["i"])):
            s = S[si]
            bal = s["balance"]
            bb = B[bis[-1]].balance
            if bal is not None and bb is not None and len(bis) == 1 and abs(float(bal.value) - bb) > 0.5:
                drift.append((s, bal, bb))
        rep["balances_differ"] = len(drift)
        if drift:
            s, bal, bb = drift[0]
            gaps = sorted({round(float(x[1].value) - x[2], 2) for x in drift})
            findings.append(Finding(
                id=new_id(), check="issuer_balance_differs", family="issuer", sensor="issuer",
                title=f"Running balance departs from the bank's record from {s['date'].strftime('%d-%m-%Y')}: "
                      f"{_fmt(float(bal.value))} on the statement, {_fmt(bb)} at the bank "
                      f"({len(drift)} row(s) differ)",
                detail="Differences seen: " + ", ".join(_fmt(g) for g in gaps[:5]) + ". A constant gap after one row "
                       "is what a changed amount with regenerated balances leaves behind.",
                confidence=0.9, localized=True, smoking_gun=True,
                evidence=[Evidence(st.doc_id, bal.page, bal.bbox, "first balance that differs", kind="field")],
                fields=[bal.key()], docs=[st.doc_id], repair={"issuer_value": bb, "statement_value": float(bal.value)}))
    return findings, report


def benign_tests(f: Finding, docs: dict, ctx: dict) -> list[BenignTest]:
    """Innocent explanations for a disagreement with the bank's record."""
    fields = ctx.get("fields", {})
    T = []
    fld = fields.get(f.fields[0]) if f.fields else None
    if f.check in ("issuer_amount_differs", "issuer_balance_differs") and fld is not None:
        a, b = f"{f.repair.get('statement_value', 0):.2f}", f"{f.repair.get('issuer_value', 0):.2f}"
        one = len(a) == len(b) and sum(x != y for x, y in zip(a, b)) == 1
        T.append(BenignTest("SAKSHI misread the amount on the statement",
                            "OCR confidence below 0.60 and the two values one character apart",
                            "plausible" if (fld.conf < 0.6 and one) else "ruled_out",
                            f"OCR confidence {fld.conf:.2f}" + ("; one character apart" if one else "")))
    if f.check == "issuer_row_missing" and fld is not None:
        T.append(BenignTest("SAKSHI misread the amount on the statement", "OCR confidence below 0.60",
                            "plausible" if fld.conf < 0.6 else "ruled_out", f"OCR confidence {fld.conf:.2f}"))
        T.append(BenignTest("Posted on a different date at the bank", "a match one day either side was searched",
                            "ruled_out", "no same-amount transaction within one day"))
    if f.check == "issuer_row_absent":
        st = docs.get(f.docs[0]) if f.docs else None
        fit = (st.structure.get("transition_fit") if st else None) or 0
        unread = [n for n in (st.notes if st else []) if "unreadable" in n.lower() or "could not be read" in n.lower()]
        T.append(BenignTest("SAKSHI did not read that row of the statement",
                            "statement rows read with a balance-equation fit of at least 0.95 and no unreadable rows",
                            "plausible" if (fit < 0.95 or unread) else "ruled_out",
                            f"balance-equation fit {fit:.2f}" + (f"; {len(unread)} unreadable-row note(s)" if unread else "")))
        T.append(BenignTest("The transaction falls outside the statement's period",
                            "only transactions inside both periods are compared", "ruled_out", ""))
    if f.check == "issuer_account_mismatch":
        T.append(BenignTest("The applicant shared a second account", "cannot be checked without the other account's "
                            "data", "not_testable", ""))
    return T


def verified_identifiers(acc: IssuerAccount, docs: dict) -> dict:
    """Identifiers of this application that the bank's own record confirms, for cross-case memory.

    The holder must be this applicant (a holder name equal to an applicant name, transliteration-aware, or the
    holder's PAN equal to a PAN on the documents). Then the account numbers on the documents that end in the same
    four digits as the bank's masked account, and the holder's PAN, are verified as this applicant's."""
    names, pans, accounts = set(), set(), set()
    for d in docs.values():
        for n in ("applicant_name", "employee_name", "name", "account_holder"):
            if n in d.fields:
                names.add(name_key(str(d.fields[n].value)))
        if "pan" in d.fields:
            pans.add(str(d.fields["pan"].value).upper())
        if "account_no" in d.fields:
            accounts.add(str(d.fields["account_no"].value))
    holder = any(name_key(h) in names for h in acc.holders) or bool(set(acc.pans) & pans)
    if not holder:
        return {}
    last4 = _last4(acc.masked_account)
    out = {"account": sorted(a for a in accounts if last4 and _last4(a) == last4),
           "pan": sorted(set(acc.pans) & pans)}
    return {k: v for k, v in out.items() if v}
