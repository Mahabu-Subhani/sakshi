"""Document ingestion: hashing, modality detection, page rasterization, text acquisition.

Modalities
  digital_pdf  - has a real text layer. Words come from the PDF (with font names),
                 pages are rendered for visual checks, and an OCR pass is kept as a
                 second, independent read ("dual read").
  scanned_pdf  - image-only PDF. The embedded scan is extracted at native resolution
                 (no resampling, so sensor noise survives for the pixel forensics).
  image        - JPG / PNG / TIFF / WEBP.
"""
from __future__ import annotations

import io
import math
import shutil
from pathlib import Path

import cv2
import numpy as np
import pymupdf as fitz
import pytesseract
from PIL import Image

from .audit import sha256_file
from .models import Document, Line, Page, Word

DPI = 200
IMAGE_EXT = {".jpg", ".jpeg", ".png", ".tif", ".tiff", ".webp", ".bmp"}
SUPPORTED = IMAGE_EXT | {".pdf"}
MAX_PAGES = 6        # pixel forensics run on the first MAX_PAGES pages (cost)
MAX_TEXT_PAGES = 40  # every page up to this is read, so arithmetic and cross-document rules see long statements


_PASSWORDS: dict[str, str] = {}  # path -> password that opened it; process memory only, never written out


def open_pdf(path):
    """Open a PDF the way ingest did, including with the analyst's password."""
    pdf = fitz.open(str(path))
    if pdf.needs_pass:
        pdf.authenticate(_PASSWORDS.get(str(path), ""))
    return pdf


def forget_passwords(paths) -> None:
    for p in paths:
        _PASSWORDS.pop(str(p), None)


class UnsupportedInput(Exception):
    pass


def _save_rgb(arr: np.ndarray, path: Path):
    Image.fromarray(arr).save(str(path))


def load_rgb(path: str) -> np.ndarray:
    return np.array(Image.open(path).convert("RGB"))


def estimate_skew(gray: np.ndarray) -> float:
    """Projection-profile skew estimate in degrees (positive = counter-clockwise text)."""
    small = cv2.resize(gray, None, fx=0.35, fy=0.35, interpolation=cv2.INTER_AREA)
    ink = (small < 150).astype(np.uint8) * 255
    if ink.mean() < 0.5:
        return 0.0
    h, w = ink.shape
    best, best_a = -1.0, 0.0
    for a in np.arange(-3.0, 3.01, 0.1):
        M = cv2.getRotationMatrix2D((w / 2, h / 2), a, 1.0)
        r = cv2.warpAffine(ink, M, (w, h), flags=cv2.INTER_NEAREST)
        prof = r.sum(axis=1).astype(np.float64)
        score = float(np.var(prof))
        if score > best:
            best, best_a = score, a
    return float(-best_a)


def ocr_words(img_path: str, lang: str = "eng") -> list[Word]:
    img = Image.open(img_path)
    data = pytesseract.image_to_data(img, lang=lang, config="--oem 1 --psm 6",
                                     output_type=pytesseract.Output.DICT)
    words = []
    for i, t in enumerate(data["text"]):
        t = (t or "").strip()
        if not t:
            continue
        conf = float(data["conf"][i])
        if conf < 0:
            continue
        x, y, w, h = data["left"][i], data["top"][i], data["width"][i], data["height"][i]
        line_key = data["block_num"][i] * 10000 + data["par_num"][i] * 100 + data["line_num"][i]
        words.append(Word(text=t, bbox=(x, y, x + w, y + h), conf=conf / 100.0, line_id=line_key, source="ocr"))
    return words


def pdf_words(page: fitz.Page, scale: float) -> list[Word]:
    """Words from the PDF text layer with font name and size. Character bboxes are kept
    per word so occlusion checks can work at character level."""
    out = []
    raw = page.get_text("rawdict")
    for block in raw.get("blocks", []):
        for line in block.get("lines", []):
            for span in line.get("spans", []):
                font, size = span.get("font", ""), span.get("size", 0.0)
                cur, boxes = "", []
                for ch in span.get("chars", []) + [{"c": " ", "bbox": None}]:
                    c = ch["c"]
                    if c.isspace():
                        if cur:
                            x0 = min(b[0] for b in boxes); y0 = min(b[1] for b in boxes)
                            x1 = max(b[2] for b in boxes); y1 = max(b[3] for b in boxes)
                            out.append(Word(text=cur, bbox=(x0 * scale, y0 * scale, x1 * scale, y1 * scale),
                                            conf=0.99, font=font, size=size, source="pdf_text"))
                        cur, boxes = "", []
                    else:
                        cur += c
                        boxes.append(ch["bbox"])
    return out


