"""Synthetic Account Aggregator FI data for the demo applicant: what the bank itself holds for the account.

Writes the deposit account in the ReBIT FI schema shape (Account / Profile / Holders / Summary / Transactions),
as XML and as its JSON rendering, from the same transactions the genuine statement is drawn from
(generate.TXNS and generate.OPENING). Every file is labelled synthetic.

    python dataset/aa.py            # writes dataset/issuer/aa_demo_applicant.xml and .json
"""
from __future__ import annotations

import json
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
import generate as G  # noqa: E402

NS = "http://api.rebit.org.in/FISchema/deposit"
NOTE = "SYNTHETIC SPECIMEN - HACKATHON DEMO DATA - NOT REAL FI DATA"


def _iso(dmy: str) -> str:
    d, m, y = dmy.split("-")
    return f"{y}-{m}-{d}"


def account(txns=None, opening=None, person=None, start="2026-09-01", end="2026-10-31") -> dict:
    """The Account object as a dict (the JSON rendering of the ReBIT deposit schema)."""
    txns = G.TXNS if txns is None else txns
    bal = G.OPENING if opening is None else opening
    p = G.PERSON if person is None else person
    rows = []
    for i, (d, narr, dr, cr) in enumerate(txns):
        bal = round(bal - dr + cr, 2)
        mode = "UPI" if narr.startswith("UPI") else "NEFT" if "NEFT" in narr or "SALARY" in narr else \
            "IMPS" if narr.startswith("IMPS") else "ATM" if narr.startswith("ATM") else "OTHERS"
        rows.append({"txnId": f"S{26090000 + i:08d}", "type": "DEBIT" if dr else "CREDIT", "mode": mode,
                     "amount": f"{dr or cr:.2f}", "currentBalance": f"{bal:.2f}",
                     "transactionTimestamp": f"{_iso(d)}T10:00:00+05:30", "valueDate": _iso(d),
                     "narration": narr, "reference": f"REF{i:06d}"})
    return {
        "type": "deposit", "maskedAccNumber": "X" * (len(p["account"]) - 4) + p["account"][-4:], "version": "1.1",
        "linkedAccRef": "SYNTHETIC-LINK-0001",
        "Profile": {"Holders": {"type": "SINGLE", "Holder": [{
            "name": p["bank_name"], "dob": _iso(p["dob"]), "mobile": p["mobile"], "pan": p["pan"],
            "ckycCompliance": "true"}]}},
        "Summary": {"currentBalance": rows[-1]["currentBalance"] if rows else f"{bal:.2f}", "currency": "INR",
                    "balanceDateTime": f"{end}T23:59:59+05:30", "type": "SAVINGS", "branch": "HSR LAYOUT",
                    "ifscCode": p["ifsc"], "openingDate": "2021-07-01", "status": "ACTIVE"},
        "Transactions": {"startDate": start, "endDate": end, "Transaction": rows},
    }


def to_xml(acc: dict) -> bytes:
    ET.register_namespace("", NS)
    q = lambda t: f"{{{NS}}}{t}"  # noqa: E731
    root = ET.Element(q("Account"), {k: v for k, v in acc.items() if isinstance(v, str)})
    prof = ET.SubElement(root, q("Profile"))
    hs = ET.SubElement(prof, q("Holders"), {"type": acc["Profile"]["Holders"]["type"]})
    for h in acc["Profile"]["Holders"]["Holder"]:
        ET.SubElement(hs, q("Holder"), h)
    ET.SubElement(root, q("Summary"), acc["Summary"])
    tx = ET.SubElement(root, q("Transactions"), {k: v for k, v in acc["Transactions"].items() if isinstance(v, str)})
    for t in acc["Transactions"]["Transaction"]:
        ET.SubElement(tx, q("Transaction"), t)
    ET.indent(root)
    return (f"<?xml version='1.0' encoding='UTF-8'?>\n<!-- {NOTE} -->\n").encode() + ET.tostring(root, encoding="utf-8")


def write(folder: Path, name: str = "aa_demo_applicant", acc: dict | None = None) -> tuple[Path, Path]:
    acc = acc or account()
    folder.mkdir(parents=True, exist_ok=True)
    x, j = folder / f"{name}.xml", folder / f"{name}.json"
    x.write_bytes(to_xml(acc))
    j.write_text(json.dumps({"_note": NOTE, "Account": acc}, indent=1), encoding="utf-8")
    return x, j


if __name__ == "__main__":
    for p in write(ROOT / "issuer"):
        print(p)
