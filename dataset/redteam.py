"""Blind red-team cases designed by Gemini 4 Argon (v1.0 round 1), synthesized by Claude
without looking at SAKSHI's thresholds, plus layout-varied genuine controls.

Argon's brief for each scenario is quoted in MANIFEST_ground_truth.json. All documents are
fictional and labelled SYNTHETIC SPECIMEN.

    python dataset/redteam.py      -> dataset/redteam/<case>/...
"""
from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

import cv2
import numpy as np
import pymupdf as fitz
from PIL import Image, ImageDraw
from reportlab.lib.pagesizes import A4
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.pdfgen import canvas

sys.path.insert(0, str(Path(__file__).resolve().parent))
import generate as G  # noqa: E402

OUT = Path(__file__).resolve().parent / "redteam"
W, H = A4
P = G.PERSON


def _hdr(c, title="STATEMENT OF ACCOUNT", period="01-09-2026 to 31-10-2026", holder=None):
    G._specimen(c)
    c.setFont("Helvetica-Bold", 16)
    c.setFillColorRGB(0.1, 0.25, 0.45)
    c.drawString(45, H - 60, "DEMO COOPERATIVE BANK LTD.")
    c.setFillColorRGB(0, 0, 0)
    c.setFont("Helvetica", 9)
    c.drawString(45, H - 74, "HSR Layout Branch, Bengaluru 560102 (fictional bank)")
    c.setFont("Helvetica-Bold", 12)
    c.drawString(45, H - 100, title)
    c.setFont("Helvetica", 10)
    info = [("Account Holder", holder or P["bank_name"]), ("Account No", P["account"]), ("IFSC", P["ifsc"]),
            ("Statement Period", period)]
    for i, (k, v) in enumerate(info):
        c.drawString(45, H - 122 - i * 16, f"{k}:")
        c.drawString(150, H - 122 - i * 16, v)


def build_statement2(path, txns, layout="dcb", opening=G.OPENING, rows_per_page=99, date_fmt=None,
                     period="01-09-2026 to 31-10-2026", balance_override=None, summary=True):
    """txns: (date, desc, dr, cr, ref, desc2). layout 'dcb' (Withdrawal/Deposit/Balance) or 'drcr'.
    balance_override: list of balances to print instead of the computed ones (for forged statements)."""
    c = canvas.Canvas(str(path), pagesize=A4)
    fmt = date_fmt or (lambda d: d)
    bal = opening
    bals = []
    for d, desc, dr, cr, *_ in txns:
        bal = round(bal - dr + cr, 2)
        bals.append(bal)
    if balance_override is not None:
        bals = balance_override
    tot_dr = sum(t[2] for t in txns)
    tot_cr = sum(t[3] for t in txns)
    pages = [txns[i:i + rows_per_page] for i in range(0, len(txns), rows_per_page)] or [[]]
    k = 0
    for pi, chunk in enumerate(pages):
        if pi == 0:
            _hdr(c, period=period)
            y = H - 210
            c.setLineWidth(0.6)
            c.line(40, y + 14, W - 38, y + 14)
            c.setFont("Helvetica-Bold", 10)
            if layout == "dcb":
                c.drawString(45, y, "Date"); c.drawString(122, y, "Particulars")
                c.drawRightString(390, y, "Withdrawal"); c.drawRightString(470, y, "Deposit"); c.drawRightString(552, y, "Balance")
            else:
                c.drawString(45, y, "Date"); c.drawString(122, y, "Narration"); c.drawString(300, y, "Chq/Ref No")
                c.drawRightString(445, y, "Amount"); c.drawString(456, y, "Dr/Cr"); c.drawRightString(552, y, "Balance")
            c.line(40, y - 6, W - 38, y - 6)
            c.setFont("Helvetica", 10)
            y -= 24
            c.drawString(45, y, fmt("01-09-2026"))
            c.drawString(122, y, "OPENING BALANCE")
            c.drawRightString(552, y, G.inr(opening))
        else:
            G._specimen(c)
            c.setFont("Helvetica", 10)
            y = H - 70
            c.drawString(122, y, "B/F")
            c.drawRightString(552, y, G.inr(bals[k - 1]))
        for (d, desc, dr, cr, ref, desc2) in chunk:
            y -= 22
            c.drawString(45, y, fmt(d))
            c.drawString(122, y, desc)
            if layout == "dcb":
                if dr:
                    c.drawRightString(390, y, G.inr(dr))
                if cr:
                    c.drawRightString(470, y, G.inr(cr))
            else:
                if ref:
                    c.drawString(300, y, ref)
                c.drawRightString(445, y, G.inr(dr or cr))
                c.drawString(456, y, "Dr" if dr else "Cr")
            c.drawRightString(552, y, G.inr(bals[k]))
            if desc2:
                y -= 14
                c.setFont("Helvetica", 9)
                c.drawString(122, y, desc2)
                c.setFont("Helvetica", 10)
            k += 1
        if pi < len(pages) - 1:
            y -= 26
            c.drawString(122, y, "C/F")
            c.drawRightString(552, y, G.inr(bals[k - 1]))
            c.setFont("Helvetica", 8)
            c.drawString(45, 40, f"Page {pi + 1} of {len(pages)}")
            c.showPage()
    if summary:
        y -= 34
        c.setFont("Helvetica-Bold", 10)
        summ = [("Opening Balance", opening), ("Total Debits", tot_dr), ("Total Credits", tot_cr), ("Closing Balance", bals[-1])]
        for i, (kk, v) in enumerate(summ):
            c.drawString(300, y - i * 16, f"{kk}:")
            c.drawRightString(552, y - i * 16, G.inr(v))
    c.setFont("Helvetica", 8)
    c.drawString(45, 40, f"Page {len(pages)} of {len(pages)} - Demo Cooperative Bank is fictional.")
    c.showPage()
    c.save()


