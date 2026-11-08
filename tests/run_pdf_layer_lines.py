"""Text hidden under a box when a whole line is one text run (pdfTeX and similar generators).

Found on a real LaTeX-made letter: the PDF-layer sensor measured coverage per text run, so a white box over one
number in a line written as one run covered only ~15% of it and went unseen, and SAKSHI's own planted-edit canary
was missed, yet the sensor was still reported as "ok". All documents here are synthetic.

* a born-digital letter whose lines are single text runs, edited the way a PDF editor does it (white box over one
  number, a new number written on top, saved incrementally): the hidden value is found and recovered;
* the unedited letter: no finding, and the canary is now caught;
* a sensor that misses its own canary is reported as "blind on this document" in the capabilities, the notes and
  the dossier's self_test_warnings, never as clean.

    python tests/run_pdf_layer_lines.py
"""
import shutil
import sys
import tempfile
from pathlib import Path

import pymupdf as fitz

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from sakshi import pipeline  # noqa: E402
from sakshi.forensics import pdf_layers  # noqa: E402

results = []
LINES = [
    "SYNTHETIC SPECIMEN - letter of reference for testing only",
    "This is to certify that the applicant has worked with us since 01-07-2021.",
    "The applicant's monthly salary is Rs. 68,500.00 and is credited on the last day.",
    "Employee ID NA-10457, reference number 2026/HR/0417, issued on 31-10-2026.",
    "For verification, contact the human resources office at the address above.",
]


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f"  ({detail})" if detail else ""), flush=True)


def letter(path: Path):
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    y = 120
    for line in LINES:  # one insert_text call per line: one text run per line, like pdfTeX
        page.insert_text((72, y), line, fontsize=11, fontname="tiro")
        y += 22
    doc.save(path)
    doc.close()


def edit(src: Path, dst: Path):
    shutil.copy(src, dst)
    doc = fitz.open(dst)
    page = doc[0]
    r = page.search_for("68,500.00")[0]
    page.draw_rect(r, color=None, fill=(1, 1, 1), overlay=True)
    page.insert_text((r.x0, r.y1 - 2.2), "86,500.00", fontsize=11, fontname="tiro")
    doc.saveIncr()
    doc.close()


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="sakshi_lines_"))
    try:
        clean, edited = tmp / "clean" / "letter.pdf", tmp / "edited" / "letter.pdf"
        clean.parent.mkdir()
        edited.parent.mkdir()
        letter(clean)
        edit(clean, edited)
        runs = [s for s in fitz.open(clean)[0].get_texttrace() if "68,500.00" in "".join(chr(c[0]) for c in s["chars"])]
        check("the salary sits inside a whole-line text run (the case that was missed)",
              runs and (runs[0]["bbox"][2] - runs[0]["bbox"][0]) > 300, f"run width {runs[0]['bbox'][2] - runs[0]['bbox'][0]:.0f} pt" if runs else "")

        d = pipeline.run_case([str(edited)], tmp / "out_edited", case_id="LINES-EDITED", html=False)
        f = [x for x in d["findings"] if x["check"] == "occluded_text"]
        check("white box over one number in a line: hidden value found and recovered",
              f and f[0]["repair"].get("recovered_value") == "68,500.00"
              and f[0]["repair"].get("displayed_value") == "86,500.00" and f[0]["tier"] == "POTENTIAL_MANIPULATION",
              f[0]["title"][:90] if f else "no finding")

        d = pipeline.run_case([str(clean)], tmp / "out_clean", case_id="LINES-CLEAN", html=False)
        caps = d["documents"][0]["capabilities"]
        check("unedited letter: no occluded-text finding",
              not [x for x in d["findings"] if x["check"] == "occluded_text"])
        check("unedited letter: the planted-edit canary is now caught",
              caps["self_test"].get("pdf_layers") == "1/1 canaries caught" and not d["self_test_warnings"],
              str(caps["self_test"]))

        real = pdf_layers.covered_text
        pdf_layers.covered_text = lambda spans, rect, before_seq: []  # a detector that sees nothing
        try:
            d = pipeline.run_case([str(clean)], tmp / "out_blind", case_id="LINES-BLIND", html=False)
        finally:
            pdf_layers.covered_text = real
        caps = d["documents"][0]["capabilities"]
        check("a sensor that misses its own canary is reported blind, not ok",
              str(caps.get("pdf_layers", "")).startswith("blind on this document")
              and [w["sensor"] for w in d["self_test_warnings"]] == ["pdf_layers"]
              and any("not evidence" in n for n in d["documents"][0]["notes"]), str(caps.get("pdf_layers")))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    ok = all(results)
    print("RESULT:", "ALL PASS" if ok else "FAILURES")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
