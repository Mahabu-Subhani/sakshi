"""Throughput and integration: a job queue that runs several cases side by side, a batch command and a REST API.

Each case runs in its own spawned process with a hard timeout (the console's isolation, without its one-case lock),
so a stalled or crashing case cannot take others down. Detection is unchanged: every worker calls the same run_case.

    python -m sakshi batch APPLICATIONS_DIR --out OUT_DIR [--workers N] [--memory registry.json]
    python -m sakshi serve [--host 127.0.0.1] [--port 8600] [--workers N] [--out DIR] [--memory registry.json]

Cross-case memory: each case is checked against the memory when it starts and registered when it ends, so two
applications that are running at the same moment cannot see each other. Use --workers 1 when strict order matters.
"""
from __future__ import annotations

import csv
import json
import os
import re
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from .console_worker import CaseFailed, CaseTimeout, TIMEOUT_S, run_in_worker

DOC_SUFFIXES = {".pdf", ".jpg", ".jpeg", ".png", ".tif", ".tiff", ".webp", ".bmp", ".json", ".xml"}
_SAFE = re.compile(r"[^A-Za-z0-9._-]+")


def safe_name(name: str, fallback: str = "file") -> str:
    """A bare file name with no directory parts, safe on every platform."""
    base = _SAFE.sub("_", Path(str(name).replace("\\", "/")).name).strip("._")
    return base[:120] or fallback


class Jobs:
    """Runs cases on a pool of isolated worker processes and keeps their status."""

    def __init__(self, root: str | Path, workers: int = 2, memory: str | Path | None = None,
                 timeout_s: float = TIMEOUT_S, lang: str = "eng"):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.workers = max(1, int(workers))
        self.memory, self.timeout_s, self.lang = memory, timeout_s, lang
        self.pool = ThreadPoolExecutor(max_workers=self.workers, thread_name_prefix="sakshi-job")
        self.jobs: dict[str, dict] = {}
        self.lock = threading.Lock()

    def submit(self, files: list[str | Path], case_id: str | None = None, passwords=None) -> str:
        job_id = uuid.uuid4().hex[:12]
        case_id = safe_name(case_id or f"CASE-{job_id}", f"CASE-{job_id}")
        job = {"job_id": job_id, "case_id": case_id, "status": "queued", "submitted": time.time(),
               "files": [Path(f).name for f in files], "out": str(self.root / job_id)}
        with self.lock:
            self.jobs[job_id] = job
        self._save(job)
        self.pool.submit(self._run, job_id, [str(f) for f in files], passwords)
        return job_id

    def _run(self, job_id, files, passwords):
        job = self.jobs[job_id]
        job.update(status="running", started=time.time())
        self._save(job)
        try:
            d = run_in_worker(files, job["out"], case_id=job["case_id"], lang=self.lang,
                              registry_path=self.memory, passwords=passwords, timeout_s=self.timeout_s)
            job.update(status="done", verdict=d["status"], counts=d["counts"],
                       audit_verified=d.get("audit", {}).get("verified"),
                       ocr_warning=(d.get("environment") or {}).get("warning"),
                       rejected=[r["file"] for r in d.get("rejected", [])])
        except (CaseTimeout, CaseFailed) as e:
            job.update(status="failed", error=str(e))
        except Exception as e:  # never let one case stop the pool
            job.update(status="failed", error=f"{type(e).__name__}: {e}")
        job["finished"] = time.time()
        job["seconds"] = round(job["finished"] - job["started"], 1)
        self._save(job)

    def _save(self, job):
        d = self.root / job["job_id"]
        d.mkdir(parents=True, exist_ok=True)
        (d / "job.json").write_text(json.dumps({k: v for k, v in job.items() if k != "out"}, indent=1))

    def get(self, job_id: str) -> dict | None:
        return self.jobs.get(job_id)

    def wait(self):
        self.pool.shutdown(wait=True)


# ---------------------------------------------------------------- batch

def applications(folder: Path) -> list[tuple[str, list[Path]]]:
    """Each sub-folder of FOLDER is one application; its documents are the files directly inside it."""
    apps = []
    for sub in sorted(p for p in Path(folder).iterdir() if p.is_dir() and not p.name.startswith(("_", "."))):
        files = sorted(f for f in sub.iterdir() if f.is_file() and f.suffix.lower() in DOC_SUFFIXES
                       and not f.name.startswith("MANIFEST"))
        if files:
            apps.append((sub.name, files))
    return apps