def render_all(pdf_path):
    doc = fitz.open(str(pdf_path))
    out = []
    for pg in doc:
        pix = pg.get_pixmap(dpi=G.DPI)
        out.append(np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.h, pix.w, pix.n)[:, :, :3].copy())
    doc.close()
    return out


def scanned_pdf(pdf_in, pdf_out, seed, q=90):
    imgs = [G.simulate_scan(im, seed=seed + i, angle=0.25)[0] for i, im in enumerate(render_all(pdf_in))]
    doc = fitz.open()
    tmp = Path(pdf_out).with_suffix(".tmp")
    tmp.mkdir(exist_ok=True)
    for i, im in enumerate(imgs):
        jp = tmp / f"p{i}.jpg"
        G.save_jpeg(im, jp, q)
        pg = doc.new_page(width=im.shape[1] / G.SCALE, height=im.shape[0] / G.SCALE)
        pg.insert_image(pg.rect, filename=str(jp))
    doc.set_metadata({"producer": "Demo ScanStation 3 (fictional)"})
    doc.save(str(pdf_out))
    doc.close()
    shutil.rmtree(tmp)


def scan_to_jpg(pdf_in, jpg_out, seed, q=90, angle=0.3):
    im, M = G.simulate_scan(G.render_pdf(pdf_in), seed=seed, angle=angle)
    G.save_jpeg(im, jpg_out, q)
    return im, M


BASE_TXNS = [(d, desc, dr, cr, None, None) for d, desc, dr, cr in G.TXNS]


def _write_manifest(case_dir, data):
    (case_dir / "MANIFEST_ground_truth.json").write_text(json.dumps(data, indent=2))


def fresh(name):
    d = OUT / name
    if d.exists():
        shutil.rmtree(d)
    d.mkdir(parents=True)
    w = OUT / "_work" / name
    w.mkdir(parents=True, exist_ok=True)
    return d, w


def rt1():
    """Argon S1: internally consistent payslip inflation + regenerated statement + matching declaration."""
    d, w = fresh("RT1_coordinated_inflation")
    earn = [("Basic Salary", 60000), ("House Rent Allowance", 16000), ("Special Allowance", 17800),
            ("Conveyance Allowance", 1600), ("Medical Allowance", 1250)]
    ded = list(G.DEDUCTIONS)  # forger kept PF at 4,800 (12% of the OLD basic)
    G.build_payslip(d / "01_payslip_oct2026.pdf", G.signature_strokes(3), earnings=earn, deductions=ded)
    tx = [list(t) for t in BASE_TXNS]
    tx[12][3] = 88500.0  # October salary credit inflated by 20,000; statement regenerated so balances follow
    tx = [tuple(t) for t in tx]
    build_statement2(w / "st.pdf", tx)
    scanned_pdf(w / "st.pdf", d / "02_bank_statement_sep_oct2026.pdf", seed=101)
    G.build_application(w / "ap.pdf", 88500, G.EMI, P["dob"], G.signature_strokes(7, 2, 0.006))
    scan_to_jpg(w / "ap.pdf", d / "03_loan_application_form.jpg", seed=102)
    G.build_letter(w / "lt.pdf", G.NET, P["doj"], G.signature_strokes(3, 1, 0.012))
    scan_to_jpg(w / "lt.pdf", d / "05_employment_letter.jpg", seed=103)
    _write_manifest(d, {"scenario": "RT1", "by": "Gemini 4 Argon", "manipulated": True,
                        "brief": "Basic +20,000 with gross, net and words updated so the payslip math holds; salary credit +20,000 and every later balance and total regenerated; declared income updated; clean born-digital PDFs (no layers, no incremental update).",
                        "targets": [{"doc": "01_", "fields": ["net_pay", "basic_salary", "provident_fund", "gross"]},
                                    {"doc": "02_", "fields": ["credit"]}, {"doc": "03_", "fields": ["declared_income"]}]})


