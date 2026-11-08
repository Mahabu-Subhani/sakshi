"""Batch mode and the REST API.

* batch: three applications (tampered demo, genuine demo, red-team RT8) investigated side by side on three worker
  processes must give exactly the counts they give one at a time, with intact audit trails and a summary CSV;
* API: a request without the bearer token is refused; a case posted as multipart files completes and its
  dossier and audit trail can be downloaded; an upload name with directory parts cannot escape the upload folder.

    python tests/run_service.py
"""
import csv
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from sakshi.audit import AuditLog  # noqa: E402
from sakshi.pipeline import run_case  # noqa: E402
from sakshi.service import batch, safe_name  # noqa: E402

EXPECTED = {}  # one-at-a-time counts, measured on this machine first (the OCR engine version can move them)
SOURCES = {"case_tampered": ROOT / "dataset/cases/case_tampered", "case_genuine": ROOT / "dataset/cases/case_genuine",
           "RT8_scanned_pdf_editor": ROOT / "dataset/redteam/RT8_scanned_pdf_editor"}
results = []


def check(name, ok, detail=""):
    results.append(ok)
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f"  ({detail})" if detail else ""))


def multipart(fields, files):
    b = uuid.uuid4().hex
    body = b""
    for k, v in fields.items():
        body += f'--{b}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'.encode()
    for name, data in files:
        body += (f'--{b}\r\nContent-Disposition: form-data; name="files"; filename="{name}"\r\n'
                 f"Content-Type: application/octet-stream\r\n\r\n").encode() + data + b"\r\n"
    return body + f"--{b}--\r\n".encode(), f"multipart/form-data; boundary={b}"


def call(url, token=None, data=None, ctype=None):
    req = urllib.request.Request(url, data=data, method="POST" if data is not None else "GET")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    if ctype:
        req.add_header("Content-Type", ctype)
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="sakshi_service_"))
    try:
        print("== one at a time (baseline on this machine)")
        for name, src in SOURCES.items():
            files = sorted(str(p) for p in src.iterdir() if p.suffix.lower() in (".pdf", ".jpg", ".png"))
            EXPECTED[name] = run_case(files, tmp / "baseline" / name, case_id=name, html=False)["counts"]
            print(f"  {name}: {EXPECTED[name]}")
        print("== batch: 3 applications on 3 workers")
        apps = tmp / "applications"
        for name, src in SOURCES.items():
            shutil.copytree(src, apps / name)
        s = batch(apps, tmp / "batch_out", workers=3, echo=lambda *a: None)
        rows = {r["application"]: r for r in csv.DictReader(open(tmp / "batch_out" / "summary.csv", encoding="utf-8"))}
        check("all 3 applications done", s["done"] == 3, f"{s['done']}/3 in {s['wall_seconds']} s")
        for name, exp in EXPECTED.items():
            got = {k: int(rows[name][k]) for k in exp} if rows.get(name, {}).get("status") == "done" else None
            check(f"{name}: same counts as one at a time", got == exp, f"{got}")
            if got:
                d = Path(rows[name]["dossier"]).parent
                ok, msg = AuditLog(d / "audit.jsonl", "verify").verify()
                check(f"{name}: audit trail intact", ok, msg)

        print("== API")
        with socket.socket() as sk:
            sk.bind(("127.0.0.1", 0))
            port = sk.getsockname()[1]
        token = uuid.uuid4().hex
        env = dict(os.environ, SAKSHI_API_TOKEN=token)
        srv = subprocess.Popen([sys.executable, "-m", "sakshi", "serve", "--port", str(port), "--workers", "2",
                                "--out", str(tmp / "api_out")], cwd=ROOT, env=env,
                               stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        try:
            base = f"http://127.0.0.1:{port}/v1"
            for _ in range(60):
                try:
                    code, _ = call(f"{base}/health")
                    if code == 200:
                        break
                except OSError:
                    time.sleep(0.5)
            code, body = call(f"{base}/health")
            check("health endpoint answers", code == 200 and json.loads(body)["status"] == "ok")
            files = [(p.name, p.read_bytes()) for p in sorted(SOURCES["case_tampered"].glob("0*"))]
            files[0] = ("../../evil/" + files[0][0], files[0][1])  # directory parts in the upload name
            data, ctype = multipart({"case_id": "API-TAMPERED"}, files)
            small, sctype = multipart({"case_id": "NO-TOKEN"}, [("a.pdf", b"%PDF-1.4 test")])
            code, _ = call(f"{base}/cases", None, small, sctype)
            check("upload without the token is refused", code == 401, f"HTTP {code}")
            code, _ = call(f"{base}/cases/anything", None)
            check("status without the token is refused", code == 401, f"HTTP {code}")
            code, body = call(f"{base}/cases", token, data, ctype)
            job = json.loads(body)
            check("case accepted", code == 202 and job.get("status") in ("queued", "running"), f"HTTP {code}")
            t0 = time.time()
            while time.time() - t0 < 600:
                code, body = call(f"{base}/cases/{job['job_id']}", token)
                job = json.loads(body)
                if job["status"] in ("done", "failed"):
                    break
                time.sleep(2)
            check("case completed through the API", job["status"] == "done",
                  job.get("error") or f"{job.get('seconds')} s")
            check("API result has the expected counts", job.get("counts") == EXPECTED["case_tampered"],
                  str(job.get("counts")))
            code, body = call(f"{base}/cases/{job['job_id']}/dossier.json", token)
            check("dossier downloadable", code == 200 and json.loads(body)["case_id"] == "API-TAMPERED")
            code, body = call(f"{base}/cases/{job['job_id']}/audit.jsonl", token)
            check("audit trail downloadable", code == 200 and body.count(b"\n") > 5)
            staged = list((tmp / "api_out" / "_uploads").rglob("*"))
            escaped = [p for p in tmp.rglob("*") if "evil" in p.parts]
            check("upload names cannot leave the upload folder",
                  not escaped and any(p.name.endswith("01_payslip_oct2026.pdf") for p in staged),
                  safe_name("../../evil/x.pdf"))
        finally:
            srv.kill()
            srv.wait(10)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    ok = all(results)
    print("RESULT:", "ALL PASS" if ok else "FAILURES")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
