"""SAKSHI review console (Streamlit).

    streamlit run app.py

Upload the documents of one application (or load a demo case), watch the
pipeline run stage by stage, then review findings in the interactive dossier.
"""
from __future__ import annotations

import shutil
import tempfile
import time
from pathlib import Path

import streamlit as st
import streamlit.components.v1 as components

from sakshi.capabilities import CAPABILITIES
from sakshi.console_worker import CaseFailed, CaseTimeout, ConsoleBusy, run_isolated
from sakshi.pipeline import STAGES

ROOT = Path(__file__).resolve().parent
st.set_page_config(page_title="SAKSHI", page_icon=None, layout="wide")

st.markdown("### SAKSHI · document forensics and contextual intelligence")
st.caption("Upload every document of one application together. Findings are leads for an analyst, never a fraud verdict. "
           "Use authorised or synthetic documents only.")
with st.expander("What SAKSHI can and cannot do (capability matrix)"):
    st.markdown("| Status | Area | Scope |\n|---|---|---|\n" +
                "\n".join(f"| {s} | {a} | {d} |" for s, a, d in CAPABILITIES))

left, right = st.columns([3, 2])
with left:
    ups = st.file_uploader("Documents (PDF, JPG, PNG, TIFF)", type=["pdf", "jpg", "jpeg", "png", "tif", "tiff", "webp"],
                           accept_multiple_files=True)
REG = ROOT / "out" / "registry.json"
RT = ROOT / "dataset" / "redteam"
with right:
    st.write("Or load a demo case (synthetic, clearly labelled specimens):")
    rt_cases = sorted(p.name for p in RT.glob("*_*") if (p / "MANIFEST_ground_truth.json").exists()) if RT.exists() else []
    demo = st.selectbox("Demo case", ["none", "tampered application", "genuine control"] + [f"red team: {c}" for c in rt_cases])
    lang = st.selectbox("OCR languages", ["eng", "eng+hin"], index=0)
    with st.expander("Locked PDFs: passwords (each is tried on every locked PDF; never stored)"):
        pdf_passwords = [st.text_input(f"Password {i + 1}", type="password", key=f"pdf_pw_{i}") for i in range(3)]
    memory = st.checkbox("Cross-case memory (remember fingerprints of earlier cases on this machine)", value=True)
    try:
        import json as _json
        n_mem = len(_json.loads(REG.read_text())["cases"]) if REG.exists() else 0
    except Exception:
        n_mem = 0
    m_a, m_b = st.columns([2, 1])
    m_a.caption(f"{n_mem} earlier case(s) remembered.")
    if m_b.button("Reset memory"):
        REG.unlink(missing_ok=True)
        st.rerun()
    go = st.button("Investigate", type="primary")

if go:
    work = Path(tempfile.mkdtemp(prefix="sakshi_"))
    files = []
    if ups:
        (work / "in").mkdir()
        for u in ups:
            p = work / "in" / Path(u.name).name
            p.write_bytes(u.getbuffer())
            files.append(str(p))
        cid = time.strftime("CASE-%Y%m%d-%H%M%S")
    elif demo.startswith("red team: "):
        name = demo.split(": ", 1)[1]
        files = sorted(str(p) for p in (RT / name).iterdir() if p.name != "MANIFEST_ground_truth.json")
        cid = name
    elif demo != "none":
        case = "case_tampered" if demo.startswith("tampered") else "case_genuine"
        src = ROOT / "dataset" / "cases" / case
        if not src.exists():
            import subprocess, sys
            subprocess.run([sys.executable, str(ROOT / "dataset" / "generate.py")], check=True)
        files = sorted(str(p) for p in src.glob("0*"))
        cid = "DEMO-TAMPERED" if case == "case_tampered" else "DEMO-GENUINE"
    if not files:
        st.warning("Add at least one document or pick a demo case.")
        st.stop()
    bar = st.progress(0.0, text="Starting")
    log = st.empty()
    done = []

    def progress(i, n, stage, note):
        done.append(stage)
        bar.progress((i + 1) / n, text=f"{stage}{(' · ' + note) if note else ''}")
        log.markdown(" → ".join(f"**{s}**" if s == stage else s for s in done))

    # Each case runs in its own worker process with a hard timeout, so a stalled case can never freeze the console.
    try:
        d = run_isolated(files, work / "out", case_id=cid, progress=progress, lang=lang,
                         registry_path=REG if memory else None, passwords=[pw for pw in pdf_passwords if pw] or None)
    except ConsoleBusy:
        st.warning("Another case is still running in this console. Try again when it finishes.")
        st.stop()
    except CaseTimeout as e:
        st.error(f"Stopped: {e}. Nothing was reported for this case; the console is ready for the next one.")
        st.stop()
    except CaseFailed as e:
        st.error(f"The case could not be completed: {e}")
        st.stop()
    st.session_state["last"] = (str(work / "out"), d)

if "last" in st.session_state:
    out, d = st.session_state["last"]
    c = d["counts"]
    st.subheader(d["status"])
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Potential manipulation", c["potential_manipulation"])
    m2.metric("Inconsistencies", c["inconsistency"])
    m3.metric("Observations", c["observation"])
    m4.metric("Processing time", f"{d['processing_seconds']} s")
    if d["rejected"]:
        for r in d["rejected"]:
            st.error(r['reason'] if r['reason'].startswith(r['file']) else f"{r['file']}: {r['reason']}")
    with st.expander("What each sensor could and could not check on these documents"):
        for doc in d["documents"]:
            st.write(f"**{doc['filename']}** ({doc['type_label']}, {doc['modality'].replace('_', ' ')})")
            st.json(doc["capabilities"], expanded=False)
    html = (Path(out) / "dossier.html").read_text(encoding="utf-8")
    # The dossier is generated by SAKSHI itself; every document-derived string is HTML-escaped before display.
    if hasattr(st, "iframe"):
        st.iframe(html, height=1150)
    else:
        components.html(html, height=1150, scrolling=True)
    col1, col2, col3 = st.columns(3)
    col1.download_button("Dossier (HTML)", html, file_name=f"{d['case_id']}_dossier.html", mime="text/html")
    col2.download_button("Dossier (JSON)", (Path(out) / "dossier.json").read_text(), file_name=f"{d['case_id']}_dossier.json")
    col3.download_button("Audit trail (JSONL)", (Path(out) / "audit.jsonl").read_text(), file_name=f"{d['case_id']}_audit.jsonl")
