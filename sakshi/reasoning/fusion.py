"""Evidence fusion and the epistemic ladder.

  OBSERVATION            a sensor reading; nothing rule-breaking, or fully explained by an innocent cause
  INCONSISTENCY          a rule broke or an anomaly is localized, but an innocent cause is still plausible
                         or only one independent line of evidence supports it
  POTENTIAL_MANIPULATION independent lines of evidence (visual / file structure / internal arithmetic /
                         external records) converge on the same field, or a smoking gun, AND every
                         testable innocent explanation was ruled out

Severity is a score, not a gate: a lone smoking gun still
surfaces loudly; two or more independent witnesses raise it further.
SAKSHI never outputs "fraud". Decisions stay with the analyst.
"""
from __future__ import annotations

from ..models import Evidence, Finding, Tier
from . import devils_advocate

OBS_ONLY = {"metadata_dates", "incremental_update", "hidden_text", "duplicate_field", "ocr_self_heal",
            "salary_pass_through", "same_amount_in_out", "salary_variation", "cross_case_resubmission",
            "scan_annotation", "unreadable_field",
            "cross_case_reused_by_other", "statement_unverified", "digital_signature_info"}
# Visual evidence is split by the physics it measures (v1.0). Pixel statistics
# (sensor noise, duplication, compression) count as ONE witness because one paste moves them all together.
PHYSICS = {"noise_inconsistency": "pixel", "copy_move": "pixel", "zero_variance_patch": "pixel",
           "compression_ghost": "pixel", "scan_clone": "pixel",
           "glyph_outlier": "typography", "font_mix": "typography", "intra_token_font": "typography",
           "layout_rhythm_break": "geometry", "signature_placement": "geometry", "signature_missing": "geometry",
           "signature_identical": "signature", "optics_outlier": "optics",
           "cross_case_photo_reuse": "cross_case", "cross_case_identifier_reuse": "cross_case",
           "cross_case_signature_reuse": "cross_case", "cross_case_file_reuse": "cross_case"}
INDEPENDENT = {"pixel", "optics", "typography", "geometry", "signature", "file_structure", "logical", "cross_document",
               "identity", "pattern", "statutory", "cross_case", "issuer"}


def family_of(f) -> set:
    if f.sensor == "repair_solver" and f.repair.get("families"):
        return set(f.repair["families"])
    return {PHYSICS.get(f.check, f.family)}


def _overlap(a, b) -> float:
    x0, y0, x1, y1 = max(a[0], b[0]), max(a[1], b[1]), min(a[2], b[2]), min(a[3], b[3])
    if x1 <= x0 or y1 <= y0:
        return 0.0
    inter = (x1 - x0) * (y1 - y0)
    small = min((a[2] - a[0]) * (a[3] - a[1]), (b[2] - b[0]) * (b[3] - b[1]))
    return inter / small if small > 0 else 0.0


def attach_fields(findings: list[Finding], fields: dict):
    for f in findings:
        if f.fields:
            continue
        hits = []
        for ev in f.evidence:
            for k, fld in fields.items():
                if fld.doc_id == ev.doc_id and fld.page == ev.page and _overlap(fld.bbox, ev.bbox) > 0.3:
                    if k not in hits:
                        hits.append(k)
        f.fields = hits


