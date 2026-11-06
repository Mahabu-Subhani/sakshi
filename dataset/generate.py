"""
Demo dataset generator for SAKSHI.

Builds two loan-application cases for one fictional applicant:
  case_genuine   - five consistent, untouched documents (control case)
  case_tampered  - the same five documents with planted manipulations

Every document is fictional, carries a visible SYNTHETIC SPECIMEN label and
uses invented institutions (Demo Cooperative Bank, Nimbus Analytics, Demo
National Identity Card). Nothing here imitates a real issuer's design.

Run:  python dataset/generate.py            (writes dataset/cases/...)
"""
from __future__ import annotations

import json
import math
import os
import random
import shutil
from dataclasses import dataclass
from pathlib import Path

import cv2
import pymupdf as fitz
import numpy as np
from PIL import Image, ImageDraw, ImageFont
from reportlab.lib.pagesizes import A4
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.pdfgen import canvas

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "cases"
DPI = 200
SCALE = DPI / 72.0
PAGE_W, PAGE_H = A4
SPECIMEN = "SYNTHETIC SPECIMEN - HACKATHON DEMO DATA - NOT A REAL DOCUMENT"
# Linux first (the dataset was generated there), then Windows and macOS. Liberation Sans is metric-compatible
# with Arial, so Arial is the faithful stand-in; the forger font only needs to differ from the document font.
FONT_DIRS = [Path("/usr/share/fonts/truetype"), Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts",
             Path("/Library/Fonts"), Path("/System/Library/Fonts/Supplemental")]
FONT_FILES = {
    "sans": ["liberation/LiberationSans-Regular.ttf", "dejavu/DejaVuSans.ttf", "arial.ttf", "Arial.ttf"],
    "sans_bold": ["liberation/LiberationSans-Bold.ttf", "dejavu/DejaVuSans-Bold.ttf", "arialbd.ttf", "Arial Bold.ttf"],
    "forger": ["freefont/FreeSans.ttf", "dejavu/DejaVuSans.ttf", "segoeui.ttf", "Verdana.ttf"],
}


def _font(name: str, size: int) -> ImageFont.FreeTypeFont:
    for f in FONT_FILES[name]:
        for d in FONT_DIRS:
            if (d / f).exists():
                return ImageFont.truetype(str(d / f), size)
    return ImageFont.load_default()


# ---------------------------------------------------------------------------
# Applicant master data (fictional)
# ---------------------------------------------------------------------------
PERSON = dict(
    name="Mohammed Arif Khan",
    bank_name="MOHD ARIF KHAN",  # benign transliteration decoy on the statement
    dob="14-03-1996",
    pan="AFKPK4821Q",
    mobile="9000012345",
    address="Flat 302, Lakeview Residency, HSR Layout, Bengaluru 560102",
    employer="Nimbus Analytics Pvt. Ltd.",
    emp_id="NA-10457",
    designation="Data Analyst",
    doj="01-07-2021",
    account="50100234567812",
    ifsc="DCBL0001234",
    id_no="DNI 4821 7730 1956",
)

EARNINGS = [("Basic Salary", 40000), ("House Rent Allowance", 16000), ("Special Allowance", 17800),
            ("Conveyance Allowance", 1600), ("Medical Allowance", 1250)]
DEDUCTIONS = [("Provident Fund", 4800), ("Professional Tax", 200), ("Income Tax (TDS)", 3150)]
GROSS = sum(v for _, v in EARNINGS)          # 76,650
TOTAL_DED = sum(v for _, v in DEDUCTIONS)    # 8,150
NET = GROSS - TOTAL_DED                       # 68,500
FORGED_NET = 86500
EMI = 24500
FORGED_EMI = 14500

OPENING = 82340.50
TXNS = [
    ("02-09-2026", "UPI/SWIGGY/BLR/882131", 640.00, 0.0),
    ("05-09-2026", "EMI DEMO HOME FIN LN88213", 24500.00, 0.0),
    ("08-09-2026", "NEFT RENT LAKEVIEW ASSOC", 18000.00, 0.0),
    ("14-09-2026", "UPI/BESCOM ELECTRICITY", 1320.00, 0.0),
    ("21-09-2026", "ATM WDL HSR LAYOUT", 5000.00, 0.0),
    ("30-09-2026", "SALARY NIMBUS ANALYTICS SEP", 0.0, 68500.00),
    ("03-10-2026", "UPI/BIGBASKET/772910", 2415.00, 0.0),
    ("05-10-2026", "EMI DEMO HOME FIN LN88213", 24500.00, 0.0),
    ("08-10-2026", "NEFT RENT LAKEVIEW ASSOC", 18000.00, 0.0),
    ("12-10-2026", "UPI/JIO RECHARGE", 299.00, 0.0),
    ("19-10-2026", "IMPS FROM AYESHA KHAN", 0.0, 3000.00),
    ("24-10-2026", "UPI/BESCOM ELECTRICITY", 1180.00, 0.0),
    ("31-10-2026", "SALARY NIMBUS ANALYTICS OCT", 0.0, 68500.00),
]
TAMPER_ROW = 7  # 05-10-2026 EMI row (0-based)
DONOR_ROW = 11  # 24-10-2026 row, its debit "1,180.00" donates the "1" glyph