def rt2():
    """Argon S2: single Amount + Dr/Cr column statement, an EMI row deleted, balances not fixed."""
    d, w = fresh("RT2_drcr_deleted_emi")
    G.build_payslip(d / "01_payslip_oct2026.pdf", G.signature_strokes(3))
    full = BASE_TXNS
    bal, bals = G.OPENING, []
    for t in full:
        bal = round(bal - t[2] + t[3], 2)
        bals.append(bal)
    keep = [i for i in range(len(full)) if i != 7]  # drop the 05-10-2026 EMI row, keep its printed balances
    tx = [(t[0], t[1], t[2], t[3], f"{400100 + i}" if t[2] else None, None) for i, t in enumerate(full)]
    build_statement2(w / "st.pdf", [tx[i] for i in keep], layout="drcr", balance_override=[bals[i] for i in keep],
                     summary=False)
    scanned_pdf(w / "st.pdf", d / "02_bank_statement_sep_oct2026.pdf", seed=201)
    G.build_application(w / "ap.pdf", G.NET, 0.0, P["dob"], G.signature_strokes(7, 2, 0.006))
    scan_to_jpg(w / "ap.pdf", d / "03_loan_application_form.jpg", seed=202)
    _write_manifest(d, {"scenario": "RT2", "by": "Gemini 4 Argon", "manipulated": True,
                        "brief": "Statement with Date | Narration | Chq/Ref No | Amount | Dr/Cr | Balance; the 05-10-2026 EMI row (24,500 Dr) deleted without fixing the running balance; applicant declares no EMIs.",
                        "targets": [{"doc": "02_", "fields": ["balance", "debit"]}, {"doc": "03_", "fields": ["declared_emi"]}]})


def _letter_ctc(path, ctc_text, sig):
    G.build_letter(path, 0, P["doj"], sig, salary_line=f"His gross annual CTC is Rs. {ctc_text}/-.")


def rt3():
    """Argon S3: pure-white MS Paint patch over the CTC on a scanned letter, retyped, saved at JPEG 70."""
    d, w = fresh("RT3_letter_paint_patch")
    _letter_ctc(w / "lt.pdf", "6,00,000", G.signature_strokes(3, 1, 0.012))
    im, M = G.simulate_scan(G.render_pdf(w / "lt.pdf"), seed=301, angle=0.35)
    G.save_jpeg(im, w / "scan.jpg", 90)
    im = G.load(w / "scan.jpg")
    # locate "6,00,000" via the drawn line: the salary line is the 4th body line
    from reportlab.pdfbase.pdfmetrics import stringWidth as sw
    prefix = "His gross annual CTC is Rs. "
    x0_pt = 55 + sw(prefix, "Helvetica", 11)
    x1_pt = x0_pt + sw("6,00,000/-.", "Helvetica", 11)
    y_pt = H - 215 - 3 * 18
    r = G.map_rect(G.Box(x0_pt, y_pt, x1_pt, 11).to_px_rect(), M)
    x0, y0, x1, y1 = int(r[0]) - 3, int(r[1]) - 4, int(r[2]) + 3, int(r[3]) + 4
    pil = Image.fromarray(im)
    dr = ImageDraw.Draw(pil)
    dr.rectangle([x0, y0, x1, y1], fill=(255, 255, 255))
    dr.text((x0 + 3, y0 + 3), "9,50,000/-.", font=G._font("sans", int(11 * G.SCALE * 0.98)), fill=(20, 20, 20))
    G.save_jpeg(np.array(pil), d / "05_employment_letter.jpg", 70)
    _write_manifest(d, {"scenario": "RT3", "by": "Gemini 4 Argon", "manipulated": True,
                        "brief": "Single scanned letter, no internal math. Pure white rectangle over 'Rs. 6,00,000/-', retyped '9,50,000' in a matching sans at matching height, whole page saved at JPEG quality 70. Amounts have no paise.",
                        "region_px": [x0, y0, x1, y1],
                        "targets": [{"doc": "05_", "fields": ["letter_salary"]}]})


