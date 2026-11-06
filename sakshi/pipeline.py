"""End-to-end investigation pipeline.

Submission -> Classification -> OCR & Extraction -> Structure -> Visual forensics ->
Contextual verification -> Cross-document correlation -> Anomaly investigation ->
Evidence generation -> Investigation dossier

Every stage is logged to a hash-chained audit trail. Any sensor that fails is
recorded as unavailable for that document instead of crashing the case.
"""
from __future__ import annotations

import itertools
import json
import time
import traceback
from dataclasses import asdict
from pathlib import Path

import cv2
import numpy as np

from . import __version__
from .audit import AuditLog
from .classify import LABELS, classify
from .extract import extract
from .fonts import label_font
from .forensics import copy_move, glyphs, layout, noise, pdf_layers, raster, scan_overlay, signature
from .ingest import MAX_PAGES, UnsupportedInput, dual_read, forget_passwords, group_lines, ingest, make_reocr
from .models import Tier
from .reasoning import coverage as cov
from .reasoning import engine, fusion, narrator, selftest

STAGES = ["Document submission", "Document classification", "OCR & information extraction", "Structural understanding",
          "Visual forensic analysis", "Contextual verification", "Cross-document correlation", "Anomaly investigation",
          "Evidence generation", "Investigation dossier"]


def _crop(page_img_path: str, bbox, out: Path, color=(40, 40, 230)):
    img = cv2.imread(page_img_path)
    H, W = img.shape[:2]
    x0, y0, x1, y1 = (int(v) for v in bbox)
    m = max(30, int(0.25 * max(x1 - x0, y1 - y0)))
    cx0, cy0, cx1, cy1 = max(0, x0 - m), max(0, y0 - m), min(W, x1 + m), min(H, y1 + m)
    c = img[cy0:cy1, cx0:cx1].copy()
    cv2.rectangle(c, (x0 - cx0, y0 - cy0), (x1 - cx0, y1 - cy0), color, 2)
    if c.shape[1] > 900:
        s = 900 / c.shape[1]
        c = cv2.resize(c, None, fx=s, fy=s, interpolation=cv2.INTER_AREA)
    cv2.imwrite(str(out), c, [cv2.IMWRITE_JPEG_QUALITY, 82])
    return str(out)


def _portable(text: str, out: Path) -> str:
    """dossier.json stores paths relative to the case folder, so a shared dossier leaks no local paths."""
    for pre in {str(out.resolve()) + "/", str(out) + "/"}:
        text = text.replace(json.dumps(pre)[1:-1], "")
    return text


def _reconstruction(page_img_path: str, bbox, text: str, out: Path) -> str | None:
    """Side-by-side 'as submitted' vs 'expected value reconstruction' (Gemini 4 Argon's labelling rule:
    it must never look like generated evidence)."""
    from PIL import Image, ImageDraw
    try:
        img = Image.open(page_img_path).convert("RGB")
        W, H = img.size
        x0, y0, x1, y1 = (int(v) for v in bbox)
        m = max(40, int(1.2 * (y1 - y0)))
        cx0, cy0, cx1, cy1 = max(0, x0 - 4 * m), max(0, y0 - m), min(W, x1 + 2 * m), min(H, y1 + m)
        crop = img.crop((cx0, cy0, cx1, cy1))
        a = crop.copy()
        da = ImageDraw.Draw(a)
        da.rectangle([x0 - cx0 - 3, y0 - cy0 - 3, x1 - cx0 + 3, y1 - cy0 + 3], outline=(200, 40, 40), width=3)
        b = crop.copy()
        db = ImageDraw.Draw(b)
        ring = np.array(crop)[max(0, y0 - cy0 - 10):max(1, y0 - cy0 - 3), x0 - cx0:x1 - cx0].reshape(-1, 3)
        paper = tuple(int(v) for v in np.median(ring, axis=0)) if ring.size else (245, 245, 245)
        db.rectangle([x0 - cx0 - 2, y0 - cy0 - 2, x1 - cx0 + 2, y1 - cy0 + 2], fill=paper)
        size = max(10, int((y1 - y0) * 0.95))
        font, small = label_font(size), label_font(18, bold=True)
        db.text((x0 - cx0, y0 - cy0 - int(size * 0.12)), text, font=font, fill=(25, 90, 170))
        db.rectangle([x0 - cx0 - 4, y0 - cy0 - 4, x0 - cx0 + font.getlength(text) + 4, y1 - cy0 + 4], outline=(25, 90, 170), width=2)
        bar = 30
        canvas = Image.new("RGB", (a.width * 2 + 12, a.height + bar), (255, 255, 255))
        canvas.paste(a, (0, bar))
        canvas.paste(b, (a.width + 12, bar))
        dc = ImageDraw.Draw(canvas)
        dc.text((6, 6), "AS SUBMITTED", font=small, fill=(160, 30, 30))
        dc.text((a.width + 18, 6), "EXPECTED VALUE RECONSTRUCTION - not evidence", font=small, fill=(25, 90, 170))
        if canvas.width > 1400:
            canvas = canvas.resize((1400, int(canvas.height * 1400 / canvas.width)))
        canvas.save(str(out), quality=85)
        return str(out)
    except Exception:
        return None