def inr(x: float, decimals: bool = True) -> str:
    """Indian digit grouping: 1,24,350.75"""
    neg = x < 0
    x = abs(x)
    whole = int(round(x * 100)) // 100
    frac = int(round(x * 100)) % 100
    s = str(whole)
    if len(s) > 3:
        head, tail = s[:-3], s[-3:]
        parts = []
        while len(head) > 2:
            parts.insert(0, head[-2:])
            head = head[:-2]
        if head:
            parts.insert(0, head)
        s = ",".join(parts + [tail])
    out = f"{s}.{frac:02d}" if decimals else s
    return ("-" if neg else "") + out


ONES = ["", "One", "Two", "Three", "Four", "Five", "Six", "Seven", "Eight", "Nine", "Ten", "Eleven", "Twelve",
        "Thirteen", "Fourteen", "Fifteen", "Sixteen", "Seventeen", "Eighteen", "Nineteen"]
TENS = ["", "", "Twenty", "Thirty", "Forty", "Fifty", "Sixty", "Seventy", "Eighty", "Ninety"]


def words_indian(n: int) -> str:
    def two(k):
        return ONES[k] if k < 20 else (TENS[k // 10] + (" " + ONES[k % 10] if k % 10 else ""))

    def three(k):
        h, r = divmod(k, 100)
        return ((ONES[h] + " Hundred" + (" " if r else "")) if h else "") + (two(r) if r else "")

    parts = []
    crore, n = divmod(n, 10_000_000)
    lakh, n = divmod(n, 100_000)
    thousand, n = divmod(n, 1000)
    if crore:
        parts.append(two(crore) + " Crore")
    if lakh:
        parts.append(two(lakh) + " Lakh")
    if thousand:
        parts.append(two(thousand) + " Thousand")
    if n:
        parts.append(three(n))
    return " ".join(parts) if parts else "Zero"


# ---------------------------------------------------------------------------
# Signatures: procedural strokes so no real signature is ever used
# ---------------------------------------------------------------------------
def signature_strokes(seed: int, variant: int = 0, jitter: float = 0.0):
    """Base shape from `seed`; `variant` adds natural wet-signature variation."""
    rng = random.Random(seed)
    strokes = []
    x = 0.0
    for _ in range(3):
        pts = []
        n = rng.randint(5, 8)
        for i in range(n):
            pts.append((x + i * rng.uniform(0.04, 0.07), rng.uniform(0.05, 0.35)))
        x = pts[-1][0] + rng.uniform(0.02, 0.05)
        strokes.append(pts)
    # underline flourish
    strokes.append([(0.0, 0.02), (x * 0.5, -0.03), (x * 0.95, 0.04)])
    if jitter:
        vr = random.Random(seed * 1000 + variant)
        new = []
        for s in strokes:
            dx, dy, sc = vr.uniform(-1, 1) * jitter, vr.uniform(-1, 1) * jitter, 1 + vr.uniform(-1, 1) * jitter
            new.append([(px * sc + dx + vr.gauss(0, jitter * 0.6), py * sc + dy + vr.gauss(0, jitter * 0.6))
                        for px, py in s])
        strokes = new
    return strokes


def _smooth(pts, k=8):
    """Catmull-Rom sample a polyline."""
    if len(pts) < 3:
        return pts
    out = []
    p = [pts[0]] + pts + [pts[-1]]
    for i in range(1, len(p) - 2):
        p0, p1, p2, p3 = p[i - 1], p[i], p[i + 1], p[i + 2]
        for t in np.linspace(0, 1, k, endpoint=False):
            t2, t3 = t * t, t * t * t
            out.append(tuple(0.5 * ((2 * p1[j]) + (-p0[j] + p2[j]) * t + (2 * p0[j] - 5 * p1[j] + 4 * p2[j] - p3[j]) * t2
                                    + (-p0[j] + 3 * p1[j] - 3 * p2[j] + p3[j]) * t3) for j in range(2)))
    out.append(pts[-1])
    return out


def draw_signature_rl(c: canvas.Canvas, strokes, x: float, y: float, width: float):
    c.saveState()
    c.setStrokeColorRGB(0.08, 0.16, 0.62)
    c.setLineWidth(1.4)
    c.setLineCap(1)
    c.setLineJoin(1)
    for s in strokes:
        sp = _smooth(s)
        path = c.beginPath()
        path.moveTo(x + sp[0][0] * width, y + sp[0][1] * width)
        for px, py in sp[1:]:
            path.lineTo(x + px * width, y + py * width)
        c.drawPath(path, stroke=1, fill=0)
    c.restoreState()


# ---------------------------------------------------------------------------
# PDF builders (reportlab). Each returns metadata with value boxes in points.
# ---------------------------------------------------------------------------
@dataclass
class Box:
    x0: float
    y_base: float  # baseline, reportlab coordinates (origin bottom-left)
    x1: float
    size: float

    def to_px_rect(self):
        """Pixel rect (top-left origin) at DPI for the glyph run."""
        top = (PAGE_H - (self.y_base + self.size * 0.78)) * SCALE
        bot = (PAGE_H - (self.y_base - self.size * 0.22)) * SCALE
        return (self.x0 * SCALE, top, self.x1 * SCALE, bot)


def _specimen(c: canvas.Canvas):
    c.saveState()
    c.setFillColorRGB(0.75, 0.1, 0.1)
    c.setFont("Helvetica-Bold", 7)
    c.drawCentredString(PAGE_W / 2, PAGE_H - 18, SPECIMEN)
    c.drawCentredString(PAGE_W / 2, 14, SPECIMEN)
    c.restoreState()


def build_payslip(path: Path, signature, month_label: str = "OCTOBER 2026", pay_date: str = "31-10-2026",
                  earnings=None, deductions=None) -> dict:
    earnings = earnings or EARNINGS
    deductions = deductions or DEDUCTIONS
    gross, total_ded = sum(v for _, v in earnings), sum(v for _, v in deductions)
    net = gross - total_ded
    c = canvas.Canvas(str(path), pagesize=A4)
    c.setTitle("Payslip October 2026")
    c.setAuthor("Nimbus Payroll Engine")
    c.setProducer("Nimbus Payroll Engine 4.2 (fictional)")
    c.setCreator("Nimbus Payroll Engine 4.2 (fictional)")
    _specimen(c)
    boxes = {}
    c.setFillColorRGB(0.06, 0.2, 0.38)
    c.rect(40, PAGE_H - 95, PAGE_W - 80, 52, fill=1, stroke=0)
    c.setFillColorRGB(1, 1, 1)
    c.setFont("Helvetica-Bold", 17)
    c.drawString(55, PAGE_H - 68, "NIMBUS ANALYTICS PVT. LTD.")
    c.setFont("Helvetica", 9)
    c.drawString(55, PAGE_H - 84, "4th Floor, Orion Tech Park, Outer Ring Road, Bengaluru 560103 (fictional)")
    c.setFillColorRGB(0, 0, 0)
    c.setFont("Helvetica-Bold", 13)
    c.drawCentredString(PAGE_W / 2, PAGE_H - 122, f"PAYSLIP FOR THE MONTH OF {month_label}")

    y = PAGE_H - 160
    c.setFont("Helvetica", 10)
    left = [("Employee Name", PERSON["name"]), ("Employee ID", PERSON["emp_id"]),
            ("Designation", PERSON["designation"]), ("Date of Joining", PERSON["doj"])]
    right = [("PAN", PERSON["pan"]), ("Bank A/c No", PERSON["account"]),
             ("Pay Date", pay_date), ("Days Paid", "31")]
    for i, ((l1, v1), (l2, v2)) in enumerate(zip(left, right)):
        yy = y - i * 18
        c.setFont("Helvetica", 10)
        c.drawString(55, yy, f"{l1}:")
        c.drawString(160, yy, v1)
        c.drawString(320, yy, f"{l2}:")
        c.drawString(410, yy, v2)
    y = y - 4 * 18 - 20

    # earnings / deductions table
    c.setLineWidth(0.6)
    top = y
    c.rect(50, top - 18, PAGE_W - 100, 18, fill=0)
    c.setFont("Helvetica-Bold", 10)
    c.drawString(58, top - 13, "Earnings")
    c.drawRightString(285, top - 13, "Amount (Rs.)")
    c.drawString(305, top - 13, "Deductions")
    c.drawRightString(PAGE_W - 58, top - 13, "Amount (Rs.)")
    c.setFont("Helvetica", 10)
    rows = max(len(earnings), len(deductions))
    for i in range(rows):
        yy = top - 18 - (i + 1) * 18 + 5
        if i < len(earnings):
            c.drawString(58, yy, earnings[i][0])
            c.drawRightString(285, yy, inr(earnings[i][1]))
        if i < len(deductions):
            c.drawString(305, yy, deductions[i][0])
            c.drawRightString(PAGE_W - 58, yy, inr(deductions[i][1]))
    bottom = top - 18 - rows * 18 - 6
    c.rect(50, bottom, PAGE_W - 100, top - 18 - bottom, fill=0)
    c.line(295, top, 295, bottom)
    yy = bottom - 16
    c.setFont("Helvetica-Bold", 10)
    c.drawString(58, yy, "Gross Earnings")
    c.drawRightString(285, yy, inr(gross))
    c.drawString(305, yy, "Total Deductions")
    c.drawRightString(PAGE_W - 58, yy, inr(total_ded))

    yy -= 36
    c.setFont("Helvetica-Bold", 12)
    c.drawString(58, yy, "Net Pay (Rs.):")
    net_txt = inr(net)
    c.drawString(165, yy, net_txt)
    boxes["net_pay"] = Box(165, yy, 165 + stringWidth(net_txt, "Helvetica-Bold", 12), 12)
    yy -= 20
    c.setFont("Helvetica", 10)
    c.drawString(58, yy, f"Amount in words: Rupees {words_indian(int(net))} Only")

    yy -= 70
    draw_signature_rl(c, signature, PAGE_W - 200, yy + 14, 120)
    c.setFont("Helvetica", 10)
    c.drawString(PAGE_W - 200, yy, "Authorised Signatory")
    c.setFont("Helvetica", 8)
    c.drawString(55, 60, "This is a system generated payslip. Nimbus Analytics is a fictional company.")
    c.showPage()
    c.save()
    return {"boxes": {k: vars(v) for k, v in boxes.items()}}


def build_statement(path: Path, txns, signature_unused=None) -> dict:
    c = canvas.Canvas(str(path), pagesize=A4)
    c.setTitle("Statement of Account")
    c.setProducer("Demo Core Banking 9 (fictional)")
    _specimen(c)
    boxes = {}
    c.setFont("Helvetica-Bold", 16)
    c.setFillColorRGB(0.45, 0.07, 0.07)
    c.drawString(45, PAGE_H - 60, "DEMO COOPERATIVE BANK LTD.")
    c.setFillColorRGB(0, 0, 0)
    c.setFont("Helvetica", 9)
    c.drawString(45, PAGE_H - 74, "HSR Layout Branch, Bengaluru 560102 (fictional bank)")
    c.setFont("Helvetica-Bold", 12)
    c.drawString(45, PAGE_H - 100, "STATEMENT OF ACCOUNT")
    c.setFont("Helvetica", 10)
    info = [("Account Holder", PERSON["bank_name"]), ("Account No", PERSON["account"]),
            ("IFSC", PERSON["ifsc"]), ("Statement Period", "01-09-2026 to 31-10-2026")]
    for i, (k, v) in enumerate(info):
        c.drawString(45, PAGE_H - 122 - i * 16, f"{k}:")
        c.drawString(150, PAGE_H - 122 - i * 16, v)

    cols = {"date": 45, "desc": 120, "debit": 390, "credit": 470, "balance": 552}
    y = PAGE_H - 210
    c.setLineWidth(0.6)
    c.line(40, y + 14, PAGE_W - 38, y + 14)
    c.setFont("Helvetica-Bold", 10)
    c.drawString(cols["date"], y, "Date")
    c.drawString(cols["desc"], y, "Description")
    c.drawRightString(cols["debit"], y, "Debit")
    c.drawRightString(cols["credit"], y, "Credit")
    c.drawRightString(cols["balance"], y, "Balance")
    c.line(40, y - 6, PAGE_W - 38, y - 6)
    c.setFont("Helvetica", 10)
    y -= 24
    c.drawString(cols["date"], y, "01-09-2026")
    c.drawString(cols["desc"], y, "OPENING BALANCE")
    c.drawRightString(cols["balance"], y, inr(OPENING))
    bal = OPENING
    tot_dr = tot_cr = 0.0
    for i, (d, desc, dr, cr) in enumerate(txns):
        y -= 22
        bal = round(bal - dr + cr, 2)
        tot_dr += dr
        tot_cr += cr
        c.drawString(cols["date"], y, d)
        c.drawString(cols["desc"], y, desc)
        if dr:
            t = inr(dr)
            c.drawRightString(cols["debit"], y, t)
            boxes[f"row{i}_debit"] = vars(Box(cols["debit"] - stringWidth(t, "Helvetica", 10), y, cols["debit"], 10))
        if cr:
            t = inr(cr)
            c.drawRightString(cols["credit"], y, t)
        c.drawRightString(cols["balance"], y, inr(bal))
    c.line(40, y - 10, PAGE_W - 38, y - 10)
    y -= 34
    c.setFont("Helvetica-Bold", 10)
    summary = [("Opening Balance", OPENING), ("Total Debits", tot_dr), ("Total Credits", tot_cr), ("Closing Balance", bal)]
    for i, (k, v) in enumerate(summary):
        c.drawString(300, y - i * 16, f"{k}:")
        c.drawRightString(cols["balance"], y - i * 16, inr(v))
    c.setFont("Helvetica", 8)
    c.drawString(45, 60, "Computer generated statement. Demo Cooperative Bank is fictional.")
    c.showPage()
    c.save()
    return {"boxes": boxes, "closing": bal}


def build_application(path: Path, income: float, emi: float, dob: str, signature) -> dict:
    c = canvas.Canvas(str(path), pagesize=A4)
    _specimen(c)
    boxes = {}
    c.setFont("Helvetica-Bold", 15)
    c.drawCentredString(PAGE_W / 2, PAGE_H - 60, "DEMO COOPERATIVE BANK LTD.")
    c.setFont("Helvetica-Bold", 12)
    c.drawCentredString(PAGE_W / 2, PAGE_H - 80, "HOME LOAN APPLICATION FORM")
    c.setFont("Helvetica", 9)
    c.drawCentredString(PAGE_W / 2, PAGE_H - 94, "Application Ref: HL/BLR/2026/004417")
    fields = [
        ("Applicant Name", PERSON["name"]),
        ("Date of Birth", dob),
        ("PAN", PERSON["pan"]),
        ("Mobile", PERSON["mobile"]),
        ("Residential Address", PERSON["address"]),
        ("Employer", PERSON["employer"]),
        ("Designation", PERSON["designation"]),
        ("Date of Joining", PERSON["doj"]),
        ("Net Monthly Income (Rs.)", inr(income)),
        ("Existing Monthly EMIs (Rs.)", inr(emi)),
        ("Salary Account No", PERSON["account"]),
        ("IFSC", PERSON["ifsc"]),
        ("Loan Amount Requested (Rs.)", inr(2500000)),
        ("Loan Tenure (months)", "240"),
        ("Date of Application", "02-11-2026"),
        ("Place", "Bengaluru"),
    ]
    y = PAGE_H - 140
    vx = 230
    c.setLineWidth(0.5)
    for k, v in fields:
        c.setFont("Helvetica", 10)
        c.drawString(55, y, f"{k}:")
        c.drawString(vx, y, v)
        c.line(vx - 4, y - 4, PAGE_W - 55, y - 4)
        key = k.split(" (")[0].lower().replace(" ", "_")
        boxes[key] = vars(Box(vx, y, vx + stringWidth(v, "Helvetica", 10), 10))
        y -= 26
    y -= 10
    c.setFont("Helvetica-Bold", 10)
    c.drawString(55, y, "Declaration")
    c.setFont("Helvetica", 9)
    decl = ["I declare that the information furnished above is true and correct to the best of my knowledge",
            "and that I have not withheld any material information. I authorise the bank to verify the same."]
    for i, line in enumerate(decl):
        c.drawString(55, y - 14 - i * 12, line)
    y -= 90
    draw_signature_rl(c, signature, 60, y + 14, 110)
    c.setFont("Helvetica", 10)
    c.drawString(60, y, "Signature of Applicant")
    c.showPage()
    c.save()
    return {"boxes": boxes}


def build_letter(path: Path, salary: float, since: str, signature, salary_line: str | None = None) -> dict:
    c = canvas.Canvas(str(path), pagesize=A4)
    _specimen(c)
    c.setFillColorRGB(0.06, 0.2, 0.38)
    c.rect(40, PAGE_H - 95, PAGE_W - 80, 52, fill=1, stroke=0)
    c.setFillColorRGB(1, 1, 1)
    c.setFont("Helvetica-Bold", 17)
    c.drawString(55, PAGE_H - 68, "NIMBUS ANALYTICS PVT. LTD.")
    c.setFont("Helvetica", 9)
    c.drawString(55, PAGE_H - 84, "4th Floor, Orion Tech Park, Outer Ring Road, Bengaluru 560103 (fictional)")
    c.setFillColorRGB(0, 0, 0)
    c.setFont("Helvetica", 11)
    c.drawString(55, PAGE_H - 130, "Ref: HR/EMP/2026/1187")
    c.drawRightString(PAGE_W - 55, PAGE_H - 130, "Date: 03-11-2026")
    c.setFont("Helvetica-Bold", 12)
    c.drawCentredString(PAGE_W / 2, PAGE_H - 175, "TO WHOM IT MAY CONCERN")
    c.setFont("Helvetica", 11)
    body = [
        f"This is to certify that Mr. {PERSON['name']} (Employee ID {PERSON['emp_id']}) has been",
        f"working with {PERSON['employer']} since {since} as {PERSON['designation']}.",
        "",
        salary_line or f"His current net monthly salary is Rs. {inr(salary)}.",
        "",
        "This letter is issued at the request of the employee for the purpose of a home loan",
        "application and carries no other liability on the part of the company.",
    ]
    y = PAGE_H - 215
    for line in body:
        c.drawString(55, y, line)
        y -= 18
    y -= 60
    c.drawString(55, y + 40, "For Nimbus Analytics Pvt. Ltd.")
    draw_signature_rl(c, signature, 55, y + 4, 120)
    c.drawString(55, y - 10, "Authorised Signatory")
    c.drawString(55, y - 26, "Human Resources")
    c.showPage()
    c.save()
    return {}


# ---------------------------------------------------------------------------
# Image helpers: render, simulate scanning, tamper
# ---------------------------------------------------------------------------
def render_pdf(path: Path) -> np.ndarray:
    doc = fitz.open(str(path))
    pix = doc[0].get_pixmap(dpi=DPI)
    img = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.h, pix.w, pix.n)[:, :, :3].copy()
    doc.close()
    return img


def simulate_scan(img: np.ndarray, seed: int, angle: float = 0.3, noise: float = 5.0):
    """Paper tint, slight skew, optical blur, sensor noise. Returns image and affine matrix."""
    rng = np.random.default_rng(seed)
    h, w = img.shape[:2]
    f = img.astype(np.float32) * (243.0 / 255.0) + 2.0
    M = cv2.getRotationMatrix2D((w / 2, h / 2), angle, 1.0)
    f = cv2.warpAffine(f, M, (w, h), flags=cv2.INTER_LINEAR, borderValue=(245, 245, 245))
    f = cv2.GaussianBlur(f, (0, 0), 0.65)
    lum = rng.normal(0, noise, (h, w, 1)).astype(np.float32)
    chroma = rng.normal(0, noise * 0.35, (h, w, 3)).astype(np.float32)
    f = f + lum + chroma
    return np.clip(f, 0, 255).astype(np.uint8), M


def map_rect(rect, M):
    x0, y0, x1, y1 = rect
    pts = np.array([[x0, y0, 1], [x1, y0, 1], [x0, y1, 1], [x1, y1, 1]], dtype=np.float64)
    out = pts @ M.T
    return (float(out[:, 0].min()), float(out[:, 1].min()), float(out[:, 0].max()), float(out[:, 1].max()))


def save_jpeg(img: np.ndarray, path: Path, q: int):
    Image.fromarray(img).save(str(path), quality=q, subsampling=0)


def load(path: Path) -> np.ndarray:
    return np.array(Image.open(str(path)).convert("RGB"))


def image_to_pdf(img_path: Path, pdf_path: Path):
    """Wrap a scan into an image-only PDF, like a real scanner would."""
    doc = fitz.open()
    im = Image.open(str(img_path))
    w_pt, h_pt = im.width / SCALE, im.height / SCALE
    page = doc.new_page(width=w_pt, height=h_pt)
    page.insert_image(page.rect, filename=str(img_path))
    doc.set_metadata({"producer": "Demo ScanStation 3 (fictional)", "creator": "Demo ScanStation 3"})
    doc.save(str(pdf_path))
    doc.close()


# ---------------------------------------------------------------------------
# ID card (drawn directly as an image)
# ---------------------------------------------------------------------------
def avatar(w: int, h: int, seed: int) -> np.ndarray:
    """Abstract silhouette placeholder: never a real face."""
    rng = random.Random(seed)
    im = Image.new("RGB", (w, h), (rng.randint(150, 200), rng.randint(170, 210), rng.randint(200, 235)))
    d = ImageDraw.Draw(im)
    for i in range(h):
        t = i / h
        d.line([(0, i), (w, i)], fill=(int(180 - 40 * t), int(195 - 30 * t), int(225 - 20 * t)))
    skin = (rng.randint(150, 200), rng.randint(110, 150), rng.randint(80, 110))
    d.ellipse([w * 0.28, h * 0.12, w * 0.72, h * 0.55], fill=skin)
    d.ellipse([w * 0.1, h * 0.58, w * 0.9, h * 1.25], fill=(rng.randint(30, 80), rng.randint(40, 90), rng.randint(60, 120)))
    return np.array(im)


def build_id_card(seed: int) -> tuple[np.ndarray, dict]:
    W, H = 1300, 820
    im = Image.new("RGB", (W, H), (248, 246, 240))
    d = ImageDraw.Draw(im)
    d.rectangle([0, 0, W, 120], fill=(20, 70, 110))
    d.text((40, 22), "DEMO NATIONAL IDENTITY CARD", font=_font("sans_bold", 46), fill=(255, 255, 255))
    d.text((40, 80), "SYNTHETIC SPECIMEN - NOT A REAL DOCUMENT", font=_font("sans", 24), fill=(255, 210, 210))
    photo_box = (60, 170, 360, 560)
    im.paste(Image.fromarray(avatar(photo_box[2] - photo_box[0], photo_box[3] - photo_box[1], 11)), photo_box[:2])
    d.rectangle(photo_box, outline=(60, 60, 60), width=3)
    f_lab, f_val = _font("sans", 26), _font("sans_bold", 32)
    rows = [("Name", PERSON["name"].upper()), ("Date of Birth", PERSON["dob"]), ("ID No", PERSON["id_no"]),
            ("Issued", "12-01-2022"), ("Valid Till", "11-01-2032")]
    y = 175
    for k, v in rows:
        d.text((410, y), k, font=f_lab, fill=(90, 90, 90))
        d.text((410, y + 30), v, font=f_val, fill=(15, 15, 15))
        y += 78
    d.text((60, 600), "Address", font=f_lab, fill=(90, 90, 90))
    d.text((60, 634), "Flat 302, Lakeview Residency, HSR Layout,", font=_font("sans", 30), fill=(15, 15, 15))
    d.text((60, 672), "Bengaluru 560102", font=_font("sans", 30), fill=(15, 15, 15))
    return np.array(im), {"photo_box": photo_box}


# ---------------------------------------------------------------------------
# Tamper operations
# ---------------------------------------------------------------------------
def tamper_payslip(src: Path, dst: Path, box: dict) -> dict:
    """White-box overlay + new value in a different font, saved as an incremental update."""
    shutil.copy(src, dst)
    doc = fitz.open(str(dst))
    page = doc[0]
    b = Box(**box)
    x0, x1 = b.x0, b.x1
    top = PAGE_H - (b.y_base + b.size * 0.95)
    bot = PAGE_H - (b.y_base - b.size * 0.3)
    rect = fitz.Rect(x0 - 1.5, top, x1 + 2.0, bot)
    page.draw_rect(rect, color=None, fill=(1, 1, 1), overlay=True)
    page.insert_text(fitz.Point(x0, PAGE_H - b.y_base), inr(FORGED_NET), fontname="tiro", fontsize=12.6,
                     color=(0, 0, 0), overlay=True)
    meta = doc.metadata
    meta["modDate"] = "D:20261102221405+05'30'"
    doc.set_metadata(meta)
    doc.saveIncr()
    doc.close()
    return {"rect_pt": [rect.x0, rect.y0, rect.x1, rect.y1]}


def tamper_statement_scan(img: np.ndarray, M, boxes: dict) -> tuple[np.ndarray, dict]:
    """Copy-move: hide the '2' of 24,500.00 with nearby blank paper, paste a '1' from another row."""
    out = img.copy()
    t = Box(**boxes[f"row{TAMPER_ROW}_debit"])
    donor = Box(**boxes[f"row{DONOR_ROW}_debit"])
    digit_w = stringWidth("2", "Helvetica", 10)
    tgt = map_rect(Box(t.x0, t.y_base, t.x0 + digit_w, 10).to_px_rect(), M)
    src = map_rect(Box(donor.x0, donor.y_base, donor.x0 + digit_w, 10).to_px_rect(), M)
    pad = 3
    tx0, ty0 = int(round(tgt[0])) - pad, int(round(tgt[1])) - pad
    sx0, sy0 = int(round(src[0])) - pad, int(round(src[1])) - pad
    w = int(round(tgt[2] - tgt[0])) + pad  # no right pad: the donor's next char is a comma
    h = int(round(tgt[3] - tgt[1])) + 2 * pad
    # the '1' glyph (with its surrounding paper) from the donor row, same column and advance width,
    # pasted over the '2'. Tabular digits share one advance width, so the patch covers the '2' fully.
    out[ty0:ty0 + h, tx0:tx0 + w] = img[sy0:sy0 + h, sx0:sx0 + w]
    return out, {"target_px": [tx0, ty0, tx0 + w, ty0 + h], "donor_px": [sx0, sy0, sx0 + w, sy0 + h]}


def tamper_application_scan(img: np.ndarray, M, boxes: dict) -> tuple[np.ndarray, dict]:
    """Digital white-out over the EMI value, retyped in another font, size and baseline."""
    out = img.copy()
    b = Box(**boxes["existing_monthly_emis"])
    r = map_rect(b.to_px_rect(), M)
    x0, y0, x1, y1 = int(r[0]) - 3, int(r[1]) - 3, int(r[2]) + 6, int(r[3]) + 3
    bg = np.median(img[y0 - 12:y0 - 4, x0:x1].reshape(-1, 3), axis=0).astype(np.uint8)
    out[y0:y1, x0:x1] = bg  # perfectly flat fill: no sensor noise
    pil = Image.fromarray(out)
    d = ImageDraw.Draw(pil)
    size = int(round(10 * SCALE * 1.2))  # forger eyeballs the font size
    d.text((x0 + 9, y0 + 6), inr(FORGED_EMI), font=_font("forger", size), fill=(38, 38, 42))
    return np.array(pil), {"overwrite_px": [x0, y0, x1, y1]}


def splice_id_photo(img: np.ndarray, photo_box) -> tuple[np.ndarray, dict]:
    x0, y0, x1, y1 = photo_box
    w, h = x1 - x0 - 6, y1 - y0 - 6
    other = avatar(w, h, 97).astype(np.float32)
    other = cv2.GaussianBlur(other, (0, 0), 1.2)
    other = np.clip(other * (243 / 255) + 2, 0, 255).astype(np.uint8)
    # different compression history: heavy JPEG on the donor before pasting
    ok, enc = cv2.imencode(".jpg", other[:, :, ::-1], [cv2.IMWRITE_JPEG_QUALITY, 55])
    other = cv2.imdecode(enc, cv2.IMREAD_COLOR)[:, :, ::-1]
    out = img.copy()
    out[y0 + 3:y0 + 3 + h, x0 + 3:x0 + 3 + w] = other
    return out, {"splice_px": [x0 + 3, y0 + 3, x0 + 3 + w, y0 + 3 + h]}


# ---------------------------------------------------------------------------
# Case assembly
# ---------------------------------------------------------------------------
def build_case(name: str, tampered: bool) -> dict:
    case_dir = OUT / name
    work = OUT / "_work" / name
    for p in (case_dir, work):
        if p.exists():
            shutil.rmtree(p)
        p.mkdir(parents=True)
    manifest = {"case": name, "tampered": tampered, "documents": {}, "planted": [], "benign_decoys": []}
    hr_sig = signature_strokes(seed=3)
    hr_sig_wet = signature_strokes(seed=3, variant=1, jitter=0.012)
    app_sig = signature_strokes(seed=7, variant=2, jitter=0.006)

    # 1. Payslip (born-digital PDF)
    slip_raw = work / "payslip_raw.pdf"
    meta = build_payslip(slip_raw, hr_sig)
    slip_clean = work / "payslip_clean.pdf"
    d = fitz.open(str(slip_raw))  # pin the issue timestamp to the pay date
    md = d.metadata
    md["creationDate"] = md["modDate"] = "D:20261031183000+05'30'"
    d.set_metadata(md)
    d.save(str(slip_clean), garbage=0)
    d.close()
    slip = case_dir / "01_payslip_oct2026.pdf"
    if tampered:
        info = tamper_payslip(slip_clean, slip, meta["boxes"]["net_pay"])
        manifest["planted"].append({
            "doc": slip.name, "field": "net_pay", "type": "white-box overlay + retyped value in different font",
            "original": inr(NET), "shown": inr(FORGED_NET), "rect_pt": info["rect_pt"],
            "expected_detections": ["occluded_text", "font_mix", "arithmetic_break", "amount_words_mismatch",
                                    "cross_doc_value_mismatch", "incremental_update"]})
    else:
        shutil.copy(slip_clean, slip)
    manifest["documents"][slip.name] = "salary_slip / born-digital PDF"

    # 2. Bank statement (scanned, image-only PDF)
    st_pdf = work / "statement_clean.pdf"
    smeta = build_statement(st_pdf, TXNS)
    st_img, M = simulate_scan(render_pdf(st_pdf), seed=21, angle=0.28)
    st_jpg = work / "statement_scan.jpg"
    save_jpeg(st_img, st_jpg, 90)
    if tampered:
        st_img = load(st_jpg)
        st_img, info = tamper_statement_scan(st_img, M, smeta["boxes"])
        save_jpeg(st_img, st_jpg, 92)
        manifest["planted"].append({
            "doc": "02_bank_statement_sep_oct2026.pdf", "field": "row 05-10-2026 debit",
            "type": "copy-move digit replacement (24,500.00 -> 14,500.00), balance column left unchanged",
            "original": inr(EMI), "shown": inr(FORGED_EMI), **info,
            "expected_detections": ["copy_move", "balance_chain_break", "statement_totals_mismatch",
                                    "recurring_amount_mismatch"]})
    st = case_dir / "02_bank_statement_sep_oct2026.pdf"
    image_to_pdf(st_jpg, st)
    manifest["documents"][st.name] = "bank_statement / scanned image-only PDF"
    manifest["benign_decoys"].append({"doc": st.name, "what": "account holder written 'MOHD ARIF KHAN'",
                                      "expected": "name variant explained as transliteration, not escalated"})

    # 3. Application form (scanned JPG)
    ap_pdf = work / "application_clean.pdf"
    amj = build_application(ap_pdf, FORGED_NET if tampered else NET, EMI,
                            "14-08-1996" if tampered else PERSON["dob"], app_sig)
    ap_img, M = simulate_scan(render_pdf(ap_pdf), seed=33, angle=-0.22)
    ap = case_dir / "03_loan_application_form.jpg"
    if tampered:
        save_jpeg(ap_img, work / "application_scan.jpg", 90)
        ap_img = load(work / "application_scan.jpg")
        ap_img, info = tamper_application_scan(ap_img, M, amj["boxes"])
        manifest["planted"].append({
            "doc": ap.name, "field": "existing_monthly_emis", "type": "digital white-out + retyped value (font/size/baseline differ)",
            "original": inr(EMI), "shown": inr(FORGED_EMI), **info,
            "expected_detections": ["noise_inconsistency", "glyph_outlier", "layout_rhythm_break",
                                    "cross_doc_value_mismatch"]})
        manifest["planted"].append({
            "doc": ap.name, "field": "net_monthly_income", "type": "false declaration (claim, no visual edit)",
            "declared": inr(FORGED_NET), "evidence": inr(NET), "expected_detections": ["claim_vs_evidence"]})
        manifest["planted"].append({
            "doc": ap.name, "field": "date_of_birth", "type": "declared DOB differs from ID card",
            "declared": "14-08-1996", "id_card": PERSON["dob"],
            "expected_detections": ["date_mismatch (kept as INCONSISTENCY: single-digit, could be a typo)"]})
    save_jpeg(ap_img, ap, 92)
    manifest["documents"][ap.name] = "application_form / scanned JPG"

    # 4. ID card (photographed/scanned JPG)
    card, cmeta = build_id_card(seed=5)
    card_img, _ = simulate_scan(card, seed=44, angle=0.15, noise=5.5)
    idp = case_dir / "04_identity_card.jpg"
    if tampered:
        save_jpeg(card_img, work / "id_scan.jpg", 88)
        card_img = load(work / "id_scan.jpg")
        card_img, info = splice_id_photo(card_img, cmeta["photo_box"])
        manifest["planted"].append({
            "doc": idp.name, "field": "photo", "type": "photo region spliced from another image (different noise + JPEG history)",
            **info, "expected_detections": ["noise_inconsistency"]})
    save_jpeg(card_img, idp, 88)
    manifest["documents"][idp.name] = "identity_card / scanned JPG"

    # 5. Employer letter (scanned JPG)
    lt_pdf = work / "letter_clean.pdf"
    build_letter(lt_pdf, FORGED_NET if tampered else NET, "01-07-2019" if tampered else PERSON["doj"],
                 hr_sig if tampered else hr_sig_wet)
    lt_img, _ = simulate_scan(render_pdf(lt_pdf), seed=55, angle=0.35)
    lt = case_dir / "05_employment_letter.jpg"
    save_jpeg(lt_img, lt, 90)
    manifest["documents"][lt.name] = "employment_letter / scanned JPG"
    if tampered:
        manifest["planted"].append({
            "doc": lt.name, "field": "signature", "type": "wet signature on scanned letter is a shape-identical copy of the payslip's printed signature",
            "expected_detections": ["signature_identical"]})
        manifest["planted"].append({
            "doc": lt.name, "field": "date_of_joining", "type": "tenure inflated (since 01-07-2019 vs payslip 01-07-2021)",
            "expected_detections": ["cross_doc_date_mismatch"]})
        manifest["planted"].append({
            "doc": lt.name, "field": "salary", "type": "letter salary 86,500.00 contradicts bank salary credits",
            "expected_detections": ["claim_vs_evidence"]})
    (case_dir / "MANIFEST_ground_truth.json").write_text(json.dumps(manifest, indent=2))
    return manifest


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    for name, t in (("case_genuine", False), ("case_tampered", True)):
        m = build_case(name, t)
        print(f"{name}: {len(m['documents'])} documents, {len(m['planted'])} planted manipulations")
    shutil.rmtree(OUT / "_work", ignore_errors=True)


if __name__ == "__main__":
    main()
