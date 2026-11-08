"""Digital signatures on PDFs: integrity always, trust only through a configured trust store.

A test CA and an issuer certificate are generated in a temporary folder (no real CA is involved), the genuine
demo payslip is signed with them, and:

* with the CA in SAKSHI_TRUST_DIR the payslip becomes an issuer-signed witness (L3) and nothing is flagged;
* without a trust store the signature is reported as information only and the witness level stays L2;
* the signed payslip edited afterwards (white box and new net pay appended as an incremental update) is reported
  as changed after signing, at POTENTIAL MANIPULATION;
* one byte flipped inside the signed range makes the signature broken, at POTENTIAL MANIPULATION;
* the full genuine case with the signed payslip stays free of potential manipulation and inconsistencies.

    python tests/run_pdf_signatures.py
"""
import datetime as dt
import os
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from sakshi.pipeline import run_case  # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f"  ({detail})" if detail else ""), flush=True)


def make_ca(folder: Path):
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import NameOID
    now = dt.datetime.now(dt.timezone.utc)

    def name(cn):
        return x509.Name([x509.NameAttribute(NameOID.COUNTRY_NAME, "IN"),
                          x509.NameAttribute(NameOID.ORGANIZATION_NAME, "SAKSHI TEST ONLY"),
                          x509.NameAttribute(NameOID.COMMON_NAME, cn)])
    ca_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    ca = (x509.CertificateBuilder().subject_name(name("SAKSHI Test Root CA")).issuer_name(name("SAKSHI Test Root CA"))
          .public_key(ca_key.public_key()).serial_number(x509.random_serial_number())
          .not_valid_before(now - dt.timedelta(days=1)).not_valid_after(now + dt.timedelta(days=30))
          .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
          .add_extension(x509.KeyUsage(True, False, False, False, False, True, True, False, False), critical=True)
          .sign(ca_key, hashes.SHA256()))
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    leaf = (x509.CertificateBuilder().subject_name(name("Nimbus Analytics Payroll (test signer)"))
            .issuer_name(ca.subject).public_key(key.public_key()).serial_number(x509.random_serial_number())
            .not_valid_before(now - dt.timedelta(days=1)).not_valid_after(now + dt.timedelta(days=30))
            .add_extension(x509.KeyUsage(True, True, False, False, False, False, False, False, False), critical=True)
            .sign(ca_key, hashes.SHA256()))
    trust = folder / "trust"
    trust.mkdir()
    (trust / "test_root.pem").write_bytes(ca.public_bytes(serialization.Encoding.PEM))
    der = lambda c: c.public_bytes(serialization.Encoding.DER)  # noqa: E731
    kder = key.private_bytes(serialization.Encoding.DER, serialization.PrivateFormat.PKCS8,
                             serialization.NoEncryption())
    return trust, der(ca), der(leaf), kder


def sign(src: Path, dst: Path, ca_der, leaf_der, key_der):
    from asn1crypto import keys, x509
    from pyhanko.pdf_utils.incremental_writer import IncrementalPdfFileWriter
    from pyhanko.sign import fields, signers
    from pyhanko_certvalidator.registry import SimpleCertificateStore
    signer = signers.SimpleSigner(signing_cert=x509.Certificate.load(leaf_der),
                                  signing_key=keys.PrivateKeyInfo.load(key_der),
                                  cert_registry=SimpleCertificateStore.from_certs([x509.Certificate.load(ca_der)]))
    with open(src, "rb") as inf, open(dst, "wb") as outf:
        w = IncrementalPdfFileWriter(inf, strict=False)
        signers.sign_pdf(w, signers.PdfSignatureMetadata(field_name="IssuerSignature"), signer=signer, output=outf,
                         new_field_spec=fields.SigFieldSpec("IssuerSignature", box=(400, 60, 560, 110)))