def rt4():
    """Argon S4: October payslip = clone of the September scan with month and pay date patched in."""
    d, w = fresh("RT4_cloned_payslip_scans")
    G.build_payslip(w / "sep.pdf", G.signature_strokes(3), month_label="SEPTEMBER 2026", pay_date="30-09-2026")
    G.build_payslip(w / "oct.pdf", G.signature_strokes(3), month_label="OCTOBER 2026", pay_date="31-10-2026")
    sep, M = G.simulate_scan(G.render_pdf(w / "sep.pdf"), seed=401, angle=0.2)
    octg, _ = G.simulate_scan(G.render_pdf(w / "oct.pdf"), seed=402, angle=0.2)  # a real October scan as glyph donor
    G.save_jpeg(sep, d / "01a_payslip_sep2026.jpg", 90)
    clone = sep.copy()
    # patch the title line and the pay-date value from the donor scan (same geometry, different scan)
    for (x0p, yb, txt, font, size) in [(0, H - 122, "", "Helvetica-Bold", 13), (410, H - 160 - 2 * 18, "", "Helvetica", 10)]:
        if x0p == 0:
            rr = G.map_rect((120 * G.SCALE, (H - 136) * G.SCALE, (W - 120) * G.SCALE, (H - 110) * G.SCALE), M)
        else:
            rr = G.map_rect((405 * G.SCALE, (H - yb - 13) * G.SCALE, 480 * G.SCALE, (H - yb + 4) * G.SCALE), M)
        a, b, c2, e = (int(v) for v in rr)
        clone[b:e, a:c2] = octg[b:e, a:c2]
    G.save_jpeg(clone, d / "01b_payslip_oct2026.jpg", 90)
    tx = [t for t in BASE_TXNS if t[0] < "25-10-2026" or not t[0].endswith("10-2026")]
    tx = [t for t in BASE_TXNS if not (t[0].endswith("-10-2026") and int(t[0][:2]) > 25)]
    build_statement2(w / "st.pdf", tx, period="01-09-2026 to 25-10-2026")
    scanned_pdf(w / "st.pdf", d / "02_bank_statement_sep_oct2026.pdf", seed=403)
    _write_manifest(d, {"scenario": "RT4", "by": "Gemini 4 Argon", "manipulated": True,
                        "brief": "Two payslip scans in one packet. The October slip is the September scan with only the month and pay date replaced by patches from another scan; every number identical. Statement ends 25-10-2026, so no October salary credit can be checked.",
                        "targets": [{"doc": "01b_", "fields": []}]})


def rt5():
    """Argon S5: ID card year of birth changed 1996 -> 1993 with font-matched digits; application agrees."""
    d, w = fresh("RT5_id_dob_font_matched")
    card, meta = G.build_id_card(seed=5)
    im, M = G.simulate_scan(card, seed=501, angle=0.15, noise=5.5)
    G.save_jpeg(im, w / "id.jpg", 88)
    im = G.load(w / "id.jpg")
    # DOB value is drawn at (410, 175+78+30) with sans_bold 32 on the card canvas
    f_val = G._font("sans_bold", 32)
    x_txt = 410 + f_val.getlength("14-03-19")
    y_txt = 175 + 78 + 30
    bx0, by0, bx1, by1 = (int(v) for v in G.map_rect((x_txt - 1, y_txt + 2, x_txt + f_val.getlength("96") + 2, y_txt + 34), M))
    patch = np.full((by1 - by0, bx1 - bx0, 3), 0, np.uint8)
    bg = np.median(im[by0 - 8:by0 - 2, bx0:bx1].reshape(-1, 3), axis=0)
    patch[:] = bg.astype(np.uint8)
    pil = Image.fromarray(patch)
    dr = ImageDraw.Draw(pil)
    dr.text((1, -2), "93", font=G._font("forger", 33), fill=(15, 15, 15))
    p = np.array(pil).astype(np.float32)
    p = cv2.GaussianBlur(p, (0, 0), 0.65)
    rng = np.random.default_rng(55)
    p += rng.normal(0, 5.5, p.shape[:2])[:, :, None]  # forger adds matching noise
    im[by0:by1, bx0:bx1] = np.clip(p, 0, 255).astype(np.uint8)
    G.save_jpeg(im, d / "04_identity_card.jpg", 88)
    G.build_application(w / "ap.pdf", G.NET, G.EMI, "14-03-1993", G.signature_strokes(7, 2, 0.006))
    scan_to_jpg(w / "ap.pdf", d / "03_loan_application_form.jpg", seed=502)
    _write_manifest(d, {"scenario": "RT5", "by": "Gemini 4 Argon", "manipulated": True,
                        "brief": "ID card year of birth digits '96' replaced by '93' in a different sans font, matched in height, blur and noise; the application declares the same forged DOB.",
                        "region_px": [bx0, by0, bx1, by1],
                        "targets": [{"doc": "04_", "fields": ["dob"]}]})


def rt6():
    """Argon S6 (false-positive trap): genuine 2-page statement with B/F, C/F, wrapped narrations, references."""
    d, w = fresh("RT6_genuine_two_page_trap")
    tx = []
    for i, (dd, desc, dr, cr) in enumerate(G.TXNS):
        desc2 = None
        if desc.startswith("UPI/"):
            desc = f"UPI/4012{i:02d}5678901/{desc.split('/')[1]}"
            desc2 = f"Ref 55{i:02d}13  merchant payment"
        tx.append((dd, desc, dr, cr, None, desc2))
    build_statement2(w / "st.pdf", tx, layout="dcb", rows_per_page=7)
    scanned_pdf(w / "st.pdf", d / "02_bank_statement_sep_oct2026.pdf", seed=601)
    G.build_payslip(d / "01_payslip_oct2026.pdf", G.signature_strokes(3))
    G.build_application(w / "ap.pdf", G.NET, G.EMI, P["dob"], G.signature_strokes(7, 2, 0.006))
    scan_to_jpg(w / "ap.pdf", d / "03_loan_application_form.jpg", seed=602)
    _write_manifest(d, {"scenario": "RT6", "by": "Gemini 4 Argon", "manipulated": False,
                        "brief": "Genuine. Two-page statement, header only on page 1, C/F and B/F rows, UPI references and wrapped narrations with numbers near the amount columns."})