def group_lines(words: list[Word]) -> list[Line]:
    """Words -> visual lines. OCR words keep Tesseract's own line structure; PDF words are
    grouped by vertical overlap against each line's median centre (robust to tall outliers)."""
    groups: list[list[Word]] = []
    if words and all(w.source == "ocr" for w in words):
        by = {}
        for w in words:
            by.setdefault(w.line_id, []).append(w)
        groups = list(by.values())
    else:
        ws = sorted(words, key=lambda w: ((w.bbox[1] + w.bbox[3]) / 2, w.bbox[0]))
        for w in ws:
            cy = (w.bbox[1] + w.bbox[3]) / 2
            h = max(4.0, w.bbox[3] - w.bbox[1])
            placed = False
            for ln in groups[-4:]:
                lcy = float(np.median([(x.bbox[1] + x.bbox[3]) / 2 for x in ln]))
                lh = float(np.median([x.bbox[3] - x.bbox[1] for x in ln]))
                if abs(cy - lcy) < 0.4 * min(h, lh) + 1:
                    ln.append(w)
                    placed = True
                    break
            if not placed:
                groups.append([w])
    groups.sort(key=lambda ln: float(np.median([(x.bbox[1] + x.bbox[3]) / 2 for x in ln])))
    out = []
    for i, ln in enumerate(groups):
        ln.sort(key=lambda w: w.bbox[0])
        for w in ln:
            w.line_id = i
        bb = (min(w.bbox[0] for w in ln), min(w.bbox[1] for w in ln),
              max(w.bbox[2] for w in ln), max(w.bbox[3] for w in ln))
        out.append(Line(id=i, words=ln, bbox=bb))
    return out


def page_layers(pdf, pg) -> dict:
    """What a PDF page is made of: a dominant full-page image (a scan) and the VISIBLE vector objects drawn
    over it (text, filled shapes, extra images). Invisible text (render mode 3 / zero opacity) is counted apart."""
    area = pg.rect.width * pg.rect.height
    dom = None
    imgs = pg.get_images(full=True)
    for im in imgs:
        try:
            for r in pg.get_image_rects(im[0]):
                if r.width * r.height >= 0.85 * area and (dom is None or r.width * r.height > dom[1].width * dom[1].height):
                    dom = (im[0], r)
        except Exception:
            continue
    vis, invis, overlays = 0, 0, []
    try:
        trace = pg.get_texttrace()
    except Exception:
        trace = []
    for s in trace:
        txt = "".join(chr(c[0]) for c in s["chars"]).strip()
        if not txt:
            continue
        invisible = s.get("type", 0) == 3 or s.get("opacity", 1.0) == 0
        n = len(txt.split())
        if invisible:
            invis += n
            continue
        vis += n
        if dom is not None:
            overlays.append({"kind": "text", "text": txt, "bbox": tuple(s["bbox"])})
    if dom is not None:
        for d in pg.get_drawings():
            r = d["rect"]
            if r.width * r.height >= 0.85 * area or r.width < 2 or r.height < 2:
                continue  # page-wide frames and hairlines are not edits
            if d.get("fill") is not None or d.get("color") is not None:
                overlays.append({"kind": "shape_filled" if d.get("fill") is not None else "shape",
                                 "text": "", "bbox": (r.x0, r.y0, r.x1, r.y1)})
        for im in imgs:
            if dom and im[0] == dom[0]:
                continue
            try:
                for r in pg.get_image_rects(im[0]):
                    overlays.append({"kind": "image", "text": "", "bbox": (r.x0, r.y0, r.x1, r.y1)})
            except Exception:
                continue
    return {"dominant": dom, "visible_words": vis, "invisible_words": invis, "overlays": overlays}


