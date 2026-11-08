"""The software a case was investigated with, recorded in every dossier and audit trail.

SAKSHI is deterministic for identical inputs and identical software. The OCR engine is the part that moves results
most: Tesseract 5.5 reads one IFSC character on the demo statement differently from 5.4, which adds two explained
observations. So every dossier states the engine and library versions it was produced with, and warns when the OCR
engine differs from the one the published results were measured with.
"""
from __future__ import annotations

import platform
import sys
from functools import lru_cache
from importlib import metadata

from . import __version__

# the Tesseract major.minor the numbers in README / docs/RESULTS.md were measured with
CALIBRATED_OCR = "5.4"
_LIBS = ("pymupdf", "opencv-python-headless", "numpy", "scikit-image", "pillow", "pytesseract")


@lru_cache(maxsize=1)
def environment() -> dict:
    try:
        import pytesseract
        ocr = str(pytesseract.get_tesseract_version()).split()[0]
    except Exception:  # Tesseract missing or unreadable: reported, never guessed
        ocr = "unknown"
    libs = {}
    for name in _LIBS:
        try:
            libs[name] = metadata.version(name)
        except metadata.PackageNotFoundError:
            libs[name] = None
    major_minor = ".".join(ocr.split(".")[:2])
    warning = None
    if ocr == "unknown":
        warning = "The OCR engine version could not be read."
    elif major_minor != CALIBRATED_OCR:
        warning = (f"OCR engine Tesseract {ocr} differs from {CALIBRATED_OCR}, the version the published results were "
                   f"measured with. Counts can differ slightly (Tesseract 5.5 reads one IFSC character on the demo "
                   f"statement differently); detection is unchanged.")
    return {"sakshi": __version__, "python": platform.python_version(), "platform": platform.platform(terse=True),
            "tesseract": ocr, "calibrated_tesseract": CALIBRATED_OCR, "libraries": libs, "warning": warning,
            "executable_64bit": sys.maxsize > 2 ** 32}
