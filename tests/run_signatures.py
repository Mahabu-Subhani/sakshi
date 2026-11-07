"""Black-ink signatures: detection near the caption, cross-document identity, and no false signatures.

    python tests/run_signatures.py

Builds a scanned employment letter and a scanned payslip signed in black ink (same generator, ink switched
from blue to black) and checks:
  1. reproduced  - the same signature on both documents is detected on each and flagged as shape-identical;
  2. different   - two different signatures are detected and NOT flagged as identical;
  3. blank       - a letter whose signature caption has nothing above it is reported as missing a signature
                   (printed text near the caption must not be mistaken for a signature).
Known limit: black ink is searched for above a readable signature caption, so a signature drawn over its own
caption (the caption is then unreadable to OCR) is not found; blue ink is found anywhere by its colour.
Exit code 1 on any failure.
"""
from __future__ import annotations

import importlib.util
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sakshi.pipeline import run_case  # noqa: E402

spec = importlib.util.spec_from_file_location("sakshi_generate", ROOT / "dataset" / "generate.py")
G = importlib.util.module_from_spec(spec)
sys.modules["sakshi_generate"] = G
spec.loader.exec_module(G)
G.SIGNATURE_INK = (0.10, 0.10, 0.11)  # black ballpoint


def scanned(build, out_jpg: Path, seed: int):
    pdf = out_jpg.with_suffix(".pdf")
    build(pdf)
    img, _ = G.simulate_scan(G.render_pdf(pdf), seed=seed, angle=0.3)
    G.save_jpeg(img, out_jpg, 88)
    return str(out_jpg)


def case(letter_sig, app_sig):  # app_sig signs the payslip
    w = Path(tempfile.mkdtemp())
    P = G.PERSON
    files = [scanned(lambda p: G.build_letter(p, G.NET, P["doj"], letter_sig), w / "05_employment_letter.jpg", 501),
             scanned(lambda p: G.build_payslip(p, app_sig), w / "01_payslip_oct2026.jpg", 502)]
    d = run_case(files, w / "out", case_id="SIG", html=False)
    sigs = {doc["filename"]: (doc.get("structure") or {}).get("signatures", []) for doc in d["documents"]}
    checks = [f["check"] for f in d["findings"]]
    return sigs, checks


def main() -> int:
    ok = True

    def check(cond, msg):
        nonlocal ok
        ok &= bool(cond)
        print(("PASS " if cond else "FAIL ") + msg, flush=True)

    a = G.signature_strokes(seed=3)
    b = G.signature_strokes(seed=7, variant=2, jitter=0.006)

    sigs, checks = case(a, a)
    check(all(len(v) >= 1 for v in sigs.values()), f"reproduced: black signature detected on both documents {[len(v) for v in sigs.values()]}")
    check("signature_identical" in checks, "reproduced: the same black signature on two documents is flagged as shape-identical")

    sigs, checks = case(a, b)
    check(all(len(v) >= 1 for v in sigs.values()), f"different: black signature detected on both documents {[len(v) for v in sigs.values()]}")
    check("signature_identical" not in checks, "different: two different signatures are not flagged as identical")

    sigs, checks = case([], b)
    letter = [v for k, v in sigs.items() if k.startswith("05_")][0]
    check(len(letter) == 0, "blank: no signature invented from the printed text around the caption")
    check("signature_missing" in checks, "blank: the empty signature caption is reported as missing a signature")

    print("\nRESULT:", "ALL PASS" if ok else "FAILURES")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