def ingest(path: str, doc_id: str, work: Path, lang: str = "eng", passwords=()) -> Document:
    p = Path(path)
    ext = p.suffix.lower()
    if ext not in SUPPORTED:
        raise UnsupportedInput(f"{p.name}: file type '{ext}' is not supported (PDF, JPG, PNG, TIFF, WEBP, BMP)")
    work.mkdir(parents=True, exist_ok=True)
    doc = Document(doc_id=doc_id, filename=p.name, path=str(p), sha256=sha256_file(p), modality="image")

    if ext == ".pdf":
        try:
            pdf = fitz.open(str(p))
        except Exception as e:  # corrupt file: fail safely
            raise UnsupportedInput(f"{p.name}: could not open PDF ({e})")
        if pdf.needs_pass:
            # bank statements are commonly password-protected; the password itself is never logged or stored
            pw = next((pw for pw in passwords if pw and pdf.authenticate(pw)), None)
            if pw is None:
                raise UnsupportedInput(f"{p.name}: password-protected PDF, cannot analyse without the password"
                                       + (" (the supplied password(s) did not open it)" if passwords else ""))
            _PASSWORDS[str(p)] = pw
            doc.notes.append("Opened with a password supplied by the analyst.")
        doc.pdf_meta = {k: v for k, v in (pdf.metadata or {}).items() if v}
        if getattr(pdf, "is_repaired", False):
            doc.notes.append("The PDF's internal structure is damaged (truncated or malformed) and was repaired on open; "
                             "file-structure checks may be incomplete.")
            doc.capabilities["file_integrity"] = "damaged, repaired on open"
        n_words = sum(len(pg.get_text("words")) for pg in pdf)
        layers = [page_layers(pdf, pg) for i, pg in enumerate(pdf) if i < MAX_TEXT_PAGES]
        # A page that is one full-page scan with only a few VISIBLE words on top is a scan, even when it
        # carries an invisible OCR layer (CamScanner / Adobe Scan "searchable" PDFs). Invisible words do not count.
        scan_like = bool(layers) and all(L["dominant"] is not None and L["visible_words"] < 15 for L in layers)
        doc.modality = "scanned_pdf" if (scan_like or n_words < 15) else "digital_pdf"
        if scan_like and any(L["invisible_words"] for L in layers):
            doc.structure["invisible_ocr_layer"] = True
            doc.notes.append("Searchable scan: the PDF carries an invisible OCR text layer from the scanner app. SAKSHI "
                             "ignores it and reads the pixels itself.")
        if pdf.page_count > MAX_TEXT_PAGES:
            doc.notes.append(f"Only the first {MAX_TEXT_PAGES} of {pdf.page_count} pages were read.")
        if pdf.page_count > MAX_PAGES:
            doc.notes.append(f"Pixel forensics ran on the first {MAX_PAGES} pages; pages {MAX_PAGES + 1}-"
                             f"{min(pdf.page_count, MAX_TEXT_PAGES)} were read for arithmetic, cross-document "
                             "and PDF-structure checks only.")
        for i, pg in enumerate(pdf):
            if i >= MAX_TEXT_PAGES:
                break
            img_path = work / f"{doc_id}_p{i}.png"
            arr = None
            base = None
            L = layers[i]
            if doc.modality == "scanned_pdf" and L["dominant"] is not None:
                xref, rect = L["dominant"]
                try:
                    info = pdf.extract_image(xref)
                    base = np.array(Image.open(io.BytesIO(info["image"])).convert("RGB"))
                except Exception:
                    base = None
                if base is not None:
                    # Render what a READER sees on the scan's own pixel grid and compare it with the bare scan.
                    # Pixel difference catches what the object list cannot: annotations (FreeText comments),
                    # edits nested in Form XObjects, pasted image patches (Argon round 4).
                    h0, w0 = base.shape[:2]
                    sx, sy = w0 / rect.width, h0 / rect.height
                    seen = None
                    if pg.rotation == 0:
                        try:
                            pix = pg.get_pixmap(matrix=fitz.Matrix(sx, sy), clip=rect, alpha=False)
                            seen = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.h, pix.w, pix.n)[:, :, :3].copy()
                            if seen.shape[:2] != (h0, w0):
                                seen = cv2.resize(seen, (w0, h0), interpolation=cv2.INTER_NEAREST)
                        except Exception:
                            seen = None
                    objs = [{"kind": o["kind"], "text": o["text"],
                             "bbox": [(o["bbox"][0] - rect.x0) * sx, (o["bbox"][1] - rect.y0) * sy,
                                      (o["bbox"][2] - rect.x0) * sx, (o["bbox"][3] - rect.y0) * sy]} for o in L["overlays"]]
                    if seen is not None:
                        diff = (np.abs(seen.astype(np.int16) - base.astype(np.int16)).max(axis=2) > 48).astype(np.uint8)
                        diff = cv2.morphologyEx(diff, cv2.MORPH_OPEN, np.ones((2, 2), np.uint8))
                        if diff.mean() > 0.2:
                            doc.notes.append(f"Page {i + 1}: the rendered page and the embedded scan could not be aligned; "
                                             "overlay comparison used the PDF object list only.")
                        elif diff.sum() > 30:
                            n, _, st, _ = cv2.connectedComponentsWithStats(cv2.dilate(diff, np.ones((9, 9), np.uint8)))
                            for k in range(1, n):
                                x, y, ww, hh, a = st[k]
                                bb = [float(x), float(y), float(x + ww), float(y + hh)]
                                covered = any(o["bbox"][0] - 6 <= bb[0] and o["bbox"][1] - 6 <= bb[1] and o["bbox"][2] + 6 >= bb[2]
                                              and o["bbox"][3] + 6 >= bb[3] for o in objs)
                                if not covered and a >= 40:
                                    objs.append({"kind": "pixels (annotation or nested object)", "text": "", "bbox": bb})
                    if not objs:
                        arr = base  # native scan pixels, nothing drawn on top
                    else:
                        arr = seen if seen is not None else base
                        base_path = work / f"{doc_id}_p{i}_scan_underneath.png"
                        _save_rgb(base, base_path)
                        doc.structure.setdefault("scan_overlays", []).append(
                            {"page": i, "base_image": str(base_path), "objects": objs})
            if arr is None:
                pix = pg.get_pixmap(dpi=DPI, alpha=False)
                arr = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.h, pix.w, pix.n)[:, :, :3].copy()
            _save_rgb(arr, img_path)
            page = Page(index=i, image_path=str(img_path), width=arr.shape[1], height=arr.shape[0])
            if doc.modality == "digital_pdf":
                page.words = pdf_words(pg, arr.shape[1] / pg.rect.width)
            doc.pages.append(page)
        pdf.close()
    else:
        try:
            im = Image.open(str(p))
            im.load()
        except Exception as e:
            raise UnsupportedInput(f"{p.name}: could not decode image ({e})")
        arr = np.array(im.convert("RGB"))
        img_path = work / f"{doc_id}_p0.png"
        _save_rgb(arr, img_path)
        doc.pages.append(Page(index=0, image_path=str(img_path), width=arr.shape[1], height=arr.shape[0]))

    for page in doc.pages:
        gray = cv2.cvtColor(load_rgb(page.image_path), cv2.COLOR_RGB2GRAY)
        page.skew_deg = estimate_skew(gray)
        if doc.modality != "digital_pdf":
            src = page.image_path
            if abs(page.skew_deg) > 1.0:
                # phone photo or badly fed scan: deskew a copy for OCR only
                h, w = gray.shape
                M = cv2.getRotationMatrix2D((w / 2, h / 2), -page.skew_deg, 1.0)
                rot = cv2.warpAffine(load_rgb(src), M, (w, h), borderValue=(245, 245, 245))
                src = str(work / f"{doc.doc_id}_p{page.index}_deskew.png")
                _save_rgb(rot, Path(src))
                page.image_path = src
                doc.notes.append(f"Page {page.index + 1} was deskewed by {page.skew_deg:.1f} deg before analysis; "
                                 "pixel-level forensics run on resampled pixels and are less reliable.")
            page.words = ocr_words(src, lang=lang)
        page.lines = group_lines(page.words)
    return doc


