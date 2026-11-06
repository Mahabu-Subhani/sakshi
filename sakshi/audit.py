"""Append-only, hash-chained audit trail (chain of custody in the spirit of ISO/IEC 27037).

Every event stores the SHA-256 of the previous event, so any later edit to the
log breaks the chain and `verify()` reports exactly where.
"""
from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path


def sha256_file(path: str | Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


class AuditLog:
    def __init__(self, path: str | Path, case_id: str):
        self.path = Path(path)
        self.case_id = case_id
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.prev = "0" * 64
        if self.path.exists():
            lines = self.path.read_text().strip().splitlines()
            if lines:
                self.prev = json.loads(lines[-1])["hash"]

    def log(self, event: str, **payload) -> dict:
        rec = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            "case_id": self.case_id,
            "event": event,
            "payload": payload,
            "prev_hash": self.prev,
        }
        body = json.dumps(rec, sort_keys=True, default=str)
        rec["hash"] = hashlib.sha256(body.encode()).hexdigest()
        with open(self.path, "a") as f:
            f.write(json.dumps(rec, default=str) + "\n")
        self.prev = rec["hash"]
        return rec

    def records(self) -> list[dict]:
        if not self.path.exists():
            return []
        return [json.loads(x) for x in self.path.read_text().strip().splitlines() if x.strip()]

    def verify(self) -> tuple[bool, str]:
        prev = "0" * 64
        for i, rec in enumerate(self.records()):
            h = rec.pop("hash")
            if rec["prev_hash"] != prev:
                return False, f"chain broken at event {i} ({rec['event']})"
            body = json.dumps(rec, sort_keys=True, default=str)
            if hashlib.sha256(body.encode()).hexdigest() != h:
                return False, f"event {i} ({rec['event']}) was modified after it was written"
            prev = h
        return True, "audit chain intact"