def run_case(paths: list[str], out_dir: str | Path, case_id: str | None = None, progress=None,
             lang: str = "eng", html: bool = True, registry_path: str | Path | None = None,
             passwords: list[str] | None = None) -> dict:
    try:
        return _run_case(paths, out_dir, case_id, progress, lang, html, registry_path, passwords)
    finally:
        forget_passwords(paths)  # also when the case fails part-way


def _run_case(paths, out_dir, case_id, progress, lang, html, registry_path, passwords) -> dict:
    import os
    registry_path = registry_path or os.environ.get("SAKSHI_REGISTRY") or None
    t0 = time.time()
    out = Path(out_dir)
    (out / "pages").mkdir(parents=True, exist_ok=True)
    (out / "evidence").mkdir(parents=True, exist_ok=True)
    case_id = case_id or time.strftime("CASE-%Y%m%d-%H%M%S")
    audit_path = out / "audit.jsonl"
    if audit_path.exists():
        audit_path.unlink()
    audit = AuditLog(audit_path, case_id)
    cnt = itertools.count(1)
    new_id = lambda: f"F{next(cnt):03d}"  # noqa: E731

    def step(i, msg=""):
        audit.log("stage", stage=STAGES[i], note=msg)
        if progress:
            progress(i, len(STAGES), STAGES[i], msg)

    # 1 submission
    step(0, f"{len(paths)} file(s)")
    audit.log("case_opened", files=[Path(p).name for p in paths], sakshi_version=__version__)
    docs, rejected = {}, []
    for i, p in enumerate(paths):
        did = f"D{i + 1}"
        try:
            d = ingest(p, did, out / "pages", lang=lang, passwords=passwords or ())
            docs[did] = d
            audit.log("document_ingested", doc_id=did, filename=d.filename, sha256=d.sha256, modality=d.modality,
                      pages=len(d.pages))
        except UnsupportedInput as e:
            rejected.append({"file": Path(p).name, "reason": str(e)})
            audit.log("document_rejected", file=Path(p).name, reason=str(e))
        except Exception as e:
            rejected.append({"file": Path(p).name, "reason": f"unexpected error during ingestion: {e}"})
            audit.log("document_rejected", file=Path(p).name, reason=traceback.format_exc(limit=2))
    findings = []

    def safe(name, d, fn, *a):
        try:
            return fn(*a) or []
        except Exception as e:
            d.capabilities[name] = f"error ({type(e).__name__}: {e})"
            audit.log("sensor_failed", doc_id=d.doc_id, sensor=name, error=traceback.format_exc(limit=3))
            return []

    def first_pages(fn, *ds):
        """Run a pixel sensor on the first MAX_PAGES pages only; later pages are read but not pixel-scanned."""
        def run(*a):
            full = [d.pages for d in ds]
            for d in ds:
                d.pages = d.pages[:MAX_PAGES]
            try:
                return fn(*a)
            finally:
                for d, pages in zip(ds, full):
                    d.pages = pages
        return run

    # file-structure archaeology runs first: occluded text must not be read as visible text
    for d in docs.values():
        findings += safe("pdf_layers", d, pdf_layers.analyse, d, new_id)
        for P in d.pages:
            P.lines = group_lines(P.words)
    # 2 classification
    step(1)
    for d in docs.values():
        classify(d)
        audit.log("document_classified", doc_id=d.doc_id, type=d.doc_type, confidence=d.type_confidence,
                  cues=d.type_evidence, witness_level=d.witness)
    # 3 extraction
    step(2)
    for d in docs.values():
        safe("dual_read", d, dual_read, d, lang)
        try:
            extract(d, reocr=make_reocr(d))
        except Exception as e:
            d.notes.append(f"Extraction failed: {e}")
            audit.log("extraction_failed", doc_id=d.doc_id, error=str(e))
        audit.log("fields_extracted", doc_id=d.doc_id, n_fields=len(d.fields),
                  n_rows=len(d.tables.get("transactions", [])), missing=d.structure.get("missing", []))
    # 4 structure
    step(3)
    # 5 visual forensics
    step(4)
    sigs = []
    for d in docs.values():
        findings += safe("noise", d, first_pages(noise.analyse, d), d, new_id, out / "evidence")
        findings += safe("copy_move", d, first_pages(copy_move.analyse, d), d, new_id)
        findings += safe("glyphs", d, first_pages(glyphs.analyse, d), d, new_id)
        findings += safe("layout", d, layout.analyse, d, new_id)
        findings += safe("compression", d, first_pages(raster.erasure_and_ghosts, d), d, new_id)
        findings += safe("intra_token_font", d, first_pages(raster.intra_token_font, d), d, new_id)
        findings += safe("optics", d, first_pages(raster.optics_outliers, d), d, new_id)
        findings += safe("scan_overlay", d, scan_overlay.analyse, d, new_id, out / "evidence")
        s = safe("signature", d, first_pages(signature.detect, d), d, out / "evidence")
        sigs += s
        findings += safe("signature", d, first_pages(signature.placement, d), d, s, new_id)
        d.capabilities.setdefault("signature", f"ok ({len(s)} blue-ink signature(s))")
        st = first_pages(selftest.run, d)(d)
        d.capabilities["self_test"] = st
        audit.log("visual_forensics", doc_id=d.doc_id, capabilities=d.capabilities)
    # 6/7 contextual + cross-document
    step(5)
    try:
        findings += first_pages(raster.scan_clones, *docs.values())(docs, new_id)
    except Exception as e:
        audit.log("sensor_failed", sensor="scan_clone", error=str(e))
    try:
        findings += signature.cross_document(sigs, docs, new_id)
    except Exception as e:
        audit.log("sensor_failed", sensor="signature_cross", error=str(e))
    step(6)
    logical, ctx = engine.run(docs, new_id)
    findings += logical
    reg, fp = None, None
    if registry_path:
        try:
            from .registry import Registry, fingerprint
            reg = Registry(registry_path)
            fp = fingerprint(case_id, docs, sigs)
            hits = reg.check(fp, docs, new_id)
            findings += hits
            audit.log("cross_case_check", registry=str(registry_path), prior_cases=len(reg.data["cases"]), matches=len(hits))
        except Exception as e:
            audit.log("sensor_failed", sensor="registry", error=str(e))
    # 8 anomaly investigation
    step(7)
    findings = fusion.fuse(findings, docs, ctx, new_id)
    assessments = [f for f in findings if f.check == "document_assessment"]
    findings = [f for f in findings if f.check != "document_assessment"]
    threads = fusion.threads(findings, ctx["fields"], docs)
    coverage = cov.coverage(ctx, docs)
    # 9 evidence
    step(8)
    for f in findings + assessments:
        for j, ev in enumerate(f.evidence):
            d = docs.get(ev.doc_id)
            if not d or ev.kind in ("file", "peel") or ev.page >= len(d.pages):
                continue
            P = d.pages[ev.page]
            if (ev.bbox[2] - ev.bbox[0]) * (ev.bbox[3] - ev.bbox[1]) > 0.6 * P.width * P.height:
                continue
            col = {Tier.POTENTIAL_MANIPULATION: (40, 40, 220), Tier.INCONSISTENCY: (0, 140, 230)}.get(f.tier, (180, 120, 0))
            ev.crop = _crop(P.image_path, ev.bbox, out / "evidence" / f"{f.id}_{j}.jpg", col)
        # counterfactual rendering for findings that reconstruct a value
        val = None
        if f.sensor == "repair_solver" and f.repair.get("proposed") is not None and not f.repair.get("contested"):
            val = f.repair["proposed"]
        elif f.check == "occluded_text" and f.repair.get("recovered_value"):
            val = f.repair["recovered_value"]
        if val is not None and f.evidence:
            ev0 = f.evidence[0]
            d = docs.get(ev0.doc_id)
            if d and ev0.page < len(d.pages):
                txt = val if isinstance(val, str) else engine.fmt(float(val))
                rp = _reconstruction(d.pages[ev0.page].image_path, ev0.bbox, txt, out / "evidence" / f"{f.id}_recon.jpg")
                if rp:
                    from .models import Evidence as _Ev
                    f.evidence.append(_Ev(ev0.doc_id, ev0.page, ev0.bbox,
                                          f"expected value reconstruction: {txt} (not evidence; for comparison only)",
                                          kind="reconstruction", crop=rp, value=txt))
        audit.log("finding_recorded", id=f.id, check=f.check, tier=f.tier.value, severity=f.severity,
                  fields=f.fields, evidence=[(e.doc_id, e.page, [round(v) for v in e.bbox]) for e in f.evidence])
    # 10 dossier
    step(9)
    summary = narrator.deterministic(findings, threads, docs)
    llm = narrator.llm(summary, findings)
    ok, msg = audit.verify()
    dossier = build_dossier(case_id, docs, findings, threads, ctx, coverage, rejected, summary, llm,
                            {"verified": ok, "message": msg}, time.time() - t0)
    dossier["document_assessments"] = [f.to_dict() for f in assessments]
    dossier["cross_case"] = {"enabled": bool(reg), "prior_cases": len(reg.data["cases"]) if reg else 0}
    if reg and fp:
        reg.register(fp)
        audit.log("case_registered", registry=str(registry_path))
    (out / "dossier.json").write_text(_portable(json.dumps(dossier, indent=1, default=str), out))
    audit.log("dossier_generated", n_findings=len(findings), seconds=round(time.time() - t0, 1))
    dossier["audit"]["records"] = audit.records()
    ok, msg = audit.verify()
    dossier["audit"].update({"verified": ok, "message": msg})
    (out / "dossier.json").write_text(_portable(json.dumps(dossier, indent=1, default=str), out))
    if html:
        from .dossier.render import render
        render(dossier, out / "dossier.html")
    return dossier


