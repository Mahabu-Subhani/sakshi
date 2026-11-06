"""Forgery Lab: automatic mutation harness (v1.0).

Applies randomized manipulation recipes to freshly generated genuine documents, runs the full
pipeline on each variant and reports detection rate per technique, plus the false-alarm rate on
re-scanned genuine variants. Recipes that SAKSHI is not expected to catch are included on
purpose and reported honestly.

    python tests/forgery_lab.py [--seeds 2] [--out OUTDIR] [--md results.md]
"""
from __future__ import annotations

import argparse
import json
import random
import shutil
import sys
from pathlib import Path

import numpy as np
import pymupdf as fitz
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "dataset"))
import generate as G  # noqa: E402
import redteam as RT  # noqa: E402

from sakshi.pipeline import run_case  # noqa: E402


def genuine_set(work: Path, seed: int, q: int = 90, noise: float = 5.0):
    """Build the five genuine documents with scan parameters varied by seed."""
    work.mkdir(parents=True, exist_ok=True)
    out = {}
    G.build_payslip(work / "slip.pdf", G.signature_strokes(3))
    d = fitz.open(str(work / "slip.pdf"))
    md = d.metadata
    md["creationDate"] = md["modDate"] = "D:20261031183000+05'30'"
    d.set_metadata(md)
    d.save(str(work / "01_payslip_oct2026.pdf"))
    d.close()
    out["slip"] = work / "01_payslip_oct2026.pdf"
    smeta = G.build_statement(work / "st.pdf", G.TXNS)
    st, Mst = G.simulate_scan(G.render_pdf(work / "st.pdf"), seed=seed * 10 + 1, angle=random.uniform(-0.4, 0.4), noise=noise)
    out["statement_img"], out["statement_M"], out["statement_boxes"] = st, Mst, smeta["boxes"]
    am = G.build_application(work / "ap.pdf", G.NET, G.EMI, G.PERSON["dob"], G.signature_strokes(7, 2, 0.006))
    ap, Map = G.simulate_scan(G.render_pdf(work / "ap.pdf"), seed=seed * 10 + 2, angle=random.uniform(-0.4, 0.4), noise=noise)
    out["app_img"], out["app_M"], out["app_boxes"] = ap, Map, am["boxes"]
    card, cm = G.build_id_card(seed=5)
    out["id_img"], out["id_meta"] = G.simulate_scan(card, seed=seed * 10 + 3, angle=0.15, noise=noise + 0.5)[0], cm
    G.build_letter(work / "lt.pdf", G.NET, G.PERSON["doj"], G.signature_strokes(3, 1, 0.012))
    lt, Mlt = G.simulate_scan(G.render_pdf(work / "lt.pdf"), seed=seed * 10 + 4, angle=random.uniform(-0.4, 0.4), noise=noise)
    out["letter_img"], out["letter_M"] = lt, Mlt
    out["q"] = q
    return out


def write_case(case: Path, g: dict, override: dict | None = None):
    override = override or {}
    case.mkdir(parents=True, exist_ok=True)
    shutil.copy(override.get("slip", g["slip"]), case / "01_payslip_oct2026.pdf")
    tmp = case / "_st.jpg"
    G.save_jpeg(override.get("statement_img", g["statement_img"]), tmp, override.get("statement_q", g["q"]))
    G.image_to_pdf(tmp, case / "02_bank_statement_sep_oct2026.pdf")
    tmp.unlink()
    G.save_jpeg(override.get("app_img", g["app_img"]), case / "03_loan_application_form.jpg", override.get("app_q", g["q"]))
    G.save_jpeg(override.get("id_img", g["id_img"]), case / "04_identity_card.jpg", override.get("id_q", 88))
    G.save_jpeg(override.get("letter_img", g["letter_img"]), case / "05_employment_letter.jpg", override.get("letter_q", g["q"]))


def jpeg_roundtrip(img, q):
    import cv2
    ok, enc = cv2.imencode(".jpg", img[:, :, ::-1], [cv2.IMWRITE_JPEG_QUALITY, q])
    return cv2.imdecode(enc, cv2.IMREAD_COLOR)[:, :, ::-1]


# ------------------------------------------------------------------ recipes (doc prefix, function)
def r_pdf_overlay(g, work, rnd, same_font=False):
    targets = ["40,000.00", "16,000.00", "17,800.00", "76,650.00", "8,150.00", "68,500.00", "4,800.00"]
    t = rnd.choice(targets)
    new = G.inr(float(t.replace(",", "")) + rnd.choice([5000, 9000, 18000]))
    dst = work / "slip_forged.pdf"
    shutil.copy(g["slip"], dst)
    d = fitz.open(str(dst))
    pg = d[0]
    r = pg.search_for(t)[0]
    pg.draw_rect(fitz.Rect(r.x0 - 1, r.y0 - 1, r.x1 + 1.5, r.y1 + 1), color=None, fill=(1, 1, 1), overlay=True)
    pg.insert_text(fitz.Point(r.x0, r.y1 - 2.2), new, fontname="helv" if same_font else "tiro", fontsize=10.2, overlay=True)
    d.saveIncr()
    d.close()
    return {"slip": dst}, "01_", f"{t} -> {new}"


