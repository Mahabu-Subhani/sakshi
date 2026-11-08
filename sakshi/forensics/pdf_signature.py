"""Digital signatures on PDFs (offline), with pyHanko.

Bank e-statements, e-payslips and Form 16 are often signed by the issuer. A signature answers two questions:

* Did anything change after signing? This needs no trust at all: the signed bytes either still match the
  signature or they do not, and anything appended after the signed revision is visible. A broken signature,
  or content changed after signing, is reported as a smoking gun.
* Who signed? A valid signature from an unknown certificate proves only that someone signed. The document is
  promoted to witness level L3 (issuer-signed) only when the signer's certificate chains to a trust anchor the
  deploying lender has configured (SAKSHI_TRUST_DIR, a folder of CA certificates; none ships with SAKSHI).

Revocation is not checked (offline; Indian e-statements rarely embed revocation data), and SAKSHI never says it is.
"""
from __future__ import annotations

import os
from pathlib import Path

from ..models import Evidence, Finding, Witness

TRUST_DIR_ENV = "SAKSHI_TRUST_DIR"


def trust_anchors() -> tuple[list, str]:
    folder = os.environ.get(TRUST_DIR_ENV, "")
    if not folder or not Path(folder).is_dir():
        return [], ""
    from asn1crypto import pem, x509
    certs = []
    for p in sorted(Path(folder).iterdir()):
        if p.suffix.lower() not in (".pem", ".crt", ".cer", ".der"):
            continue
        data = p.read_bytes()
        try:
            if pem.detect(data):
                certs += [x509.Certificate.load(der) for _, _, der in pem.unarmor(data, multiple=True)]
            else:
                certs.append(x509.Certificate.load(data))
        except Exception:
            continue  # an unreadable file in the trust folder is skipped, never trusted
    return certs, folder


def _widget_box(doc, field_name: str):
    """The signature field's rectangle on its page, in page pixels, if it has one."""
    try:
        from ..ingest import open_pdf
        pdf = open_pdf(doc.path)
        for i, pg in enumerate(pdf):
            for w in pg.widgets() or []:
                if w.field_name == field_name and i < len(doc.pages) and w.rect.width > 2:
                    k = doc.pages[i].width / pg.rect.width
                    r = w.rect
                    pdf.close()
                    return i, (r.x0 * k, r.y0 * k, r.x1 * k, r.y1 * k)
        pdf.close()
    except Exception:
        pass
    return None