def g7():
    """Genuine control with other conventions: Dr/Cr statement, 'DD-Mon-YYYY' dates, letter amount without paise."""
    d, w = fresh("G7_genuine_other_formats")
    mon = {"09": "Sep", "10": "Oct"}
    fmt = lambda s: f"{s[:2]}-{mon.get(s[3:5], s[3:5])}-{s[6:]}"  # noqa: E731
    tx = [(dd, desc, dr, cr, f"{300100 + i}" if dr else None, None) for i, (dd, desc, dr, cr) in enumerate(G.TXNS)]
    build_statement2(w / "st.pdf", tx, layout="drcr", date_fmt=fmt)
    scanned_pdf(w / "st.pdf", d / "02_bank_statement_sep_oct2026.pdf", seed=701)
    G.build_payslip(d / "01_payslip_oct2026.pdf", G.signature_strokes(3))
    G.build_letter(w / "lt.pdf", 0, P["doj"], G.signature_strokes(3, 1, 0.012),
                   salary_line="His current net monthly salary is Rs. 68,500/-.")
    scan_to_jpg(w / "lt.pdf", d / "05_employment_letter.jpg", seed=703)
    G.build_application(w / "ap.pdf", G.NET, G.EMI, P["dob"], G.signature_strokes(7, 2, 0.006))
    scan_to_jpg(w / "ap.pdf", d / "03_loan_application_form.jpg", seed=702)
    _write_manifest(d, {"scenario": "G7", "by": "Claude", "manipulated": False,
                        "brief": "Genuine. Single Amount + Dr/Cr statement with cheque numbers, dates like 05-Oct-2026, letter salary written 'Rs. 68,500/-'."})


def g8():
    """Genuine control for scan-based sensors: two separately scanned genuine payslips (Sep, Oct) and a statement."""
    d, w = fresh("G8_genuine_scanned_payslips")
    G.build_payslip(w / "sep.pdf", G.signature_strokes(3), month_label="SEPTEMBER 2026", pay_date="30-09-2026")
    G.build_payslip(w / "oct.pdf", G.signature_strokes(3), month_label="OCTOBER 2026", pay_date="31-10-2026")
    scan_to_jpg(w / "sep.pdf", d / "01a_payslip_sep2026.jpg", seed=801, angle=0.2)
    scan_to_jpg(w / "oct.pdf", d / "01b_payslip_oct2026.jpg", seed=802, angle=-0.15)
    build_statement2(w / "st.pdf", BASE_TXNS)
    scanned_pdf(w / "st.pdf", d / "02_bank_statement_sep_oct2026.pdf", seed=803)
    _write_manifest(d, {"scenario": "G8", "by": "Claude", "manipulated": False,
                        "brief": "Genuine. Two payslips printed by the same payroll system (identical signature image and layout) but scanned separately, plus the statement."})


def rt7():
    """Claude's scenario: an identity ring. A different applicant reuses the ID photo of an earlier
    applicant and the same salary account. Only detectable with cross-case memory."""
    d, w = fresh("RT7_identity_ring")
    saved = dict(G.PERSON)
    try:
        G.PERSON.update(name="Rahul Verma", bank_name="RAHUL VERMA", dob="02-11-1994", pan="BXRPV7712L",
                        mobile="9000077777", id_no="DNI 7305 1188 2044", emp_id="NA-20991",
                        address="No 14, 2nd Cross, Koramangala, Bengaluru 560034")
        card, _ = G.build_id_card(seed=5)  # same avatar image as the earlier applicant's card
        im, _ = G.simulate_scan(card, seed=901, angle=0.12, noise=5.0)
        G.save_jpeg(im, d / "04_identity_card.jpg", 88)
        G.build_application(w / "ap.pdf", 72000, 0.0, G.PERSON["dob"], G.signature_strokes(13, 1, 0.006))
        scan_to_jpg(w / "ap.pdf", d / "03_loan_application_form.jpg", seed=902)
    finally:
        G.PERSON.clear()
        G.PERSON.update(saved)
    _write_manifest(d, {"scenario": "RT7", "by": "Claude", "manipulated": True, "needs_registry": True,
                        "brief": "New applicant 'Rahul Verma' whose ID card reuses the photo image of applicant Mohammed Arif Khan (case_genuine) and whose application lists the same salary account number. Each document is internally clean.",
                        "targets": [{"doc": "04_", "fields": []}, {"doc": "03_", "fields": ["account_no"]}]})