def r_copy_move(g, work, rnd):
    img = g["statement_img"].copy()
    img = jpeg_roundtrip(img, 90)
    rows = [k for k in g["statement_boxes"] if k.endswith("_debit")]
    tk, dk = rnd.sample(rows, 2)
    t, dn = G.Box(**g["statement_boxes"][tk]), G.Box(**g["statement_boxes"][dk])
    w = G.stringWidth("2", "Helvetica", 10)
    M = g["statement_M"]
    tgt = G.map_rect(G.Box(t.x0, t.y_base, t.x0 + w, 10).to_px_rect(), M)
    src = G.map_rect(G.Box(dn.x0, dn.y_base, dn.x0 + w, 10).to_px_rect(), M)
    tx0, ty0, sx0, sy0 = int(tgt[0]) - 3, int(tgt[1]) - 3, int(src[0]) - 3, int(src[1]) - 3
    ww, hh = int(tgt[2] - tgt[0]) + 3, int(tgt[3] - tgt[1]) + 6
    img[ty0:ty0 + hh, tx0:tx0 + ww] = img[sy0:sy0 + hh, sx0:sx0 + ww]
    return {"statement_img": img, "statement_q": 92}, "02_", f"first digit of {tk} copied from {dk}"


def r_whiteout(g, work, rnd):
    key = rnd.choice(["declared_income", "existing_monthly_emis", "loan_amount_requested", "net_monthly_income"])
    boxes = g["app_boxes"]
    key = key if key in boxes else "existing_monthly_emis"
    img = jpeg_roundtrip(g["app_img"].copy(), 90)
    b = G.Box(**boxes[key])
    r = G.map_rect(b.to_px_rect(), g["app_M"])
    x0, y0, x1, y1 = int(r[0]) - 3, int(r[1]) - 3, int(r[2]) + 6, int(r[3]) + 3
    bg = np.median(img[y0 - 12:y0 - 4, x0:x1].reshape(-1, 3), axis=0).astype(np.uint8)
    img[y0:y1, x0:x1] = bg
    pil = Image.fromarray(img)
    ImageDraw.Draw(pil).text((x0 + rnd.randint(2, 9), y0 + rnd.randint(2, 6)), G.inr(rnd.choice([12500, 45000, 91000])),
                             font=G._font("forger", int(10 * G.SCALE * rnd.uniform(1.0, 1.2))), fill=(35, 35, 40))
    return {"app_img": np.array(pil), "app_q": 92}, "03_", f"{key} whited out and retyped"


def r_paint_q70(g, work, rnd):
    img = g["letter_img"].copy()
    from reportlab.pdfbase.pdfmetrics import stringWidth as sw
    prefix = "His current net monthly salary is Rs. "
    x0_pt = 55 + sw(prefix, "Helvetica", 11)
    x1_pt = x0_pt + sw("68,500.00", "Helvetica", 11)
    y_pt = G.PAGE_H - 215 - 3 * 18
    r = G.map_rect(G.Box(x0_pt, y_pt, x1_pt, 11).to_px_rect(), g["letter_M"])
    x0, y0, x1, y1 = int(r[0]) - 3, int(r[1]) - 4, int(r[2]) + 3, int(r[3]) + 4
    pil = Image.fromarray(img)
    dr = ImageDraw.Draw(pil)
    dr.rectangle([x0, y0, x1, y1], fill=(255, 255, 255))
    dr.text((x0 + 3, y0 + 3), G.inr(rnd.choice([86500, 95000, 112000])), font=G._font("sans", int(11 * G.SCALE * 0.98)), fill=(20, 20, 20))
    return {"letter_img": np.array(pil), "letter_q": 70}, "05_", "salary painted over, retyped, JPEG 70"


def r_photo_splice(g, work, rnd):
    img = jpeg_roundtrip(g["id_img"].copy(), 88)
    out, _ = G.splice_id_photo(img, g["id_meta"]["photo_box"])
    return {"id_img": out}, "04_", "photo replaced"


