"""Long and password-protected statements: pages beyond the pixel-forensics cap are still read.

    python tests/run_long_statement.py [--out OUTDIR]

Builds a 13-page statement (one transaction per page) and a copy whose page-8 amount was edited
while the printed balances were kept, born-digital and scanned. PASS = the page-8 edit is caught
(a non-observation finding with evidence on page 8 or later), the genuine statement stays clean,
and the locked copy is rejected without its password and reads the same as the unlocked file with it.
The page-8 edit is also run with reading capped at 6 pages, to show what the old limit missed.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pymupdf as fitz

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "dataset"))
import generate as G  # noqa: E402
import redteam as RT  # noqa: E402

from sakshi import ingest as ingest_mod  # noqa: E402
from sakshi.pipeline import run_case  # noqa: E402

EDIT_ROW = 7  # 0-based: one transaction per page, so this row is printed on page 8
PASSWORD = "Test@2026"


def build(work: Path) -> dict:
    work.mkdir(parents=True, exist_ok=True)
    tx = [(d, desc, dr, cr, None, None) for d, desc, dr, cr in G.TXNS]
    bal, bals = G.OPENING, []
    for _, _, dr, cr, *_ in tx:
        bal = round(bal - dr + cr, 2)
        bals.append(bal)
    d, desc, dr, cr, ref, d2 = tx[EDIT_ROW]
    forged = list(tx)
    forged[EDIT_ROW] = (d, desc, dr - 5000 if dr else 0.0, cr + 5000 if cr else 0.0, ref, d2)
    f = {"genuine": work / "genuine.pdf", "forged": work / "forged.pdf"}
    RT.build_statement2(f["genuine"], tx, rows_per_page=1)
    RT.build_statement2(f["forged"], forged, rows_per_page=1, balance_override=bals)  # amount edited, balances kept
    f["forged_scan"] = work / "forged_scan.pdf"
    RT.scanned_pdf(f["forged"], f["forged_scan"], seed=808)
    f["locked"] = work / "genuine_locked.pdf"
    doc = fitz.open(str(f["genuine"]))
    doc.save(str(f["locked"]), encryption=fitz.PDF_ENCRYPT_AES_256, user_pw=PASSWORD, owner_pw=PASSWORD + "-owner")
    doc.close()
    return f


def run(path: Path | str, out: Path, name: str, **kw) -> dict:
    return run_case([str(path)], out / name, case_id=name, html=False, registry_path=None, **kw)


def loud(d):
    return [f for f in d["findings"] if f["tier"] != "OBSERVATION"]


def late(d):
    return [f for f in loud(d) if any(e["page"] >= ingest_mod.MAX_PAGES for e in f["evidence"])]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(ROOT / "out" / "long_statement"))
    a = ap.parse_args()
    out = Path(a.out)
    f = build(out / "_docs")
    pages = fitz.open(str(f["genuine"])).page_count
    print(f"statement: {pages} pages, edit on page {EDIT_ROW + 1}")
    ok = True

    def check(label, cond, detail=""):
        nonlocal ok
        ok &= cond
        print(f"{'PASS' if cond else 'FAIL'} {label}{(': ' + detail) if detail else ''}")

    g = run(f["genuine"], out, "genuine")
    check(f"genuine {pages}-page statement clean", not loud(g), "; ".join(x["title"][:80] for x in loud(g)[:3]))
    for name in ("forged", "forged_scan"):
        d = run(f[name], out, name)
        hit = late(d)
        check(f"{name}: page-{EDIT_ROW + 1} edit caught", bool(hit),
              "; ".join(f"{x['tier'][:3]} {x['check']} p{x['evidence'][0]['page'] + 1}: {x['title'][:70]}" for x in hit[:2]))
    keep = ingest_mod.MAX_TEXT_PAGES
    ingest_mod.MAX_TEXT_PAGES = ingest_mod.MAX_PAGES  # the old limit: only the first 6 pages were read
    try:
        old = run(f["forged"], out, "forged_old_limit")
    finally:
        ingest_mod.MAX_TEXT_PAGES = keep
    print(f"INFO with the old 6-page limit the edit is {'caught' if late(old) else 'missed'} "
          f"({len(loud(old))} non-observation finding(s) in total)")
    no_pw = run(f["locked"], out, "locked_no_password")
    check("locked PDF rejected without a password", bool(no_pw["rejected"]), no_pw["rejected"][0]["reason"] if no_pw["rejected"] else "")
    wrong = run(f["locked"], out, "locked_wrong_password", passwords=["wrong"])
    check("locked PDF rejected with a wrong password", bool(wrong["rejected"]))
    right = run(f["locked"], out, "locked_right_password", passwords=["wrong", PASSWORD])
    same = sorted((x["check"], x["tier"]) for x in right["findings"]) == sorted((x["check"], x["tier"]) for x in g["findings"])
    check("locked PDF opens with its password and reads like the unlocked file", not right["rejected"] and same)
    leaked = PASSWORD in (out / "locked_right_password" / "dossier.json").read_text(encoding="utf-8") + \
        (out / "locked_right_password" / "audit.jsonl").read_text(encoding="utf-8")
    check("password not written to the dossier or audit trail", not leaked)
    check("password forgotten after the case", not ingest_mod._PASSWORDS)
    slash = run(f["locked"].as_posix(), out, "locked_forward_slashes", passwords=[PASSWORD])  # a str, kept as typed
    check("password forgotten for a forward-slash path too", not slash["rejected"] and not ingest_mod._PASSWORDS)
    real = run_case.__globals__["engine"].run
    run_case.__globals__["engine"].run = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("simulated crash"))
    try:
        run(f["locked"], out, "locked_crash", passwords=[PASSWORD])
    except RuntimeError:
        pass
    finally:
        run_case.__globals__["engine"].run = real
    check("password forgotten when a case crashes", not ingest_mod._PASSWORDS)
    print("\nRESULT:", "ALL PASS" if ok else "FAILURES")


if __name__ == "__main__":
    main()
