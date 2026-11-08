"""Signatures on real-looking letters: printed coloured text is not a signature; pasted signature images are seen.

Found on a real letter tested privately: a letterhead printed in navy blue was reported as two "blue-ink
signatures", and the letter's own signature, a pasted image in a born-digital PDF, was never looked at.
All documents here are synthetic.

* a born-digital letter with a navy-blue printed heading and footer: no signature is reported from printed text;
* a scanned page with navy-blue printed text and a blue pen signature: the pen signature is found, the text is not;
* a born-digital letter with a signature image placed above "Authorised Signatory": the image is found;
* the same letter with the signature image pasted in a later save: reported as added after the document was made;
* the existing signature suite (tests/run_signatures.py) must still pass.

    python tests/run_signature_images.py
"""
import io
import shutil
import sys
import tempfile
from pathlib import Path

import cv2
import numpy as np
import pymupdf as fitz

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from sakshi.pipeline import run_case  # noqa: E402

NAVY = (0.0, 0.16, 0.42)
results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f"  ({detail})" if detail else ""), flush=True)


def signature_png(color=(30, 40, 160)) -> bytes:
    """A pen-like signature: two looping strokes on a white background (BGR colour)."""
    img = np.full((92, 240, 3), 255, np.uint8)
    t = np.linspace(0, 1, 400)
    for k, (a, b) in enumerate([(20, 70), (110, 220)]):
        x = a + (b - a) * t
        y = 48 + 22 * np.sin(t * 9 + k) * np.exp(-t) + 8 * np.sin(t * 31)
        pts = np.stack([x, y], 1).astype(np.int32)
        cv2.polylines(img, [pts], False, color, 2, cv2.LINE_AA)
    ok, buf = cv2.imencode(".png", img)
    return buf.tobytes()


def letter(path: Path, sig: str | None):
    """sig: None, 'inline' (placed when the letter is made) or 'later' (pasted in an incremental save)."""
    doc = fitz.open()
    pg = doc.new_page(width=595, height=842)
    pg.insert_text((72, 70), "INSTITUTE OF SYNTHETIC SCIENCES AND TECHNOLOGY", fontsize=15, fontname="tibo", color=NAVY)
    y = 130
    for line in ["SYNTHETIC SPECIMEN - test letter, not a real document",
                 "This is to certify that the applicant completed the programme in 2024.",
                 "We recommend the applicant without reservation for further study.",
                 "Reference number 2026/AC/0412, issued on 20-01-2026."]:
        pg.insert_text((72, y), line, fontsize=11, fontname="tiro")
        y += 22
    pg.insert_text((72, 470), "Authorised Signatory", fontsize=11, fontname="tiro")
    pg.insert_text((150, 790), "Block A, Synthetic Campus, Sector 99, Testnagar - 000000", fontsize=10, fontname="tibo", color=NAVY)
    pg.insert_text((190, 806), "Tel.: +91-00-0000-0000   E-mail: office@example.org", fontsize=10, fontname="tiro", color=NAVY)
    rect = fitz.Rect(72, 405, 252, 460)
    if sig == "inline":
        pg.insert_image(rect, stream=signature_png())
    doc.save(path)
    doc.close()
    if sig == "later":
        doc = fitz.open(path)
        doc[0].insert_image(rect, stream=signature_png())
        doc.saveIncr()
        doc.close()


def scan_with_navy_text(path: Path):
    """A scanned page: navy printed heading (text) and a blue pen signature."""
    img = np.full((1100, 850, 3), 250, np.uint8)
    cv2.putText(img, "INSTITUTE OF SYNTHETIC SCIENCES", (60, 90), cv2.FONT_HERSHEY_TRIPLEX, 1.15, (110, 40, 0), 2, cv2.LINE_AA)
    cv2.putText(img, "SYNTHETIC SPECIMEN - scanned test letter", (60, 160), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (30, 30, 30), 2)
    cv2.putText(img, "Authorised Signatory", (60, 660), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (30, 30, 30), 2)
    sig = cv2.imdecode(np.frombuffer(signature_png((170, 60, 20)), np.uint8), cv2.IMREAD_COLOR)
    img[540:632, 60:300] = np.minimum(img[540:632, 60:300], sig)
    noise = np.random.default_rng(3).normal(0, 3, img.shape)
    img = np.clip(img + noise, 0, 255).astype(np.uint8)
    cv2.imwrite(str(path), img, [cv2.IMWRITE_JPEG_QUALITY, 90])


def sigs_of(d):
    return d["documents"][0]["structure"].get("signatures", [])


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="sakshi_sigimg_"))
    try:
        for name, sig in (("plain", None), ("inline", "inline"), ("later", "later")):
            (tmp / name).mkdir()
            letter(tmp / name / "letter.pdf", sig)
        d = run_case([str(tmp / "plain" / "letter.pdf")], tmp / "o_plain", case_id="SIG-PLAIN", html=False)
        check("born-digital letter, navy printed heading and footer: no signature reported", not sigs_of(d),
              f"{len(sigs_of(d))} reported")
        d = run_case([str(tmp / "inline" / "letter.pdf")], tmp / "o_inline", case_id="SIG-INLINE", html=False)
        s = sigs_of(d)
        later = [f for f in d["findings"] if f["check"] == "signature_image_added_later"]
        check("signature image above 'Authorised Signatory' is found", len(s) == 1 and s[0].get("ink") == "image",
              str([x.get("ink") for x in s]))
        check("an image placed when the letter was made is not called pasted later", not later)
        d = run_case([str(tmp / "later" / "letter.pdf")], tmp / "o_later", case_id="SIG-LATER", html=False)
        later = [f for f in d["findings"] if f["check"] == "signature_image_added_later"]
        check("signature image pasted in a later save is reported", len(later) == 1 and later[0]["tier"] == "INCONSISTENCY",
              later[0]["title"][:90] if later else "none")
        scan = tmp / "scan" / "letter.jpg"
        scan.parent.mkdir()
        scan_with_navy_text(scan)
        d = run_case([str(scan)], tmp / "o_scan", case_id="SIG-SCAN", html=False)
        s = sigs_of(d)
        check("scan: the blue pen signature is found and the navy printed heading is not",
              len(s) == 1 and s[0]["bbox"][1] > 400, str([round(x["bbox"][1]) for x in s]))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    ok = all(results)
    print("RESULT:", "ALL PASS" if ok else "FAILURES")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