def r_consistent_edit(g, work, rnd):
    """Expected to be MISSED: a non-recurring row changed and the whole statement regenerated."""
    tx = list(G.TXNS)
    i = rnd.choice([0, 3, 4, 6, 9])
    d, desc, dr, cr = tx[i]
    tx[i] = (d, desc, dr + 3000 if dr else 0.0, cr + 3000 if cr else 0.0)
    G.build_statement(work / "st2.pdf", tx)
    st, _ = G.simulate_scan(G.render_pdf(work / "st2.pdf"), seed=rnd.randint(1, 999), angle=0.2)
    return {"statement_img": st}, "02_", f"row {i} changed by 3,000 with every balance regenerated (no pixel trace)"


RECIPES = [
    ("PDF white-box overlay, different font", lambda g, w, r: r_pdf_overlay(g, w, r, False)),
    ("PDF white-box overlay, same font", lambda g, w, r: r_pdf_overlay(g, w, r, True)),
    ("Scan copy-move digit (statement)", r_copy_move),
    ("Scan white-out and retype (application)", r_whiteout),
    ("Paint patch + JPEG 70 (letter)", r_paint_q70),
    ("ID photo splice", r_photo_splice),
    ("Regenerated statement, non-recurring row (expected miss)", r_consistent_edit),
]


def detected(d: dict, prefix: str) -> tuple[bool, str]:
    docs = {x["doc_id"]: x["filename"] for x in d["documents"]}
    best = "NONE"
    order = ["NONE", "INCONSISTENCY", "POTENTIAL_MANIPULATION"]
    for f in d["findings"] + d.get("document_assessments", []):
        if f["tier"] == "OBSERVATION":
            continue
        if any(docs.get(x, "").startswith(prefix) for x in f["docs"] + [k.split(".")[0] for k in f["fields"]]):
            if order.index(f["tier"]) > order.index(best):
                best = f["tier"]
    return best != "NONE", best


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seeds", type=int, default=2)
    ap.add_argument("--out", default=str(ROOT / "out" / "forgery_lab"))
    ap.add_argument("--md", default="")
    a = ap.parse_args()
    out = Path(a.out)
    if out.exists():
        shutil.rmtree(out)
    rows, fp_rows = [], []
    for s in range(a.seeds):
        random.seed(1000 + s)
        rnd = random.Random(2000 + s)
        g = genuine_set(out / f"_gen{s}", seed=s + 1, q=[90, 80, 85][s % 3], noise=[5.0, 3.5, 6.5][s % 3])
        # genuine controls: re-scanned with different noise and JPEG quality
        case = out / f"genuine_s{s}"
        write_case(case, g)
        d = run_case(sorted(str(p) for p in case.iterdir()), out / f"run_genuine_s{s}", case_id=f"LAB-GEN-{s}", html=False)
        bad = [f for f in d["findings"] if f["tier"] != "OBSERVATION"]
        fp_rows.append({"seed": s, "clean": not bad, "alarms": [f"{f['tier'][:3]} {f['check']}: {f['title'][:80]}" for f in bad]})
        print(f"genuine s{s}: {'clean' if not bad else 'FALSE ALARM'} {[x[:70] for x in fp_rows[-1]['alarms']]}", flush=True)
        for name, fn in RECIPES:
            ov, prefix, what = fn(g, out / f"_gen{s}", rnd)
            case = out / f"{name[:24].replace(' ', '_').replace(',', '')}_s{s}"
            write_case(case, g, ov)
            d = run_case(sorted(str(p) for p in case.iterdir()), out / f"run_{case.name}", case_id=case.name, html=False)
            hit, tier = detected(d, prefix)
            rows.append({"recipe": name, "seed": s, "what": what, "detected": hit, "tier": tier})
            print(f"{'HIT ' if hit else 'MISS'} {tier:24s} {name} | {what}", flush=True)
    summary = {}
    for r in rows:
        k = r["recipe"]
        summary.setdefault(k, {"n": 0, "hit": 0, "pm": 0})
        summary[k]["n"] += 1
        summary[k]["hit"] += r["detected"]
        summary[k]["pm"] += r["tier"] == "POTENTIAL_MANIPULATION"
    lines = ["| Recipe | Detected | At potential manipulation |", "|---|---|---|"]
    for k, v in summary.items():
        lines.append(f"| {k} | {v['hit']}/{v['n']} | {v['pm']}/{v['n']} |")
    lines.append(f"| Genuine re-scans (false-alarm check) | clean {sum(r['clean'] for r in fp_rows)}/{len(fp_rows)} | |")
    md = "\n".join(lines)
    print("\n" + md)
    (out / "results.json").write_text(json.dumps({"rows": rows, "genuine": fp_rows, "summary": summary}, indent=1))
    if a.md:
        Path(a.md).write_text(md + "\n")


if __name__ == "__main__":
    main()
