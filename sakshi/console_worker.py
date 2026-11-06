"""Run one case in its own process for the review console.

The console used to call the pipeline inside the Streamlit server process. If a case ever stalls there,
the whole console stalls with it (seen once on 2026-11-06; cause not found in about 25 replays).
Here each case runs in a spawned worker process:

* only small progress tuples cross the process boundary; the result is read from the dossier.json the
  pipeline already writes, never pickled back;
* a hard timeout (SAKSHI_CASE_TIMEOUT seconds, default 600) kills the worker and everything it started,
  and the analyst gets a clear error instead of a frozen page;
* one case runs at a time per console, so two clicks cannot double the memory use;
* passwords travel to the worker over the in-memory spawn pipe, never on a command line or on disk, and
  worker errors are reported as type and message only.

Detection code and thresholds are untouched: the worker calls the same run_case as the CLI and the tests.
This module must not import Streamlit, so the spawned worker never re-runs console code.
"""
from __future__ import annotations

import json
import multiprocessing as mp
import os
import queue
import subprocess
import threading
import time
from pathlib import Path

TIMEOUT_S = float(os.environ.get("SAKSHI_CASE_TIMEOUT", "600"))
_ONE_CASE = threading.Lock()


class ConsoleBusy(RuntimeError):
    """Another case is already running in this console."""


class CaseTimeout(RuntimeError):
    """The case did not finish in time and its worker was stopped."""


class CaseFailed(RuntimeError):
    """The worker stopped with an error."""


def _worker(files, out_dir, case_id, lang, registry_path, passwords, q):
    from sakshi.pipeline import run_case

    def progress(i, n, stage, note):
        q.put(("progress", i, n, stage, note))

    try:
        run_case(files, out_dir, case_id=case_id, progress=progress, lang=lang, registry_path=registry_path,
                 passwords=passwords)
        q.put(("done",))
    except BaseException as e:  # report type and message only: no locals, no arguments
        q.put(("error", f"{type(e).__name__}: {e}"))


def _kill_tree(pid: int) -> None:
    try:
        import psutil
        proc = psutil.Process(pid)
        for p in proc.children(recursive=True) + [proc]:
            try:
                p.kill()
            except psutil.Error:
                pass
        return
    except Exception:
        pass
    if os.name == "nt":
        subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True)
    else:
        try:
            os.kill(pid, 9)
        except OSError:
            pass


def run_isolated(files, out_dir, *, case_id, lang="eng", registry_path=None, passwords=None, progress=None,
                 timeout_s: float = TIMEOUT_S) -> dict:
    """Run one case in a worker process and return its dossier (as written to dossier.json)."""
    if not _ONE_CASE.acquire(blocking=False):
        raise ConsoleBusy("another case is still running in this console")
    proc = None
    try:
        ctx = mp.get_context("spawn")
        q = ctx.Queue()
        proc = ctx.Process(target=_worker, daemon=True, name=f"sakshi-{case_id}",
                           args=([str(f) for f in files], str(out_dir), case_id, lang,
                                 str(registry_path) if registry_path else None, list(passwords or []) or None, q))
        proc.start()
        t0 = time.time()
        while True:
            try:
                msg = q.get(timeout=0.5)
            except queue.Empty:
                if time.time() - t0 > timeout_s:
                    _kill_tree(proc.pid)
                    raise CaseTimeout(f"case {case_id} did not finish within {timeout_s:.0f} s and was stopped")
                if not proc.is_alive():
                    try:  # the last message may arrive just after the worker exits
                        msg = q.get(timeout=1.0)
                    except queue.Empty:
                        raise CaseFailed(f"the worker for case {case_id} exited (code {proc.exitcode}) without a result")
                else:
                    continue
            if msg[0] == "progress":
                if progress:
                    progress(*msg[1:])
            elif msg[0] == "done":
                break
            elif msg[0] == "error":
                raise CaseFailed(msg[1])
        proc.join(10)
        return json.loads((Path(out_dir) / "dossier.json").read_text(encoding="utf-8"))
    finally:
        if proc is not None and proc.is_alive():
            _kill_tree(proc.pid)
        _ONE_CASE.release()