def _searchable(scan_pdf: Path, source_pdf: Path, out_pdf: Path, stamp: str | None = None):
    """Add what scanner apps add: an invisible OCR text layer, and optionally a visible e-sign stamp
    in a blank margin (vector text + thin frame, no fill)."""
    src = fitz.open(str(source_pdf))
    doc = fitz.open(str(scan_pdf))
    for i, pg in enumerate(doc):
        if i < len(src):
            sx, sy = pg.rect.width / src[i].rect.width, pg.rect.height / src[i].rect.height
            for x0, y0, x1, y1, word, *_ in src[i].get_text("words"):
                pg.insert_text((x0 * sx, y1 * sy - 2), word, fontsize=max(4.0, (y1 - y0) * 0.75 * sy), render_mode=3)
        if stamp and i == 0:
            r = fitz.Rect(pg.rect.width - 250, pg.rect.height - 70, pg.rect.width - 40, pg.rect.height - 34)
            pg.draw_rect(r, color=(0.1, 0.5, 0.2), width=0.8)
            pg.insert_textbox(r + (4, 3, -4, -2), stamp, fontsize=7.5, color=(0.1, 0.45, 0.2))
    doc.save(str(out_pdf))
    doc.close()
    src.close()


def phone_forward(img: np.ndarray, seed: int, long_edge: int = 1280) -> np.ndarray:
    """A phone photo of the paper, sent over WhatsApp and forwarded once: perspective, uneven light,
    lens blur, downscale to 1280 px, JPEG ~75 twice."""
    rng = np.random.default_rng(seed)
    h, w = img.shape[:2]
    d = 0.02 * min(h, w)
    src = np.float32([[0, 0], [w, 0], [w, h], [0, h]])
    dst = src + rng.uniform(-d, d, (4, 2)).astype(np.float32)
    f = cv2.warpPerspective(img, cv2.getPerspectiveTransform(src, dst), (w, h), borderValue=(205, 200, 190))
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    light = 0.88 + 0.12 * (xx / w) * 0.6 + 0.12 * (1 - yy / h) * 0.4
    f = np.clip(f.astype(np.float32) * light[..., None] + rng.normal(0, 3.0, f.shape), 0, 255).astype(np.uint8)
    f = cv2.GaussianBlur(f, (0, 0), 0.9)
    s = long_edge / max(h, w)
    f = cv2.resize(f, (int(w * s), int(h * s)), interpolation=cv2.INTER_AREA)
    for q in (75, 72):
        ok, buf = cv2.imencode(".jpg", f, [cv2.IMWRITE_JPEG_QUALITY, q])
        f = cv2.imdecode(buf, cv2.IMREAD_COLOR)
    return f


def rt8():
    """Claude's scenario (round 3): the most common real edit. A scanned payslip PDF is opened in a PDF
    editor; a white box is drawn over Net Pay and a new number typed on top. The scanned image inside
    the file is untouched. The application declares the new figure."""
    d, w = fresh("RT8_scanned_pdf_editor")
    G.build_payslip(w / "ps.pdf", G.signature_strokes(3))
    scanned_pdf(w / "ps.pdf", w / "ps_scan.pdf", seed=1101)
    src = fitz.open(str(w / "ps.pdf"))
    r = next(x for x in src[0].search_for(G.fmt_inr(G.NET) if hasattr(G, "fmt_inr") else "68,500.00"))
    src.close()
    doc = fitz.open(str(w / "ps_scan.pdf"))
    pg = doc[0]
    box = fitz.Rect(r.x0 - 3, r.y0 - 1, r.x1 + 4, r.y1 + 1)
    pg.draw_rect(box, color=None, fill=(0.955, 0.955, 0.955), width=0)
    pg.insert_text((r.x0, r.y1 - 4), "88,500.00", fontsize=10.5, fontname="helv", color=(0.08, 0.08, 0.08))
    doc.save(str(d / "01_payslip_oct2026.pdf"))
    doc.close()
    build_statement2(w / "st.pdf", BASE_TXNS)
    scanned_pdf(w / "st.pdf", d / "02_bank_statement_sep_oct2026.pdf", seed=1102)
    G.build_application(w / "ap.pdf", 88500, G.EMI, P["dob"], G.signature_strokes(7, 2, 0.006))
    scan_to_jpg(w / "ap.pdf", d / "03_loan_application_form.jpg", seed=1103)
    _write_manifest(d, {"scenario": "RT8", "by": "Claude", "manipulated": True,
                        "brief": "Scanned payslip PDF edited in a PDF editor: grey-white box over Net Pay 68,500.00 and "
                                 "'88,500.00' typed on top as vector text. The scan image inside the file is untouched. "
                                 "Application declares 88,500.",
                        "targets": [{"doc": "01_", "fields": ["net_pay"]}]})