def batch(folder, out, workers=2, memory=None, timeout_s=TIMEOUT_S, lang="eng", echo=print) -> dict:
    apps = applications(Path(folder))
    if not apps:
        raise SystemExit(f"no applications found in {folder}: put each application's documents in its own sub-folder")
    jobs = Jobs(out, workers=workers, memory=memory, timeout_s=timeout_s, lang=lang)
    t0 = time.time()
    ids = [(name, jobs.submit(files, case_id=name)) for name, files in apps]
    echo(f"{len(ids)} application(s) queued on {jobs.workers} worker(s)")
    jobs.wait()
    wall = time.time() - t0
    rows = []
    for name, jid in ids:
        j = jobs.get(jid)
        c = j.get("counts") or {}
        rows.append({"application": name, "job_id": jid, "status": j["status"], "verdict": j.get("verdict", ""),
                     "potential_manipulation": c.get("potential_manipulation", ""),
                     "inconsistency": c.get("inconsistency", ""), "observation": c.get("observation", ""),
                     "seconds": j.get("seconds", ""), "audit_verified": j.get("audit_verified", ""),
                     "dossier": str(Path(j["out"]) / "dossier.html") if j["status"] == "done" else "",
                     "error": j.get("error", "")})
        echo(f"  {name:40s} {j['status']:6s} {j.get('verdict', j.get('error', ''))[:60]}  {j.get('seconds', '')}s")
    with open(Path(out) / "summary.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    done = sum(r["status"] == "done" for r in rows)
    summary = {"applications": len(rows), "done": done, "failed": len(rows) - done, "workers": jobs.workers,
               "wall_seconds": round(wall, 1), "cases_per_hour": round(3600 * done / wall, 1) if wall else None,
               "cpu_count": os.cpu_count()}
    (Path(out) / "summary.json").write_text(json.dumps(summary, indent=1))
    echo(f"{done}/{len(rows)} done in {wall:.0f} s on {jobs.workers} worker(s): "
         f"{summary['cases_per_hour']} cases per hour. Summary: {Path(out) / 'summary.csv'}")
    return summary


# ---------------------------------------------------------------- REST API

MAX_FILES, MAX_BYTES = 20, 50 * 1024 * 1024


def make_app(jobs: Jobs, token: str | None = None):
    """Starlette app (Starlette and uvicorn ship with Streamlit, so no extra dependency)."""
    from starlette.applications import Starlette
    from starlette.requests import Request
    from starlette.responses import FileResponse, JSONResponse
    from starlette.routing import Route

    def authorised(request: Request) -> bool:
        return not token or request.headers.get("authorization", "") == f"Bearer {token}"

    def deny():
        return JSONResponse({"error": "missing or wrong bearer token"}, status_code=401)

    def view(job):
        out = {k: v for k, v in job.items() if k not in ("out",)}
        if job["status"] == "done":
            base = f"/v1/cases/{job['job_id']}"
            out["links"] = {"dossier_html": f"{base}/dossier.html", "dossier_json": f"{base}/dossier.json",
                            "audit": f"{base}/audit.jsonl"}
        return out

    async def health(request):
        from .environment import environment
        return JSONResponse({"status": "ok", "workers": jobs.workers, "environment": environment()})

    async def create(request: Request):
        if not authorised(request):
            # read and discard a small refused body so the client receives the 401 instead of a reset connection;
            # a large unauthorised upload is cut off rather than read
            seen = 0
            async for chunk in request.stream():
                seen += len(chunk)
                if seen > 1024 * 1024:
                    break
            return deny()
        form = await request.form(max_files=MAX_FILES, max_fields=10)
        uploads = form.getlist("files")
        if not uploads:
            return JSONResponse({"error": "send the application's documents as multipart field 'files'"}, 400)
        stage = jobs.root / "_uploads" / uuid.uuid4().hex[:12]
        stage.mkdir(parents=True)
        paths = []
        for i, up in enumerate(uploads):
            data = await up.read()
            if len(data) > MAX_BYTES:
                return JSONResponse({"error": f"{up.filename}: larger than {MAX_BYTES // 2**20} MB"}, 413)
            p = stage / f"{i + 1:02d}_{safe_name(up.filename)}"
            p.write_bytes(data)
            paths.append(p)
        pw = [v for v in form.getlist("password") if isinstance(v, str) and v]
        job_id = jobs.submit(paths, case_id=form.get("case_id"), passwords=pw or None)
        return JSONResponse(view(jobs.get(job_id)) | {"status_url": f"/v1/cases/{job_id}"}, status_code=202)

    async def status(request: Request):
        if not authorised(request):
            return deny()
        job = jobs.get(request.path_params["job_id"])
        return JSONResponse(view(job)) if job else JSONResponse({"error": "no such job"}, 404)

    async def artefact(request: Request):
        if not authorised(request):
            return deny()
        job = jobs.get(request.path_params["job_id"])
        name = request.path_params["name"]
        if not job or job["status"] != "done" or name not in ("dossier.html", "dossier.json", "audit.jsonl"):
            return JSONResponse({"error": "not available"}, 404)
        return FileResponse(Path(job["out"]) / name)

    return Starlette(routes=[
        Route("/v1/health", health),
        Route("/v1/cases", create, methods=["POST"]),
        Route("/v1/cases/{job_id}", status),
        Route("/v1/cases/{job_id}/{name}", artefact),
    ])


def serve(host="127.0.0.1", port=8600, workers=2, out="out/service", memory=None, timeout_s=TIMEOUT_S, lang="eng"):
    import uvicorn
    token = os.environ.get("SAKSHI_API_TOKEN") or None
    if host not in ("127.0.0.1", "localhost", "::1") and not token:
        raise SystemExit("set SAKSHI_API_TOKEN before listening on a non-local address")
    jobs = Jobs(out, workers=workers, memory=memory, timeout_s=timeout_s, lang=lang)
    print(f"SAKSHI API on http://{host}:{port}/v1 with {jobs.workers} worker(s); "
          f"{'bearer token required' if token else 'no token (local only)'}", flush=True)
    uvicorn.run(make_app(jobs, token), host=host, port=port, log_level="warning")