def fuse(findings: list[Finding], docs: dict, ctx: dict, new_id) -> list[Finding]:
    fields = ctx["fields"]
    attach_fields(findings, fields)
    # a repair contested by income triangulation stands again if pixel/file evidence independently backs it
    touched = {k for f in findings if f.family in ("visual", "file_structure") for k in f.fields}
    for f in findings:
        if f.repair.get("contested") and f.fields and f.fields[0] in touched:
            f.repair["contested"] = False
            f.repair["uncontested_by"] = "independent pixel or file-structure evidence on the same field"
    # 1) innocent explanations
    for f in findings:
        f.benign = devils_advocate.run(f, docs, ctx)
    # 2) which independent evidence families touch each field
    fam_by_field = {}
    for f in findings:
        if any(b.result == "explains" for b in f.benign) or f.check in OBS_ONLY:
            continue
        fams = family_of(f)
        for k in f.fields:
            fam_by_field.setdefault(k, {}).setdefault(f.id, set()).update(fams)
    # copy-move names two glyphs; the suspect is the one whose field breaks rules
    for f in findings:
        if f.check == "copy_move" and len(f.fields) >= 2:
            ranked = sorted(f.fields, key=lambda k: -len(fam_by_field.get(k, {})))
            f.fields = ranked
            f.repair["suspect_field"] = ranked[0]
    # 3) tiers
    for f in findings:
        if f.tier == Tier.OBSERVATION and f.repair.get("equivalent"):
            continue
        res = {b.result for b in f.benign}
        if "explains" in res or f.check in OBS_ONLY:
            f.tier = Tier.OBSERVATION
            continue
        if f.check == "signature_identical" and f.repair.get("both_digital"):
            f.tier = Tier.OBSERVATION
            continue
        f.tier = Tier.INCONSISTENCY
        if "plausible" in res:
            continue
        fams, others = set(), set()
        for k in f.fields[:1] if f.check == "copy_move" else f.fields:
            for fid, fs in fam_by_field.get(k, {}).items():
                fams |= fs
                if fid != f.id:
                    others.add(fid)
        fams |= family_of(f)
        f.corroborated_by = sorted(others)
        claim_only = f.repair.get("claim") and not (fams & {"visual", "file_structure"})
        if claim_only:
            continue  # a false declaration is not a manipulated document
        if f.smoking_gun or len(fams & INDEPENDENT) >= 2:
            # weak sensors (alignment, typography) corroborate but cannot lead on their own
            # (a 7px shift alone is not evidence of manipulation)
            strong = f.smoking_gun or f.sensor == "repair_solver" or f.confidence >= 0.8
            if f.localized and strong:
                f.tier = Tier.POTENTIAL_MANIPULATION
            elif f.localized:
                f.repair["supports"] = True
    # 4) document-level assessment: several independent anomalies on one document
    extra = []
    for d in docs.values():
        mine = [f for f in findings if d.doc_id in f.docs and f.tier != Tier.OBSERVATION
                and (len(f.docs) == 1 or any(fields[k].doc_id == d.doc_id for k in f.fields)
                     or d.doc_id in f.repair.get("target_docs", []))]
        fams = {fm for f in mine for fm in family_of(f)}
        if len(mine) >= 3 and len(fams) >= 2:
            clean = [f for f in mine if not any(b.result == "plausible" for b in f.benign)]
            tier = Tier.POTENTIAL_MANIPULATION if len(clean) >= 2 else Tier.INCONSISTENCY
            extra.append(Finding(
                id=new_id(), check="document_assessment", family="fusion", sensor="fusion",
                title=f"{d.filename}: {len(mine)} independent anomalies across {len(fams)} evidence families",
                detail="Findings on this document: " + "; ".join(f"[{f.id}] {f.title}" for f in mine) + ".",
                tier=tier, confidence=0.85, localized=True,
                evidence=[Evidence(d.doc_id, 0, (0, 0, d.pages[0].width, d.pages[0].height), "whole document")],
                docs=[d.doc_id], corroborated_by=[f.id for f in mine],
                verify_next="Treat this document as unverified until obtained from its issuer through an independent channel."))
    findings += extra
    # 5) severity
    for f in findings:
        base = {Tier.OBSERVATION: 10, Tier.INCONSISTENCY: 40, Tier.POTENTIAL_MANIPULATION: 70}[f.tier]
        fams = set()
        for k in f.fields:
            for fs in fam_by_field.get(k, {}).values():
                fams |= fs
        f.severity = int(min(100, base + 8 * max(0, len(fams) - 1) + (10 if f.smoking_gun else 0) + round(8 * f.confidence)))
    for f in findings:
        if f.family == "visual":
            f.family = PHYSICS.get(f.check, "visual")  # show which physics a visual witness measured
    findings.sort(key=lambda f: (-f.severity, not f.smoking_gun, f.id))
    return findings


def threads(findings: list[Finding], fields: dict, docs: dict) -> list[dict]:
    """Group related findings into investigation threads."""
    act = [f for f in findings if f.tier != Tier.OBSERVATION and f.check != "document_assessment"]
    parent = {f.id: f.id for f in act}

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    by_key = {}
    for f in act:
        keys = set(f.fields)
        if f.repair.get("diagnosis"):
            keys.add(f.repair["diagnosis"])
        for k in keys:
            by_key.setdefault(k, []).append(f.id)
    for ids in by_key.values():
        for a in ids[1:]:
            parent[find(a)] = find(ids[0])
    groups = {}
    for f in act:
        groups.setdefault(find(f.id), []).append(f)
    out = []
    for g in groups.values():
        g.sort(key=lambda f: -f.severity)
        top = g[0]
        reps = [f for f in g if f.sensor == "repair_solver" and "proposed" in f.repair]
        drows = [f for f in g if f.check == "deleted_row"]
        if reps:
            title = "Consistent only if: " + "; ".join(
                f"{f.title.split(' reads ')[0]} were {f.repair['proposed']:,.2f} (reads {f.repair['current']:,.2f})" for f in reps)
        elif drows:
            title = "Consistent only if a removed row is restored: " + "; ".join(
                f"{f.repair['deleted_amount']:,.2f} debit in {f.repair['month']}" for f in drows)
        else:
            title = top.title
        tier = max((f.tier for f in g), key=lambda t: ["OBSERVATION", "INCONSISTENCY", "POTENTIAL_MANIPULATION"].index(t.value))
        out.append({"title": title, "lead": top.title, "tier": tier.value, "severity": top.severity, "findings": [f.id for f in g],
                    "docs": sorted({d for f in g for d in f.docs}),
                    "families": sorted({fm for f in g for fm in family_of(f)}),
                    "recovered": next((f.repair.get("proposed") or f.repair.get("recovered_value") or f.repair.get("deleted_amount")
                                       for f in g if f.repair.get("proposed") is not None or f.repair.get("recovered_value")
                                       or f.repair.get("deleted_amount")), None)})
    out.sort(key=lambda t: -t["severity"])
    return out
