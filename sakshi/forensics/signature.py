"""Signature analysis: detection, placement, cross-document identity.

Wet signatures vary every time a person signs. Two signatures whose stroke
shapes are near-identical across documents mean one was reproduced (scanned,
copied, pasted). Gemini's red-team guard: a signature image inserted by
software into two born-digital documents from the same issuer *is* expected
to be identical, so identity is only escalated when at least one copy is on a
scanned page (a supposed wet signature).
"""
from __future__ import annotations

import re

import cv2
import numpy as np
from skimage.morphology import skeletonize

from ..models import Document, Evidence, Finding

LABEL_RE = re.compile(r"^(for\s.*)?(authori[sz]ed\s+)?(signatory|signature)(\s+of\s+[a-z ]+)?\s*:?$", re.I)


def detect(doc: Document, ev_dir) -> list[dict]:
    sigs = []
    for P in doc.pages:
        bgr = cv2.imread(P.image_path)
        hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)
        b, g, r = [bgr[:, :, i].astype(np.int16) for i in range(3)]
        blue = ((hsv[:, :, 0] >= 95) & (hsv[:, :, 0] <= 135) & (hsv[:, :, 1] > 70) & (hsv[:, :, 2] < 230)
                & (b - r > 40)).astype(np.uint8)
        blue = cv2.morphologyEx(blue, cv2.MORPH_OPEN, np.ones((2, 2), np.uint8))
        grown = cv2.dilate(blue, np.ones((41, 41), np.uint8))
        n, lab, st, _ = cv2.connectedComponentsWithStats(grown, connectivity=8)
        for i in range(1, n):
            x, y, w, h, area = st[i]
            ink = blue[y:y + h, x:x + w] & (lab[y:y + h, x:x + w] == i)
            if ink.sum() < 150 or w < 60 or h < 20:
                continue
            # a solid blue block (header band, photo background) is not a signature
            if ink.sum() > 0.35 * w * h:
                continue
            sk = skeletonize(ink > 0).sum()
            if sk == 0 or ink.sum() / sk > 7.0:
                continue  # thick filled shapes (photo, logo), not pen strokes
            ys, xs = np.nonzero(ink)
            bb = (x + xs.min(), y + ys.min(), x + xs.max() + 1, y + ys.max() + 1)
            mask = ink[ys.min():ys.max() + 1, xs.min():xs.max() + 1].astype(np.uint8)
            crop_path = ev_dir / f"{doc.doc_id}_p{P.index}_sig{len(sigs)}.png"
            cv2.imwrite(str(crop_path), bgr[bb[1] - 6:bb[3] + 6, bb[0] - 6:bb[2] + 6])
            sigs.append({"doc": doc.doc_id, "page": P.index, "bbox": tuple(float(v) for v in bb), "mask": mask,
                         "crop": str(crop_path), "modality": doc.modality})
    doc.structure["signatures"] = [{"page": s["page"], "bbox": s["bbox"], "crop": s["crop"]} for s in sigs]
    return sigs


def placement(doc: Document, sigs: list[dict], new_id) -> list[Finding]:
    out = []
    for P in doc.pages:
        labels = [l for l in P.lines if LABEL_RE.search(l.text.strip()) and len(l.text) < 45]
        mine = [s for s in sigs if s["page"] == P.index]
        for l in labels:
            near = [s for s in mine if -40 < l.bbox[1] - s["bbox"][3] < 260 and s["bbox"][0] < l.bbox[2] + 250
                    and s["bbox"][2] > l.bbox[0] - 250]
            if not near:
                out.append(Finding(
                    id=new_id(), check="signature_missing", family="visual", sensor="signature",
                    title=f"No signature found near '{l.text.strip()}'",
                    detail="The document has a signature caption but no ink strokes in the expected place. "
                           "Black-ink signatures are not detected by this prototype (blue-ink detector).",
                    confidence=0.45, localized=True,
                    evidence=[Evidence(doc.doc_id, P.index, l.bbox, "signature caption without signature")],
                    docs=[doc.doc_id]))
        for s in mine:
            if labels and not any(-40 < l.bbox[1] - s["bbox"][3] < 260 for l in labels):
                out.append(Finding(
                    id=new_id(), check="signature_placement", family="visual", sensor="signature",
                    title="Signature is far from any signature caption",
                    detail="Signatures normally sit just above their caption. This one is elsewhere on the page.",
                    confidence=0.5, localized=True,
                    evidence=[Evidence(doc.doc_id, s["page"], s["bbox"], "misplaced signature", crop=s["crop"])],
                    docs=[doc.doc_id]))
    return out


def similarity(a: np.ndarray, b: np.ndarray) -> float:
    """Shape similarity of two ink masks after normalizing position and scale (dilated IoU)."""
    ra = a.shape[1] / max(1, a.shape[0])
    rb = b.shape[1] / max(1, b.shape[0])
    if abs(ra - rb) / max(ra, rb) > 0.15:
        return 0.0
    size = (240, int(240 / ra)) if ra >= 1 else (int(96 * ra), 96)
    A = cv2.resize(a, size, interpolation=cv2.INTER_AREA) > 0
    B = cv2.resize(b, size, interpolation=cv2.INTER_AREA) > 0
    k = np.ones((3, 3), np.uint8)
    A = cv2.dilate(A.astype(np.uint8), k) > 0
    B = cv2.dilate(B.astype(np.uint8), k) > 0
    return float((A & B).sum() / max(1, (A | B).sum()))


def cross_document(all_sigs: list[dict], docs: dict, new_id) -> list[Finding]:
    out = []
    for i in range(len(all_sigs)):
        for j in range(i + 1, len(all_sigs)):
            a, b = all_sigs[i], all_sigs[j]
            if a["doc"] == b["doc"]:
                continue
            s = similarity(a["mask"], b["mask"])
            if s < 0.72:
                continue
            both_digital = a["modality"] == "digital_pdf" and b["modality"] == "digital_pdf"
            system_docs = {"salary_slip", "bank_statement"}
            both_system = docs[a["doc"]].doc_type in system_docs and docs[b["doc"]].doc_type in system_docs
            da, db = docs[a["doc"]], docs[b["doc"]]
            out.append(Finding(
                id=new_id(), check="signature_identical", family="visual", sensor="signature",
                title=(f"Signatures on {da.filename} and {db.filename} are shape-identical (similarity {s:.2f})"),
                detail=("Two signatures by the same signatory never match stroke for stroke; natural variation on "
                        "this dataset gives similarity around 0.3 to 0.6. "
                        + ("Both documents are born-digital, so a software-inserted signature image is expected."
                           if both_digital else
                           "At least one copy sits on a scanned page, i.e. it is presented as a wet signature, "
                           "yet it matches another document's signature exactly.")),
                confidence=round(0.5 + 0.45 * (s - 0.72) / 0.28, 2) if not both_digital else 0.3, localized=True,
                evidence=[Evidence(a["doc"], a["page"], a["bbox"], "signature A", crop=a["crop"]),
                          Evidence(b["doc"], b["page"], b["bbox"], "signature B", crop=b["crop"])],
                docs=[a["doc"], b["doc"]], repair={"similarity": round(s, 3), "both_digital": both_digital,
                                                   "both_system": both_system,
                                                   "target_docs": [x["doc"] for x in (a, b) if x["modality"] != "digital_pdf"]}))
    return out
