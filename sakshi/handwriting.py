"""Optional handwriting reader: Microsoft TrOCR (microsoft/trocr-base-handwritten, MIT licence), offline, CPU.

Tesseract reads printed text; handwriting comes back as low-confidence fragments. When switched on
(`sakshi run --handwriting` or SAKSHI_HANDWRITING=1), each text line that Tesseract read with low confidence on a
scanned page or photo is cropped and read again by TrOCR, a transformer trained on English handwriting (IAM) that
reads ONE text line at a time.

What it is for, and what it is not:
* its readings are reported in the dossier next to Tesseract's, with a confidence, for the analyst to read;
* they are never fed into the rules and never raise or lower a finding;
* it was measured against Tesseract on real handwriting from FUNSD (tests/eval_handwriting.py), not on Indian
  handwriting or scripts, for which no public test set was available.

Needs `pip install -r requirements-handwriting.txt` (PyTorch, Transformers) and the model files in
SAKSHI_TROCR_DIR (default: ~/models/trocr-base-handwritten), downloaded once from Hugging Face.
"""
from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

import numpy as np

LOW_CONF = 0.5          # a line Tesseract read with mean word confidence below this is offered to TrOCR
MAX_LINES = 40          # per document, so one messy page cannot run for minutes
MODEL_ENV = "SAKSHI_TROCR_DIR"


def enabled() -> bool:
    return os.environ.get("SAKSHI_HANDWRITING", "").lower() in ("1", "true", "yes")


def model_dir() -> Path:
    return Path(os.environ.get(MODEL_ENV) or Path.home() / "models" / "trocr-base-handwritten")


def status() -> str:
    """Why the reader can or cannot run here, for the capability list."""
    try:
        import torch  # noqa: F401
        import transformers  # noqa: F401
    except ImportError:
        return "not installed (pip install -r requirements-handwriting.txt)"
    if not (model_dir() / "config.json").exists():
        return f"model files not found in {model_dir()} (set {MODEL_ENV})"
    return "ok"


@lru_cache(maxsize=1)
def _load():
    import torch
    from transformers import TrOCRProcessor, VisionEncoderDecoderModel
    torch.set_num_threads(max(1, (os.cpu_count() or 2) // 2))
    proc = TrOCRProcessor.from_pretrained(str(model_dir()), local_files_only=True)
    model = VisionEncoderDecoderModel.from_pretrained(str(model_dir()), local_files_only=True)
    model.eval()
    return proc, model


def read_lines(images: list) -> list[tuple[str, float]]:
    """Read single text-line images (RGB numpy arrays or PIL images); returns (text, confidence 0..1) each.
    Confidence is the geometric mean of the probabilities of the generated tokens."""
    if not images:
        return []
    import torch
    from PIL import Image
    proc, model = _load()
    pil = [im if isinstance(im, Image.Image) else Image.fromarray(np.asarray(im)).convert("RGB") for im in images]
    out = []
    with torch.inference_mode():
        for i in range(0, len(pil), 8):
            px = proc(images=pil[i:i + 8], return_tensors="pt").pixel_values
            gen = model.generate(px, max_new_tokens=48, num_beams=1, output_scores=True,
                                 return_dict_in_generate=True)
            texts = proc.batch_decode(gen.sequences, skip_special_tokens=True)
            scores = model.compute_transition_scores(gen.sequences, gen.scores, normalize_logits=True)
            for t, sc in zip(texts, scores):
                sc = sc[torch.isfinite(sc)]
                conf = float(torch.exp(sc.mean())) if len(sc) else 0.0
                out.append((t.strip(), round(conf, 3)))
    return out


def analyse(doc) -> list[dict]:
    """Offer this document's low-confidence lines to TrOCR. Returns the readings; never raises a finding."""
    if doc.modality == "digital_pdf":
        doc.capabilities["handwriting"] = "n/a (born-digital text is read from the file)"
        return []
    st = status()
    if st != "ok":
        doc.capabilities["handwriting"] = st
        return []
    import cv2
    crops, meta = [], []
    for pi, P in enumerate(doc.pages):
        img = None
        for ln in P.lines:
            ws = [w for w in ln.words if w.text.strip()]
            if not ws or np.mean([w.conf for w in ws]) >= LOW_CONF:
                continue
            if img is None:
                img = cv2.cvtColor(cv2.imread(P.image_path), cv2.COLOR_BGR2RGB)
            x0, y0, x1, y1 = (int(v) for v in ln.bbox)
            pad = max(4, (y1 - y0) // 4)
            crop = img[max(0, y0 - pad):y1 + pad, max(0, x0 - pad):x1 + pad]
            if crop.size == 0 or crop.shape[0] < 8 or crop.shape[1] < 8:
                continue
            crops.append(crop)
            meta.append({"page": pi, "bbox": [x0, y0, x1, y1], "tesseract": " ".join(w.text for w in ws),
                         "tesseract_confidence": round(float(np.mean([w.conf for w in ws])), 3)})
            if len(crops) >= MAX_LINES:
                break
        if len(crops) >= MAX_LINES:
            break
    readings = []
    for m, (text, conf) in zip(meta, read_lines(crops)):
        readings.append(dict(m, trocr=text, trocr_confidence=conf))
    doc.structure["handwriting"] = readings
    doc.capabilities["handwriting"] = (f"ok ({len(readings)} low-confidence line(s) re-read by TrOCR; "
                                       "readings shown, not used by the rules)")
    return readings