def single(path, out, cid):
    d = run_case([str(path)], out, case_id=cid, html=False)
    sig = [f for f in d["findings"] if f["sensor"] == "pdf_signature"]
    return d, sig


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="sakshi_sig_"))
    old = os.environ.pop("SAKSHI_TRUST_DIR", None)
    try:
        trust, ca, leaf, key = make_ca(tmp)
        src = ROOT / "dataset/cases/case_genuine/01_payslip_oct2026.pdf"
        signed = tmp / "01_payslip_oct2026.pdf"
        sign(src, signed, ca, leaf, key)

        os.environ["SAKSHI_TRUST_DIR"] = str(trust)
        d, sig = single(signed, tmp / "trusted", "SIG-TRUSTED")
        doc = d["documents"][0]
        check("trusted signer: information finding, witness promoted to L3",
              [f["check"] for f in sig] == ["digital_signature_info"] and doc["witness"] == 3
              and "configured trust anchor" in sig[0]["title"], f"witness L{doc['witness']}")
        check("trusted signer: no inconsistency or potential manipulation",
              d["counts"]["potential_manipulation"] == 0 and d["counts"]["inconsistency"] == 0, str(d["counts"]))

        os.environ.pop("SAKSHI_TRUST_DIR")
        d, sig = single(signed, tmp / "untrusted", "SIG-UNTRUSTED")
        doc = d["documents"][0]
        check("no trust store: signature reported as information only, witness stays L2",
              [f["check"] for f in sig] == ["digital_signature_info"] and doc["witness"] == 2
              and "not trusted" in sig[0]["title"], f"witness L{doc['witness']}")

        import pymupdf
        edited = tmp / "edited" / "01_payslip_oct2026.pdf"
        edited.parent.mkdir()
        shutil.copy(signed, edited)
        pdf = pymupdf.open(edited)
        pg = pdf[0]
        hits = pg.search_for("68,500.00")
        r = hits[0] if hits else pymupdf.Rect(300, 400, 380, 415)
        pg.draw_rect(r, color=(1, 1, 1), fill=(1, 1, 1))
        pg.insert_text((r.x0, r.y1 - 2), "86,500.00", fontsize=9)
        pdf.saveIncr()
        pdf.close()
        d, sig = single(edited, tmp / "run_edited", "SIG-EDITED")
        f = [x for x in sig if x["check"] == "signed_then_modified"]
        check("edited after signing: reported at POTENTIAL MANIPULATION",
              len(f) == 1 and f[0]["tier"] == "POTENTIAL_MANIPULATION", f[0]["title"][:90] if f else str(sig))

        broken = tmp / "broken" / "01_payslip_oct2026.pdf"
        broken.parent.mkdir()
        data = bytearray(signed.read_bytes())
        i = data.index(b"%PDF-") + 10  # inside the header comment line, within the first signed byte range
        data[i] = (data[i] + 1) % 256 or 1
        broken.write_bytes(bytes(data))
        d, sig = single(broken, tmp / "run_broken", "SIG-BROKEN")
        f = [x for x in sig if x["check"] == "signature_broken"]
        check("one byte flipped inside the signed range: signature broken, POTENTIAL MANIPULATION",
              len(f) == 1 and f[0]["tier"] == "POTENTIAL_MANIPULATION", f[0]["title"][:90] if f else str(sig))

        os.environ["SAKSHI_TRUST_DIR"] = str(trust)
        case = tmp / "case"
        shutil.copytree(ROOT / "dataset/cases/case_genuine", case, ignore=shutil.ignore_patterns("MANIFEST*"))
        shutil.copy(signed, case / "01_payslip_oct2026.pdf")
        d = run_case(sorted(str(p) for p in case.iterdir()), tmp / "run_case", case_id="SIG-CASE", html=False)
        check("genuine case with the signed payslip: no potential manipulation, no inconsistency",
              d["counts"]["potential_manipulation"] == 0 and d["counts"]["inconsistency"] == 0, str(d["counts"]))
    finally:
        os.environ.pop("SAKSHI_TRUST_DIR", None)
        if old is not None:
            os.environ["SAKSHI_TRUST_DIR"] = old
        shutil.rmtree(tmp, ignore_errors=True)
    ok = all(results)
    print("RESULT:", "ALL PASS" if ok else "FAILURES")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