def g9():
    """Genuine control: searchable scans (invisible OCR layer, as CamScanner/Adobe Scan produce) and an
    e-sign stamp added digitally in a blank margin of the payslip."""
    d, w = fresh("G9_genuine_searchable_scan_esign")
    G.build_payslip(w / "ps.pdf", G.signature_strokes(3))
    scanned_pdf(w / "ps.pdf", w / "ps_scan.pdf", seed=1201)
    _searchable(w / "ps_scan.pdf", w / "ps.pdf", d / "01_payslip_oct2026.pdf",
                stamp="Digitally signed by HR Operations\nNovaAxis Payroll  Ref PAY-OCT-26")
    build_statement2(w / "st.pdf", BASE_TXNS)
    scanned_pdf(w / "st.pdf", w / "st_scan.pdf", seed=1202)
    _searchable(w / "st_scan.pdf", w / "st.pdf", d / "02_bank_statement_sep_oct2026.pdf")
    G.build_application(w / "ap.pdf", G.NET, G.EMI, P["dob"], G.signature_strokes(7, 2, 0.006))
    scan_to_jpg(w / "ap.pdf", d / "03_loan_application_form.jpg", seed=1203)
    _write_manifest(d, {"scenario": "G9", "by": "Claude (from Argon's round-3 MRC warning)", "manipulated": False,
                        "brief": "Genuine. Payslip and statement are searchable scans with an invisible OCR text layer; the "
                                 "payslip carries a digital e-sign stamp drawn in a blank margin."})


def g10():
    """Genuine control (Argon round 3): phone photos forwarded on WhatsApp, 1280 px, JPEG ~75 twice."""
    d, w = fresh("G10_genuine_whatsapp_photos")
    G.build_payslip(w / "ps.pdf", G.signature_strokes(3))
    cv2.imwrite(str(d / "01_payslip_oct2026.jpg"), phone_forward(G.render_pdf(w / "ps.pdf")[:, :, ::-1], seed=1301))
    G.build_letter(w / "lt.pdf", G.NET, P["doj"], G.signature_strokes(3, 1, 0.012))
    cv2.imwrite(str(d / "05_employment_letter.jpg"), phone_forward(G.render_pdf(w / "lt.pdf")[:, :, ::-1], seed=1302))
    build_statement2(w / "st.pdf", BASE_TXNS)
    shutil.copy(w / "st.pdf", d / "02_bank_statement_sep_oct2026.pdf")
    _write_manifest(d, {"scenario": "G10", "by": "Argon (round 3) / built by Claude", "manipulated": False,
                        "brief": "Genuine. Payslip and employment letter are phone photos forwarded on WhatsApp (perspective, "
                                 "uneven light, 1280 px long edge, JPEG 75 then 72). Statement is the bank's PDF."})


def g11():
    """Genuine control (Argon round 3): the genuine demo case submitted a second time under a new case ID."""
    d, w = fresh("G11_genuine_resubmission")
    for p in sorted((Path(__file__).resolve().parent / "cases" / "case_genuine").glob("0*")):
        shutil.copy(p, d / p.name)
    _write_manifest(d, {"scenario": "G11", "by": "Argon (round 3) / built by Claude", "manipulated": False,
                        "needs_registry": True,
                        "brief": "Genuine. The exact files of case_genuine, run again under a new case ID with cross-case "
                                 "memory on (a rehearsal re-run). Must not look like an identity ring."})


def rt9():
    """Argon round 4, attack C: the edit hides where an object-list parser does not look. The Oct salary
    credit on a scanned statement is covered by an Acrobat-style comment (FreeText annotation, white
    fill) showing a new figure. Annotations are not page content: only a pixel comparison sees it."""
    d, w = fresh("RT9_annotation_overlay")
    build_statement2(w / "st.pdf", BASE_TXNS)
    src = fitz.open(str(w / "st.pdf"))
    r = src[0].search_for("68,500.00")[-1]  # the October salary credit
    src.close()
    scanned_pdf(w / "st.pdf", w / "st_scan.pdf", seed=1401)
    doc = fitz.open(str(w / "st_scan.pdf"))
    pg = doc[0]
    a = pg.add_freetext_annot(fitz.Rect(r.x0 - 3, r.y0 - 1, r.x1 + 3, r.y1 + 1), "88,500.00", fontsize=9.5,
                              fontname="helv", text_color=(0.1, 0.1, 0.1), fill_color=(0.955, 0.955, 0.955), align=2)
    a.set_border(width=0)
    a.update()
    doc.save(str(d / "02_bank_statement_sep_oct2026.pdf"))
    doc.close()
    G.build_application(w / "ap.pdf", 88500, G.EMI, P["dob"], G.signature_strokes(7, 2, 0.006))
    scan_to_jpg(w / "ap.pdf", d / "03_loan_application_form.jpg", seed=1402)
    _write_manifest(d, {"scenario": "RT9", "by": "Argon (round 4) / built by Claude", "manipulated": True,
                        "brief": "October salary credit 68,500.00 on a scanned statement hidden under a FreeText comment "
                                 "annotation (white fill) that shows 88,500.00. The page content stream is untouched. "
                                 "Application declares 88,500.",
                        "targets": [{"doc": "02_", "fields": []}]})