def claim_graph(docs, ctx, findings) -> dict:
    fields = ctx["fields"]
    blamed = {k for f in findings if f.tier != Tier.OBSERVATION for k in f.fields}
    nodes = [{"id": d.doc_id, "type": "doc", "label": d.filename, "doc_type": d.doc_type, "witness": d.witness}
             for d in docs.values()]
    edges = []
    attrs = {}
    for eq in ctx["rules"].equality:
        attrs[eq.attr] = eq.refs
    inc = [inv for inv in ctx["rules"].linear if inv.id.startswith(("X1", "X2", "X3"))]
    if inc:
        attrs["monthly_income"] = sorted({k for inv in inc for k in inv.coef})
    emi = [inv for inv in ctx["rules"].linear if inv.id.startswith("X4")]
    if emi:
        attrs["monthly_emi"] = sorted({k for inv in emi for k in inv.coef})
    for a, refs in attrs.items():
        nodes.append({"id": f"A:{a}", "type": "attr", "label": a.replace("_", " ")})
        for r in refs:
            f = fields[r]
            edges.append({"from": f.doc_id, "to": f"A:{a}", "value": f.raw, "ref": r,
                          "status": "conflict" if r in blamed else "agree"})
    return {"nodes": nodes, "edges": edges}


def build_dossier(case_id, docs, findings, threads, ctx, coverage, rejected, summary, llm, audit, secs) -> dict:
    from .reasoning.invariants import Linear
    rules = []
    vals = ctx["vals"]
    for inv in ctx["rules"].linear:
        if all(k in vals for k in inv.coef):
            r = inv.residual(vals)
            rules.append({"id": inv.id, "text": inv.text, "status": "broken" if abs(r) > inv.tol else "holds",
                          "residual": round(r, 2), "scope": inv.scope, "check": inv.check, "soft": inv.soft})
    for st in ctx["rules"].statutory:
        rules.append({"id": st["id"], "text": st["text"], "status": "holds" if st["ok"] else "broken",
                      "values": [ctx["fields"][k].raw for k in st["fields"]], "scope": "intra", "check": "statutory"})
    for eq in ctx["rules"].equality:
        from .reasoning.repair import equality_key
        keys = {equality_key(eq.kind, vals[r]) for r in eq.refs}
        rules.append({"id": eq.id, "text": eq.text, "status": "broken" if len(keys) > 1 else "holds",
                      "values": [ctx["fields"][r].raw for r in eq.refs], "scope": "cross", "check": "equality"})
    ddocs = []
    for d in docs.values():
        ddocs.append({
            "doc_id": d.doc_id, "filename": d.filename, "sha256": d.sha256, "modality": d.modality,
            "type": d.doc_type, "type_label": LABELS.get(d.doc_type, d.doc_type), "type_confidence": d.type_confidence,
            "type_evidence": d.type_evidence, "witness": d.witness, "pdf_meta": d.pdf_meta,
            "pages": [{"index": p.index, "image": p.image_path, "width": p.width, "height": p.height,
                       "skew_deg": round(p.skew_deg, 2), "noise_sigma": round(p.noise_sigma, 2),
                       "hidden_words": [w.text for w in getattr(p, "hidden_words", [])]} for p in d.pages],
            "fields": [asdict(f) for f in d.fields.values()],
            "tables": {"earnings": [asdict(f) for f in d.tables.get("earnings", [])],
                       "deductions": [asdict(f) for f in d.tables.get("deductions", [])],
                       "transactions": [{"date": r["date"].raw if r.get("date") else "", "description": r["description"],
                                         **{c: asdict(r[c]) for c in ("debit", "credit", "balance") if r.get(c)},
                                         "bbox": r["bbox"], "page": r["page"]}
                                        for r in d.tables.get("transactions", [])]},
            "structure": {k: v for k, v in d.structure.items()},
            "capabilities": d.capabilities, "notes": d.notes,
            "status": "processed",
        })
    n_pm = sum(1 for f in findings if f.tier == Tier.POTENTIAL_MANIPULATION)
    n_inc = sum(1 for f in findings if f.tier == Tier.INCONSISTENCY)
    return {
        "case_id": case_id, "generated_at": time.strftime("%Y-%m-%d %H:%M:%S %z"), "sakshi_version": __version__,
        "processing_seconds": round(secs, 1),
        "status": ("REFER: corroborated anomalies need human review" if n_pm else
                   "REVIEW: inconsistencies need explanation" if n_inc else "NO RULE-BREAKING ANOMALY FOUND (not proof of authenticity)"),
        "counts": {"potential_manipulation": n_pm, "inconsistency": n_inc,
                   "observation": sum(1 for f in findings if f.tier == Tier.OBSERVATION)},
        "summary": summary, "llm_summary": ({"text": llm[0], "model": llm[1]} if llm else None),
        "documents": ddocs, "rejected": rejected, "findings": [f.to_dict() for f in findings], "threads": threads,
        "diagnoses": ctx["diagnoses"], "rules": rules,
        "expectations": ctx["rules"].expectations, "coverage": coverage, "claim_graph": claim_graph(docs, ctx, findings),
        "audit": audit, "limitations": LIMITATIONS,
    }


LIMITATIONS = [
    "Handwritten text is not recognised (Tesseract printed-text model). Handwritten fields are reported as missing, not verified.",
    "Signature detection looks for blue ink only; black-ink signatures are not detected or compared.",
    "Pixel forensics (noise, copy-move, typography) need a real scan with measurable sensor noise; they declare themselves blind on clean digital exports and screenshots.",
    "Copy-move detection compares digit glyphs only; larger copied regions (logos, stamps) are not searched.",
    "Extraction relies on common Indian labels (Net Pay, Gross Earnings, Statement of Account, ...). Unseen layouts fall back to generic label:value harvesting with fewer cross-checks.",
    "The repair solver handles linear rules and up to 3 simultaneous field changes. Forgeries consistent across every rule are only caught where an independent document disagrees.",
    "No issuer verification: SAKSHI cannot confirm a document with the bank, employer or registry. Witness level L3/L4 sources are modelled but not connected.",
    "Multi-page support is limited to the first 6 pages per document.",
    "Classification is keyword based and may label unusual documents as 'unknown'; contextual rules are then skipped for that document.",
    "Thresholds were set on synthetic data; they are documented in the code and need calibration on real, authorised samples before any production use.",
]