def dual_read(doc: Document, lang: str = "eng") -> None:
    """For born-digital PDFs, OCR the rendered page as an independent second reader.
    Disagreements between what the file says and what a reader sees are evidence."""
    if doc.modality != "digital_pdf":
        return
    for page in doc.pages:
        page.ocr_words = ocr_words(page.image_path, lang=lang)  # type: ignore[attr-defined]


def make_reocr(doc: Document):
    """Independent second reader for one table cell: the crop only, upscaled, digits whitelist.
    It never sees the ledger or the expected value (Argon's guard against biased re-reads)."""
    cache = {}

    def reocr(page_index: int, bbox) -> tuple[str, float]:
        try:
            P = doc.pages[page_index]
            if P.image_path not in cache:
                cache[P.image_path] = Image.open(P.image_path).convert("L")
            im = cache[P.image_path]
            x0, y0, x1, y1 = (int(v) for v in bbox)
            crop = im.crop((max(0, x0 - 6), max(0, y0 - 5), min(im.width, x1 + 6), min(im.height, y1 + 5)))
            crop = crop.resize((crop.width * 2, crop.height * 2), Image.BICUBIC)
            d = pytesseract.image_to_data(crop, config="--oem 1 --psm 7 -c tessedit_char_whitelist=0123456789,.-DrCr",
                                          output_type=pytesseract.Output.DICT)
            toks = [(t, float(c)) for t, c in zip(d["text"], d["conf"]) if t.strip() and float(c) >= 0]
            if not toks:
                return "", 0.0
            return " ".join(t for t, _ in toks), min(c for _, c in toks) / 100.0
        except Exception:
            return "", 0.0

    return reocr