def g12():
    """Genuine control (Argon round 4 FP risk): the applicant redacted their own PAN on a scanned payslip
    with a white box and 'XXXXXX821Q' typed on top, and added a 'Self-attested' comment."""
    d, w = fresh("G12_genuine_redacted_pan")
    G.build_payslip(w / "ps.pdf", G.signature_strokes(3))
    src = fitz.open(str(w / "ps.pdf"))
    r = src[0].search_for(P["pan"])[0]
    src.close()
    scanned_pdf(w / "ps.pdf", w / "ps_scan.pdf", seed=1501)
    doc = fitz.open(str(w / "ps_scan.pdf"))
    pg = doc[0]
    pg.draw_rect(fitz.Rect(r.x0 - 2, r.y0 - 1, r.x1 + 3, r.y1 + 1), color=None, fill=(1, 1, 1), width=0)
    pg.insert_text((r.x0, r.y1 - 3.5), "XXXXXX821Q", fontsize=10, fontname="helv", color=(0.1, 0.1, 0.1))
    a = pg.add_freetext_annot(fitz.Rect(pg.rect.width - 170, pg.rect.height - 60, pg.rect.width - 40, pg.rect.height - 40),
                              "Self-attested copy", fontsize=9, text_color=(0.1, 0.2, 0.6))
    a.update()
    doc.save(str(d / "01_payslip_oct2026.pdf"))
    doc.close()
    build_statement2(w / "st.pdf", BASE_TXNS)
    scanned_pdf(w / "st.pdf", d / "02_bank_statement_sep_oct2026.pdf", seed=1502)
    _write_manifest(d, {"scenario": "G12", "by": "Argon (round 4) / built by Claude", "manipulated": False,
                        "brief": "Genuine. Applicant masked their PAN on the scanned payslip (white box + 'XXXXXX821Q') and "
                                 "added a 'Self-attested copy' comment. Redaction must not be read as a replaced value."})


def rt10():
    """Argon's final attack on the parse-quality gate: smudge the balance cells of three small rows so the
    statement looks unparseable, hoping SAKSHI switches statement arithmetic off; then inflate the October
    salary credit without fixing the running balance. Born-digital statement, application declares 88,500."""
    d, w = fresh("RT10_garbage_decoy_balance")
    tx = [list(t) for t in BASE_TXNS]
    bal, bals = G.OPENING, []
    for t in tx:
        bal = round(bal - t[2] + t[3], 2)
        bals.append(bal)
    tx[12][3] = 88500.0  # credit edited, balance left at the genuine value
    over = list(bals)
    for i, junk in ((0, "1,0#,2?0.0O"), (3, "8B,4@I.OO"), (9, "~5,1?,9#.00")):
        over[i] = junk
    orig = G.inr
    G.inr = lambda x: x if isinstance(x, str) else orig(x)  # noqa: E731
    try:
        build_statement2(d / "02_bank_statement_sep_oct2026.pdf", [tuple(t) for t in tx], balance_override=over)
    finally:
        G.inr = orig
    G.build_application(w / "ap.pdf", 88500, G.EMI, P["dob"], G.signature_strokes(7, 2, 0.006))
    scan_to_jpg(w / "ap.pdf", d / "03_loan_application_form.jpg", seed=1601)
    _write_manifest(d, {"scenario": "RT10", "by": "Argon (final check) / built by Claude", "manipulated": True,
                        "brief": "Born-digital statement. Balance cells of three small rows smudged with garbage characters "
                                 "(decoy to make the parse look unreliable); October salary credit changed 68,500 -> 88,500 "
                                 "without fixing the running balance. Application declares 88,500.",
                        "targets": [{"doc": "02_", "fields": []}]})


def main():
    OUT.mkdir(exist_ok=True)
    for f in (rt1, rt2, rt3, rt4, rt5, rt6, g7, g8, rt7, rt8, g9, g10, g11, rt9, g12, rt10):
        f()
        print("built", f.__name__)
    shutil.rmtree(OUT / "_work", ignore_errors=True)


if __name__ == "__main__":
    if len(sys.argv) > 1:
        OUT.mkdir(exist_ok=True)
        for name in sys.argv[1:]:
            globals()[name]()
        shutil.rmtree(OUT / "_work", ignore_errors=True)
    else:
        main()