def analyse(doc, new_id, passwords=()) -> list[Finding]:
    if not doc.path.lower().endswith(".pdf"):
        doc.capabilities["digital_signature"] = "n/a (not a PDF)"
        return []
    from pyhanko.pdf_utils.reader import PdfFileReader
    from pyhanko.sign.diff_analysis import ModificationLevel
    from pyhanko.sign.validation import validate_pdf_signature
    from pyhanko.sign.validation.status import SignatureCoverageLevel
    from pyhanko_certvalidator import ValidationContext

    import logging
    logging.getLogger("pyhanko").setLevel(logging.ERROR)  # an untrusted chain is an expected outcome, not an error
    logging.getLogger("pyhanko_certvalidator").setLevel(logging.ERROR)
    with open(doc.path, "rb") as fh:
        r = PdfFileReader(fh, strict=False)
        if r.encrypted:
            opened = False
            for pw in passwords or ():
                try:
                    if r.decrypt(pw.encode() if isinstance(pw, str) else pw).status.name != "FAILED":
                        opened = True
                        break
                except Exception:
                    continue
            if not opened:
                doc.capabilities["digital_signature"] = "not checked (encrypted file; no working password)"
                return []
        sigs = list(r.embedded_regular_signatures)
        if not sigs:
            doc.capabilities["digital_signature"] = "n/a (no digital signature)"
            doc.structure["digital_signature"] = {"signed": False}
            return []
        anchors, folder = trust_anchors()
        vc = ValidationContext(trust_roots=anchors, allow_fetching=False, revocation_mode="soft-fail")
        out, summary = [], []
        for es in sigs:
            try:
                st = validate_pdf_signature(es, signer_validation_context=vc)
            except Exception as e:
                summary.append({"field": str(es.field_name), "error": f"{type(e).__name__}: {e}"})
                continue
            cert = st.signing_cert
            signer = str(cert.subject.human_friendly) if cert else "unknown signer"
            issuer = str(cert.issuer.human_friendly) if cert else "unknown issuer"
            field_name = str(es.field_name)  # pyHanko's string object keeps a reference to the open file
            cov = st.coverage
            mod = st.modification_level
            whole = cov == SignatureCoverageLevel.ENTIRE_FILE
            changed = (not whole) and mod is not None and mod > ModificationLevel.FORM_FILLING
            info = {"field": field_name, "signer": signer, "issuer": issuer, "intact": bool(st.intact),
                    "valid": bool(st.valid), "trusted": bool(st.trusted), "coverage": str(cov.name) if cov else None,
                    "modification_level": str(mod.name) if mod else None, "trust_store": folder or None,
                    "revocation_checked": False}
            summary.append(info)
            loc = _widget_box(doc, field_name)
            P = doc.pages[0] if doc.pages else None
            page, box = loc if loc else (0, (0, 0, P.width, P.height) if P else (0, 0, 10, 10))
            ev = [Evidence(doc.doc_id, page, box, "digital signature" if loc else "signed document")]
            if not st.intact or not st.valid:
                out.append(Finding(
                    id=new_id(), check="signature_broken", family="file_structure", sensor="pdf_signature",
                    title=f"{doc.filename}: the digital signature of {signer} no longer matches the signed content",
                    detail="The bytes covered by the signature were changed after signing, or the signature itself "
                           "is invalid. A document cannot be edited without breaking its issuer's signature.",
                    confidence=0.97, localized=True, smoking_gun=True, evidence=ev, docs=[doc.doc_id],
                    repair={"signature": info}))
            elif changed:
                gun = mod == ModificationLevel.OTHER
                out.append(Finding(
                    id=new_id(), check="signed_then_modified", family="file_structure", sensor="pdf_signature",
                    title=f"{doc.filename}: changed after it was signed by {signer} "
                          f"({'content' if gun else 'annotations'} added after the signature)",
                    detail="The signature is intact for the revision that was signed, but later revisions were "
                           "appended. What a reader sees is not what the issuer signed.",
                    confidence=0.95 if gun else 0.75, localized=True, smoking_gun=gun, evidence=ev,
                    docs=[doc.doc_id], repair={"signature": info}))
            else:
                trusted = bool(st.trusted)
                if trusted and doc.witness < Witness.L3_SIGNED:
                    doc.witness = int(Witness.L3_SIGNED)
                out.append(Finding(
                    id=new_id(), check="digital_signature_info", family="file_structure", sensor="pdf_signature",
                    title=f"{doc.filename}: digitally signed by {signer}; "
                          + ("the certificate chains to a configured trust anchor, so the document is treated as "
                             "issuer-signed (L3)" if trusted else
                             "the signature is intact but its certificate is not trusted here, so it adds no weight"),
                    detail=f"Certificate issuer: {issuer}. Covers {cov.name.lower().replace('_', ' ') if cov else 'an unclear range'}. "
                           "Revocation was not checked (offline).",
                    confidence=0.9, localized=bool(loc), evidence=ev, docs=[doc.doc_id], repair={"signature": info}))
        doc.structure["digital_signature"] = {"signed": True, "signatures": summary}
        ok = [s for s in summary if s.get("intact") and s.get("valid")]
        doc.capabilities["digital_signature"] = (
            f"ok ({len(summary)} signature(s); {sum(s['trusted'] for s in ok)} trusted; revocation not checked)")
        return out
