"""Cross-case memory (v1.0): fingerprints of every investigated application, kept locally.

Forgery rings reuse material: the same ID photo under different names, the same salary
account for several "employees", the same payslip file, the same signature. A single
application can look clean while the second application from the same ring is obvious.

Stored per case (no images, no raw documents): normalized applicant name, identifiers (PAN,
account, mobile, ID number, employer + employee ID), SHA-256 of every file, a 64-bit
perceptual hash of each ID-card photo, and a coarse stroke-density grid of each signature
(DCT hashes collide on sparse signature masks, grids do not).
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

import cv2
import numpy as np

from .models import Evidence, Finding
from .reasoning.repair import name_key


def photo_region(img_path: str):
    """Largest roughly portrait rectangle on an ID card that is not text: the photo."""
    bgr = cv2.imread(img_path)
    if bgr is None:
        return None
    g = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
    H, W = g.shape
    edges = cv2.Canny(cv2.GaussianBlur(g, (5, 5), 0), 40, 120)
    edges = cv2.dilate(edges, np.ones((3, 3), np.uint8))
    cnts, _ = cv2.findContours(edges, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
    best = None
    for c in cnts:
        x, y, w, h = cv2.boundingRect(c)
        a = w * h
        if not (0.04 * W * H <= a <= 0.35 * W * H) or not (0.55 <= w / max(h, 1) <= 0.95):
            continue
        roi = g[y:y + h, x:x + w]
        if float(roi.std()) < 15:
            continue
        if best is None or a > best[2] * best[3]:
            best = (x, y, w, h)
    return best


def phash(gray: np.ndarray) -> str:
    small = cv2.resize(gray, (32, 32), interpolation=cv2.INTER_AREA).astype(np.float32)
    d = cv2.dct(small)[:8, :8].ravel()[1:]
    bits = (d > np.median(d)).astype(np.uint8)
    return "".join(map(str, bits))


def sig_grid(mask: np.ndarray) -> str:
    m = (mask > 0).astype(np.uint8)
    g = cv2.resize(m * 255, (48, 16), interpolation=cv2.INTER_AREA) > 40
    return "".join("1" if b else "0" for b in g.ravel())


def _ham(a: str, b: str) -> int:
    return sum(x != y for x, y in zip(a, b)) + abs(len(a) - len(b))


def _grid_iou(a: str, b: str) -> float:
    A = np.array([c == "1" for c in a]).reshape(16, 48)
    B = np.array([c == "1" for c in b]).reshape(16, 48)
    k = np.ones((3, 3), np.uint8)
    A = cv2.dilate(A.astype(np.uint8), k) > 0
    B = cv2.dilate(B.astype(np.uint8), k) > 0
    return float((A & B).sum() / max(1, (A | B).sum()))


def fingerprint(case_id: str, docs: dict, sigs: list, verified: dict | None = None) -> dict:
    names, ids = set(), {"pan": set(), "account": set(), "mobile": set(), "id_no": set(), "employee": set()}
    refs = {}
    display = ""
    for d in docs.values():
        for n in ("applicant_name", "employee_name", "name", "account_holder"):
            if n in d.fields:
                names.add(name_key(d.fields[n].value))
                if not display or (n in ("applicant_name", "name") and len(str(d.fields[n].value)) > len(display)):
                    display = str(d.fields[n].value).title()
        for key, n in (("pan", "pan"), ("account", "account_no"), ("mobile", "mobile"), ("id_no", "id_no")):
            if n in d.fields:
                ids[key].add(str(d.fields[n].value))
                refs.setdefault(f"{key}:{d.fields[n].value}", (d.doc_id, d.fields[n].page, d.fields[n].bbox))
        if "employee_id" in d.fields and "employer" in d.fields:
            v = f"{d.fields['employer'].value}|{d.fields['employee_id'].value}"
            ids["employee"].add(v)
            refs.setdefault(f"employee:{v}", (d.doc_id, d.fields["employee_id"].page, d.fields["employee_id"].bbox))
    photos = []
    for d in docs.values():
        if d.doc_type == "identity_card" and d.pages:
            r = photo_region(d.pages[0].image_path)
            if r:
                x, y, w, h = r
                g = cv2.cvtColor(cv2.imread(d.pages[0].image_path), cv2.COLOR_BGR2GRAY)[y:y + h, x:x + w]
                photos.append({"hash": phash(g), "doc": d.doc_id, "bbox": (x, y, x + w, y + h)})
    signatures = [{"grid": sig_grid(s["mask"]), "doc": s["doc"], "bbox": s["bbox"],
                   "doc_type": docs[s["doc"]].doc_type} for s in sigs]
    applicant = display or (sorted(names, key=len)[-1] if names else "")
    return {"case_id": case_id, "ts": time.strftime("%Y-%m-%d %H:%M:%S"), "applicant": applicant, "names": sorted(names),
            "ids": {k: sorted(v) for k, v in ids.items()}, "files": {d.filename: d.sha256 for d in docs.values()},
            "photos": photos, "signatures": signatures, "refs": refs, "verified": verified or {}}


class Registry:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.data = {"cases": []}
        if self.path.exists():
            try:
                self.data = json.loads(self.path.read_text())
            except Exception:
                self.data = {"cases": []}

    def check(self, fp: dict, docs: dict, new_id) -> list[Finding]:
        """Compare this application with every remembered one.

        Who used an identifier first decides nothing (v1.1): a ring that registers a victim's identifiers first must
        not get the victim flagged. A conflict between two different people is CONTESTED on this application, and a
        notice is recorded against the other one, until an issuer settles it: an identifier the bank's own record
        (Account Aggregator data) confirms for one of the two applicants belongs to that applicant. Photos,
        signatures and identical files cannot be verified by an issuer offline, so their conflicts stay contested.
        Each conflict is reported once, naming every remembered application involved."""
        out = []
        me = set(fp["names"])
        fp.setdefault("contests", [])
        mine_verified = fp.get("verified", {})

        def other_person(c):
            return not (set(c["names"]) & me)

        def settle(c, key, v) -> str:
            ours = v in mine_verified.get(key, [])
            theirs = v in c.get("verified", {}).get(key, [])
            return "mine" if ours and not theirs else "theirs" if theirs and not ours else "contested"

        def contest(c, label):
            fp["contests"].append({"case_id": c["case_id"], "by_case": fp["case_id"], "what": label})

        def ev_for(key):
            r = fp["refs"].get(key)
            if not r:
                return []
            return [Evidence(r[0], r[1], tuple(r[2]), "this application", kind="field")]

        def whom(cs):
            names = [f"case {c['case_id']} ({c['applicant'].title()})" for c in cs[:3]]
            return ", ".join(names) + (f" and {len(cs) - 3} more" if len(cs) > 3 else "")

        contested = ("Which application is genuine is unknown until an issuer verifies it; both sides are flagged, "
                     "whichever came first.")
        verify = ("Obtain the bank's Account Aggregator data (or a UIDAI / PAN check) for the applicants involved; "
                  "the verified holder settles it.")
        files_g, ids_g, photo_g, sig_g = {}, {}, {}, {}

        for c in self.data["cases"]:
            if c["case_id"] == fp["case_id"]:
                continue
            same = [(fname, of) for fname, h in fp["files"].items() for of, oh in c["files"].items() if h == oh]
            if same and not other_person(c):
                # the same applicant re-submitting their own documents (a re-run, a second application, a rehearsal):
                # recorded, never escalated (a demo re-run must not look like an identity ring)
                full = len(same) == len(fp["files"]) == len(c["files"])
                did = next(d.doc_id for d in docs.values() if d.filename == same[0][0])
                out.append(Finding(
                    id=new_id(), check="cross_case_resubmission", family="cross_case", sensor="registry",
                    title=(f"Duplicate submission of case {c['case_id']} (same applicant, identical files)" if full else
                           f"{len(same)} file(s) were already submitted by the same applicant in case {c['case_id']}"),
                    detail="Identical SHA-256 and the same applicant name. Re-using one's own documents is normal; recorded "
                           "so the analyst can link the two applications.",
                    confidence=0.5, localized=False,
                    evidence=[Evidence(did, 0, (0, 0, docs[did].pages[0].width, docs[did].pages[0].height), "whole file", kind="file")],
                    docs=[did], repair={"other_case": c["case_id"], "files": [a for a, _ in same]}))
                continue
            if not other_person(c):
                continue
            for fname, of in same:
                files_g.setdefault(fname, []).append((c, of))
                contest(c, f"file {fname}")
            for key, vals in fp["ids"].items():
                for v in sorted(set(vals) & set(c["ids"].get(key, []))):
                    state = settle(c, key, v)
                    ids_g.setdefault((key, v), []).append((c, state))
                    contest(c, f"{key} {v.split('|')[-1]}" + (f" verified for {fp['case_id']}" if state == "mine" else ""))
            for i, p in enumerate(fp["photos"]):
                hd = min((_ham(p["hash"], q["hash"]) for q in c.get("photos", [])), default=99)
                if hd <= 8:
                    photo_g.setdefault(i, []).append((c, hd))
                    contest(c, "ID photo")
            for i, s_ in enumerate(fp["signatures"]):
                if s_["doc_type"] != "application_form":
                    continue
                iou = max((_grid_iou(s_["grid"], t["grid"]) for t in c.get("signatures", [])
                           if t.get("doc_type") == "application_form"), default=0.0)
                if iou >= 0.8:
                    sig_g.setdefault(i, []).append((c, iou))
                    contest(c, "applicant signature")

        for fname, hits in files_g.items():
            did = next(d.doc_id for d in docs.values() if d.filename == fname)
            cs = [c for c, _ in hits]
            out.append(Finding(
                id=new_id(), check="cross_case_file_reuse", family="cross_case", sensor="registry",
                title=f"{fname} is byte-for-byte the same file as one in {whom(cs)}, a different applicant: contested",
                detail="Identical SHA-256: the same document file was submitted in another person's application. "
                       + contested,
                confidence=0.97, localized=True, verify_next=verify,
                evidence=[Evidence(did, 0, (0, 0, docs[did].pages[0].width, docs[did].pages[0].height), "whole file", kind="file")],
                docs=[did], repair={"other_cases": [c["case_id"] for c in cs], "identity_contested": True}))
        labels = {"pan": "PAN", "account": "Salary account number", "mobile": "Mobile number", "id_no": "ID number",
                  "employee": "Employer + employee ID"}
        for (key, v), hits in ids_g.items():
            label, shown = labels[key], v.split("|")[-1]
            ev = ev_for(f"{key}:{v}")
            evid = ev or [Evidence(next(iter(docs)), 0, (0, 0, 10, 10), "case")]
            theirs = [c for c, s in hits if s == "theirs"]
            mine = [c for c, s in hits if s == "mine"]
            open_ = [c for c, s in hits if s == "contested"]
            if theirs:
                out.append(Finding(
                    id=new_id(), check="cross_case_identifier_reuse", family="cross_case", sensor="registry",
                    title=f"{label} {shown} is verified by the bank's own record as belonging to {whom(theirs)}, "
                          "not to this applicant",
                    detail=("The Account Aggregator data attached to the other application confirms its holder. This "
                            f"application ({', '.join(n.title() for n in fp['names'])}) uses it under a different name."),
                    confidence=0.95, localized=bool(ev), smoking_gun=True, evidence=evid,
                    docs=[evid[0].doc_id] if ev else [],
                    repair={"other_cases": [c["case_id"] for c in theirs], "identifier": key, "verified": "other case"}))
            elif open_:
                out.append(Finding(
                    id=new_id(), check="cross_case_identifier_reuse", family="cross_case", sensor="registry",
                    title=f"{label} {shown} also appears under a different name in {whom(open_)}: contested",
                    detail=(f"This application ({', '.join(n.title() for n in fp['names'])}) shares its {label.lower()} "
                            "with another person. One identifier used by two different people is a known pattern of "
                            "identity recycling and mule accounts; innocent explanations are a family member's or a joint "
                            "account, or a data-entry error. " + contested),
                    confidence=0.85, localized=bool(ev), verify_next=verify, evidence=evid,
                    docs=[evid[0].doc_id] if ev else [],
                    repair={"other_cases": [c["case_id"] for c in open_], "identifier": key, "identity_contested": True}))
            if mine and not theirs:
                out.append(Finding(
                    id=new_id(), check="cross_case_reused_by_other", family="cross_case", sensor="registry",
                    title=f"{label} {shown} is verified by the bank's own record as this applicant's; {whom(mine)} "
                          "used it under another name",
                    detail="The Account Aggregator data attached to this case confirms the holder. The other "
                           "application is the one to review; recorded so the applications stay linked.",
                    confidence=0.6, localized=False, evidence=evid, docs=[evid[0].doc_id],
                    repair={"other_cases": [c["case_id"] for c in mine], "identifier": key, "verified": "this case"}))
        for i, hits in photo_g.items():
            p = fp["photos"][i]
            cs = [c for c, _ in hits]
            hd = min(h for _, h in hits)
            out.append(Finding(
                id=new_id(), check="cross_case_photo_reuse", family="cross_case", sensor="registry",
                title=f"The ID photo is the same image as the ID photo in {whom(cs)}, under a different name: contested",
                detail=(f"Perceptual hashes differ in {hd} of 63 bits (independent photos of different people differ in "
                        "about 32). The same face image is used for two identities. " + contested),
                confidence=0.92, localized=True, verify_next=verify,
                evidence=[Evidence(p["doc"], 0, tuple(p["bbox"]), "photo on this application")],
                docs=[p["doc"]], repair={"other_cases": [c["case_id"] for c in cs], "hamming": hd,
                                         "identity_contested": True}))
        for i, hits in sig_g.items():
            s_ = fp["signatures"][i]
            cs = [c for c, _ in hits]
            iou = max(x for _, x in hits)
            out.append(Finding(
                id=new_id(), check="cross_case_signature_reuse", family="cross_case", sensor="registry",
                title=f"The applicant's signature matches the applicant signature in {whom(cs)}: contested",
                detail=f"Stroke-density grids overlap at {iou:.2f}; two people do not sign alike. " + contested,
                confidence=0.8, localized=True, verify_next=verify,
                evidence=[Evidence(s_["doc"], 0, tuple(s_["bbox"]), "signature on this application")],
                docs=[s_["doc"]], repair={"other_cases": [c["case_id"] for c in cs], "iou": round(iou, 3),
                                          "identity_contested": True}))
        return out

    def register(self, fp: dict):
        # a re-run keeps the case's original position: registration order is "who held it first"
        rec = {k: v for k, v in fp.items() if k not in ("refs", "contests")}
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with _FileLock(self.path.with_name(self.path.name + ".lock")):
            # re-read under the lock: another process (console worker, command line) may have registered a case
            # since this one was loaded, and its entry must not be overwritten
            if self.path.exists():
                try:
                    self.data = json.loads(self.path.read_text())
                except Exception:
                    raise RuntimeError(f"cross-case memory {self.path} is unreadable; it was left untouched") from None
            ids = [c["case_id"] for c in self.data["cases"]]
            for n in fp.get("contests", []):  # the other application in each conflict is flagged too
                if n["case_id"] in ids:
                    other = self.data["cases"][ids.index(n["case_id"])]
                    note = {"by_case": n["by_case"], "what": n["what"]}
                    if note not in other.setdefault("contested_by", []):
                        other["contested_by"].append(note)
            if fp["case_id"] in ids:
                self.data["cases"][ids.index(fp["case_id"])] = rec
            else:
                self.data["cases"].append(rec)
            tmp = self.path.with_name(self.path.name + f".{os.getpid()}.tmp")
            tmp.write_text(json.dumps(self.data, indent=1, default=str))
            for attempt in range(20):  # atomic swap: a reader never sees a half-written file
                try:
                    os.replace(tmp, self.path)
                    break
                except PermissionError:  # Windows: a reader has the file open for a moment
                    if attempt == 19:
                        tmp.unlink(missing_ok=True)
                        raise
                    time.sleep(0.05)


class _FileLock:
    """Cross-process lock using an exclusively created lock file (no extra dependency). A lock older than
    `stale` seconds is treated as left behind by a crashed process and removed."""

    def __init__(self, path: Path, timeout: float = 30.0, stale: float = 120.0):
        self.path, self.timeout, self.stale = path, timeout, stale

    def __enter__(self):
        deadline = time.monotonic() + self.timeout
        while True:
            try:
                fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                os.write(fd, str(os.getpid()).encode())
                os.close(fd)
                return self
            except FileExistsError:
                try:
                    if time.time() - self.path.stat().st_mtime > self.stale:
                        self.path.unlink(missing_ok=True)
                        continue
                except FileNotFoundError:
                    continue
                if time.monotonic() > deadline:
                    raise TimeoutError(f"cross-case memory is locked by another process ({self.path})")
                time.sleep(0.05)

    def __exit__(self, *exc):
        self.path.unlink(missing_ok=True)
