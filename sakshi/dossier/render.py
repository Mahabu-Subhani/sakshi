"""Render the investigation dossier as one self-contained, interactive HTML file.

Sections follow the problem statement (7.1 Document Overview ... 7.6 Investigation
Summary) plus the verification coverage map and the audit trail. Every finding
can be traced back to its source pixels: clicking it opens the original page
with the evidence boxes drawn in original pixel coordinates.
"""
from __future__ import annotations

import base64
import json
from pathlib import Path

import cv2


def _img(path: str, max_w: int = 1100, q: int = 72) -> str:
    try:
        im = cv2.imread(str(path))
        if im is None:
            return ""
        if im.shape[1] > max_w:
            s = max_w / im.shape[1]
            im = cv2.resize(im, None, fx=s, fy=s, interpolation=cv2.INTER_AREA)
        ok, buf = cv2.imencode(".jpg", im, [cv2.IMWRITE_JPEG_QUALITY, q])
        return "data:image/jpeg;base64," + base64.b64encode(buf.tobytes()).decode() if ok else ""
    except Exception:
        return ""


def _slim(dossier: dict) -> dict:
    d = json.loads(json.dumps(dossier, default=str))
    for doc in d["documents"]:
        for p in doc["pages"]:
            p["img"] = _img(p.pop("image"))
        arts = doc.get("structure", {}).get("artifacts", {})
        doc["heatmaps"] = {k: _img(v, 900, 65) for k, v in arts.items()}
        # no local file paths inside the shareable HTML
        doc.get("structure", {}).pop("artifacts", None)
        for L in doc.get("structure", {}).get("scan_overlays", []):
            L.pop("base_image", None)
        for s in doc.get("structure", {}).get("signatures", []):
            s["img"] = _img(s.get("crop", ""), 500, 80)
            s.pop("crop", None)
    for f in d["findings"]:
        for ev in f["evidence"]:
            c = ev.get("crop", "")
            ev["img"] = _img(c, 700, 78) if c and c.endswith(".jpg") and "_noise" not in c else ""
            ev.pop("crop", None)
    for r in d["audit"].get("records", []):
        p = r.get("payload", {})
        if "error" in p:
            p["error"] = str(p["error"])[-400:]
    return d


def render(dossier: dict, out_path: str | Path) -> str:
    data = json.dumps(_slim(dossier), default=str).replace("</", "<\\/")
    html = TEMPLATE.replace("__DATA__", data).replace("__CASE__", dossier["case_id"])
    Path(out_path).write_text(html, encoding="utf-8")
    return str(out_path)


TEMPLATE = r"""<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<title>SAKSHI Dossier __CASE__</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Spectral:wght@500;600&family=IBM+Plex+Sans:wght@400;500;600&family=IBM+Plex+Mono:wght@400;500&display=swap">
<style>
/* Layout: case-file header, section tabs (7.1-7.6 + coverage + audit), investigation view = findings rail + evidence viewer */
:root{
  --bg:#eef0ee; --surface:#ffffff; --sunk:#f6f7f5; --ink:#161b1f; --muted:#56616b; --line:#d6dbdc;
  --accent:#1d4e89; --accent-soft:#e3ecf7;
  --pm:#a4231c; --pm-soft:#fbe9e7; --inc:#8a5a00; --inc-soft:#fdf1d8; --obs:#4d5b68; --obs-soft:#e8ecef;
  --ok:#1f6f43; --ok-soft:#e3f3ea;
  --f-display:"Spectral", Georgia, "Times New Roman", serif;
  --f-body:"IBM Plex Sans", system-ui, -apple-system, "Segoe UI", sans-serif;
  --f-mono:"IBM Plex Mono", ui-monospace, "SFMono-Regular", Menlo, Consolas, monospace;
}
@media (prefers-color-scheme: dark){:root:not([data-theme="light"]){
  --bg:#0f1214; --surface:#171c20; --sunk:#12171a; --ink:#e4e8ea; --muted:#98a3ab; --line:#2a3238;
  --accent:#8db7ee; --accent-soft:#1b2a3d;
  --pm:#ff8f84; --pm-soft:#3a1714; --inc:#e8b54a; --inc-soft:#33270e; --obs:#a2aeb8; --obs-soft:#222a30;
  --ok:#6fd39a; --ok-soft:#14301f; color-scheme:dark}}
:root[data-theme="dark"]{
  --bg:#0f1214; --surface:#171c20; --sunk:#12171a; --ink:#e4e8ea; --muted:#98a3ab; --line:#2a3238;
  --accent:#8db7ee; --accent-soft:#1b2a3d;
  --pm:#ff8f84; --pm-soft:#3a1714; --inc:#e8b54a; --inc-soft:#33270e; --obs:#a2aeb8; --obs-soft:#222a30;
  --ok:#6fd39a; --ok-soft:#14301f; color-scheme:dark}
*{box-sizing:border-box}
body{background:var(--bg);color:var(--ink);font:14px/1.5 var(--f-body);margin:0}
.wrap{max-width:1360px;margin:0 auto;padding-left:max(16px,env(safe-area-inset-left,0px));padding-right:max(16px,env(safe-area-inset-right,0px));padding-block:20px 48px}
h1,h2,h3{text-wrap:balance;margin:0}
h1{font:600 28px/1.15 var(--f-display);letter-spacing:-.01em}
h2{font:600 20px/1.25 var(--f-display);margin-bottom:10px}
h3{font:600 14px/1.3 var(--f-body)}
.mono{font-family:var(--f-mono);font-size:12px}
.muted{color:var(--muted)}
.eyebrow{font:500 11px/1 var(--f-body);letter-spacing:.09em;text-transform:uppercase;color:var(--muted)}
header.case{display:grid;grid-template-columns:1fr auto;gap:16px;align-items:end;padding-bottom:14px;border-bottom:2px solid var(--ink)}
.case-meta{display:flex;flex-wrap:wrap;gap:6px 18px;margin-top:8px;color:var(--muted);font-size:13px}
.status{display:inline-flex;align-items:center;gap:8px;padding:6px 12px;border-radius:4px;font-weight:600;font-size:13px}
.status.pm{background:var(--pm-soft);color:var(--pm)} .status.inc{background:var(--inc-soft);color:var(--inc)} .status.ok{background:var(--ok-soft);color:var(--ok)}
.counts{display:flex;gap:8px;flex-wrap:wrap;justify-content:flex-end;margin-top:8px}
.tier{display:inline-flex;align-items:center;gap:6px;font:600 11px/1 var(--f-body);letter-spacing:.05em;text-transform:uppercase;padding:4px 7px;border-radius:3px;white-space:nowrap}
.tier.POTENTIAL_MANIPULATION{background:var(--pm-soft);color:var(--pm)}
.tier.INCONSISTENCY{background:var(--inc-soft);color:var(--inc)}
.tier.OBSERVATION{background:var(--obs-soft);color:var(--obs)}
nav.tabs{display:flex;gap:2px;overflow-x:auto;margin:14px 0 18px;border-bottom:1px solid var(--line)}
nav.tabs button{font:500 13px var(--f-body);color:var(--muted);background:none;border:0;border-bottom:2px solid transparent;padding:10px 12px;cursor:pointer;white-space:nowrap}
nav.tabs button[aria-selected="true"]{color:var(--ink);border-bottom-color:var(--accent)}
nav.tabs button:focus-visible,button:focus-visible,.fitem:focus-visible{outline:2px solid var(--accent);outline-offset:2px}
.panel{background:var(--surface);border:1px solid var(--line);border-radius:6px;padding:16px}
.grid2{display:grid;grid-template-columns:minmax(0,1fr) minmax(0,1fr);gap:16px}
.invest{display:grid;grid-template-columns:minmax(300px,400px) minmax(0,1fr);gap:16px;align-items:start}
.stack{display:flex;flex-direction:column;gap:12px}
.rail{display:flex;flex-direction:column;gap:6px;max-height:calc(100vh - 120px);overflow:auto;position:sticky;top:max(12px,env(safe-area-inset-top,0px));padding-right:4px}
.filters{display:flex;gap:6px;flex-wrap:wrap;margin-bottom:6px}
.chip{font:500 12px var(--f-body);padding:5px 9px;border-radius:999px;border:1px solid var(--line);background:var(--surface);color:var(--ink);cursor:pointer}
.chip[aria-pressed="true"]{background:var(--ink);color:var(--surface);border-color:var(--ink)}
.group{display:flex;flex-direction:column;gap:6px;padding:10px;border:1px solid var(--line);border-radius:6px;background:var(--sunk)}
.ghead{display:flex;gap:8px;align-items:center}
.gtitle{font:600 13px/1.35 var(--f-body);margin-bottom:2px}
.fitem{display:grid;grid-template-columns:4px 1fr;gap:10px;background:var(--surface);border:1px solid var(--line);border-radius:5px;padding:10px 10px 10px 0;cursor:pointer;text-align:left;color:var(--ink);font:inherit;width:100%}
.fitem .stripe{border-radius:0 3px 3px 0}
.fitem.POTENTIAL_MANIPULATION .stripe{background:var(--pm)} .fitem.INCONSISTENCY .stripe{background:var(--inc)} .fitem.OBSERVATION .stripe{background:var(--obs)}
.fitem[aria-current="true"]{border-color:var(--accent);box-shadow:0 0 0 1px var(--accent)}
.fitem .t{font-weight:500;font-size:13px;line-height:1.35}
.fitem .m{display:flex;gap:8px;align-items:center;margin-bottom:4px;flex-wrap:wrap}
.sev{font:500 11px var(--f-mono);color:var(--muted)}
.viewer{position:relative;background:var(--sunk);border:1px solid var(--line);border-radius:6px;overflow:auto;max-height:72vh}
.viewer svg{display:block;width:100%;height:auto}
.viewer .lbl{font:600 22px var(--f-body)}
.docbar{display:flex;gap:8px;align-items:center;flex-wrap:wrap;margin-bottom:8px}
.docbar select{font:inherit;padding:5px 8px;border:1px solid var(--line);border-radius:4px;background:var(--surface);color:var(--ink);max-width:100%}
.detail h3{font:600 17px/1.3 var(--f-display)}
.detail p{max-width:75ch;margin:6px 0}
table{border-collapse:collapse;width:100%;font-size:13px}
th,td{text-align:left;padding:7px 8px;border-bottom:1px solid var(--line);vertical-align:top}
th{font:600 11px var(--f-body);letter-spacing:.06em;text-transform:uppercase;color:var(--muted);background:var(--sunk)}
td.num{font-variant-numeric:tabular-nums;font-family:var(--f-mono);font-size:12px;text-align:right}
.tbl{overflow-x:auto;border:1px solid var(--line);border-radius:5px;background:var(--surface)}
.res{font:600 11px var(--f-body);text-transform:uppercase;letter-spacing:.05em}
.res.ruled_out{color:var(--ok)} .res.plausible{color:var(--inc)} .res.explains{color:var(--obs)} .res.not_testable{color:var(--muted)}
.evlist{display:flex;flex-direction:column;gap:8px}
.ev{display:grid;grid-template-columns:minmax(0,160px) minmax(0,1fr);gap:10px;align-items:start;border:1px solid var(--line);border-radius:5px;padding:8px;background:var(--sunk)}
.ev img{border-radius:3px;border:1px solid var(--line);background:var(--surface);max-width:100%;height:auto}
.ev.wide{grid-template-columns:1fr}
.linkbtn{font:500 12px var(--f-body);color:var(--accent);background:none;border:0;padding:0;cursor:pointer;text-decoration:underline;text-underline-offset:2px}
.kv{display:grid;grid-template-columns:max-content minmax(0,1fr);gap:4px 14px;font-size:13px}
.kv dt{color:var(--muted)} .kv dd{margin:0;overflow-wrap:anywhere}
.callout{border-left:3px solid var(--accent);background:var(--accent-soft);padding:10px 12px;border-radius:0 5px 5px 0;max-width:90ch}
.thread{border:1px solid var(--line);border-radius:5px;padding:12px;background:var(--surface);display:flex;flex-direction:column;gap:6px}
.pill{display:inline-block;font:500 11px var(--f-body);padding:2px 7px;border-radius:3px;background:var(--sunk);border:1px solid var(--line);color:var(--muted);margin-right:4px}
.cov.STRONG{color:var(--ok);font-weight:600} .cov.WEAK{color:var(--inc);font-weight:600} .cov.BLIND{color:var(--pm);font-weight:600}
.bar{display:flex;height:10px;border-radius:5px;overflow:hidden;background:var(--sunk);border:1px solid var(--line)}
.bar span{display:block;height:100%}
.timeline{display:flex;flex-direction:column;gap:0}
.timeline div{display:grid;grid-template-columns:120px 1fr;gap:12px;padding:6px 0;border-bottom:1px dashed var(--line);font-size:13px}
.graph text{fill:var(--ink);font:12px var(--f-body)}
.sigs{display:flex;gap:10px;flex-wrap:wrap}
.sigs figure{margin:0;border:1px solid var(--line);border-radius:5px;padding:6px;background:var(--surface);max-width:260px}
.sigs figcaption{font-size:12px;color:var(--muted);margin-top:4px}
.section-note{color:var(--muted);font-size:13px;margin:-4px 0 12px;max-width:90ch}
@media (max-width:900px){.invest,.grid2{grid-template-columns:1fr}.rail{position:static;max-height:none}header.case{grid-template-columns:1fr}.counts{justify-content:flex-start}.ev{grid-template-columns:1fr}}
@media (prefers-reduced-motion:reduce){*{transition:none!important;animation:none!important}}
</style>

<div class="wrap">
  <header class="case">
    <div>
      <div class="eyebrow">SAKSHI investigation dossier · analyst use only</div>
      <h1 id="h-title"></h1>
      <div class="case-meta" id="h-meta"></div>
    </div>
    <div>
      <div id="h-status"></div>
      <div class="counts" id="h-counts"></div>
    </div>
  </header>
  <nav class="tabs" role="tablist" id="tabs"></nav>
  <main id="main"></main>
</div>

<script>
const D = __DATA__;
const $ = (s, el=document) => el.querySelector(s);
const esc = s => String(s ?? "").replace(/[&<>"]/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));
const docs = Object.fromEntries(D.documents.map(d => [d.doc_id, d]));
const findings = D.findings;
const assess = D.document_assessments || [];
const byId = Object.fromEntries([...findings, ...assess].map(f => [f.id, f]));
const TIERS = {POTENTIAL_MANIPULATION:"Potential manipulation", INCONSISTENCY:"Inconsistency", OBSERVATION:"Observation"};
const WIT = ["L0 claim","L1 weak witness","L2 standard witness","L3 signed","L4 direct source"];
const tierTag = t => `<span class="tier ${t}">${TIERS[t]||t}</span>`;
const fmtV = v => typeof v === "number" ? v.toLocaleString("en-IN",{minimumFractionDigits:2,maximumFractionDigits:2}) : esc(v);
let state = {finding: null, filter: "ALL", doc: D.documents[0]?.doc_id, page: 0, boxes: []};

function header(){
  $("#h-title").textContent = `Case ${D.case_id}`;
  $("#h-meta").innerHTML = [
    `${D.documents.length} documents`, `generated ${esc(D.generated_at)}`, `${D.processing_seconds}s processing`,
    `SAKSHI ${esc(D.sakshi_version)}`, D.environment ? `OCR Tesseract ${esc(D.environment.tesseract)}` : "",
    `audit chain: <b style="color:var(${D.audit.verified?'--ok':'--pm'})">${esc(D.audit.message)}</b>`,
    D.environment && D.environment.warning ? `<b style="color:var(--inc)" title="${esc(D.environment.warning)}">OCR version differs from the calibrated one</b>` : ""
  ].filter(Boolean).map(x=>`<span>${x}</span>`).join("");
  const c = D.counts, cls = c.potential_manipulation ? "pm" : c.inconsistency ? "inc" : "ok";
  $("#h-status").innerHTML = `<span class="status ${cls}">${esc(D.status)}</span>`;
  $("#h-counts").innerHTML = `${tierTag("POTENTIAL_MANIPULATION")} <b>${c.potential_manipulation}</b> ${tierTag("INCONSISTENCY")} <b>${c.inconsistency}</b> ${tierTag("OBSERVATION")} <b>${c.observation}</b>`;
}

const TABS = [
  ["investigate","Investigation"], ["overview","7.1 Document overview"], ["extracted","7.2 Extracted information"],
  ["context","7.3 Contextual analysis"], ["visual","7.4 Visual forensics"], ["evidence","7.5 Evidence & traceability"],
  ["summary","7.6 Investigation summary"], ["coverage","Coverage map"], ["audit","Audit trail"]];

function tabs(){
  $("#tabs").innerHTML = TABS.map(([k,l]) => `<button role="tab" id="tab-${k}" data-k="${k}">${l}</button>`).join("");
  $("#tabs").onclick = e => { const b = e.target.closest("button"); if (b) go(b.dataset.k); };
}
function go(k){
  if (!TABS.find(t=>t[0]===k)) k = "investigate";
  document.querySelectorAll("#tabs button").forEach(b => b.setAttribute("aria-selected", b.dataset.k===k));
  try { if (location.hash.slice(1)!==k) history.replaceState(null,"","#"+k); } catch(e){}
  ({investigate, overview, extracted, context, visual, evidence, summary, coverage, audit})[k]();
}

/* ---------------- evidence viewer ---------------- */
function viewerHTML(){
  const opts = D.documents.map(d => d.pages.map(p => `<option value="${d.doc_id}|${p.index}">${esc(d.doc_id)} · ${esc(d.filename)}${d.pages.length>1?` · p${p.index+1}`:""}</option>`).join("")).join("");
  return `<div class="docbar"><label class="eyebrow" for="docsel">Source document</label><select id="docsel">${opts}</select><span class="muted" id="docinfo"></span></div><div class="viewer" id="viewer"></div>`;
}
function drawViewer(){
  const d = docs[state.doc]; if (!d) return;
  const p = d.pages[state.page] || d.pages[0];
  $("#docsel").value = `${d.doc_id}|${p.index}`;
  $("#docinfo").textContent = `${d.type_label} · ${d.modality.replace("_"," ")} · ${WIT[d.witness]}`;
  const boxes = state.boxes.filter(b => b.doc_id===d.doc_id && b.page===p.index && b.kind!=="file" && b.kind!=="reconstruction" && b.kind!=="peel");
  const sw = Math.max(3, p.width/350);
  const rects = boxes.map((b,i) => { const [x0,y0,x1,y1]=b.bbox; const col = b.color || "var(--accent)";
    return `<rect x="${x0-4}" y="${y0-4}" width="${x1-x0+8}" height="${y1-y0+8}" fill="none" stroke="${col}" stroke-width="${sw}" rx="4"/>
            <rect x="${x0-4}" y="${Math.max(0,y0-38)}" width="${Math.max(34, 16+14*String(i+1).length)}" height="30" fill="${col}" rx="3"/>
            <text class="lbl" x="${x0+4}" y="${Math.max(22,y0-16)}" fill="var(--surface)">${i+1}</text>`; }).join("");
  $("#viewer").innerHTML = `<svg viewBox="0 0 ${p.width} ${p.height}" role="img" aria-label="${esc(d.filename)} with ${boxes.length} highlighted region(s)">
     <image href="${p.img}" x="0" y="0" width="${p.width}" height="${p.height}"/>${rects}</svg>`;
  if (boxes.length){ const b = boxes[0]; const v = $("#viewer"); const s = v.clientWidth / p.width;
    v.scrollTop = Math.max(0, b.bbox[1]*s - 120); }
}
function show(docId, page, boxes){
  state.doc = docId; state.page = page||0; state.boxes = boxes||[];
  if (!$("#viewer")) { go("investigate"); }
  drawViewer();
  $("#viewer").scrollIntoView({block:"nearest", behavior:"smooth"});
}
const tierColor = t => t==="POTENTIAL_MANIPULATION" ? "var(--pm)" : t==="INCONSISTENCY" ? "var(--inc)" : "var(--obs)";

/* ---------------- investigation ---------------- */
function investigate(){
  $("#main").innerHTML = `<div class="invest">
    <aside><div class="filters" id="filters"></div><div class="rail" id="rail"></div></aside>
    <section class="stack">${viewerHTML()}<div class="panel detail" id="detail"></div></section></div>`;
  const f = [["ALL","All"],["POTENTIAL_MANIPULATION","Potential manipulation"],["INCONSISTENCY","Inconsistency"],["OBSERVATION","Observation"]];
  $("#filters").innerHTML = f.map(([k,l]) => `<button class="chip" aria-pressed="${state.filter===k}" data-k="${k}">${l} ${k==="ALL"?findings.length:findings.filter(x=>x.tier===k).length}</button>`).join("");
  $("#filters").onclick = e => { const b=e.target.closest("button"); if(!b) return; state.filter=b.dataset.k; investigate(); };
  const item = x => `<button class="fitem ${x.tier}" data-id="${x.id}" aria-current="${state.finding===x.id}">
      <span class="stripe"></span><span><span class="m">${tierTag(x.tier)}<span class="sev">${x.id} · severity ${x.severity}${x.repair&&x.repair.supports?" · supporting":""}</span></span>
      <span class="t">${esc(x.title)}</span></span></button>`;
  let html = "";
  if (state.filter === "ALL") {
    const used = new Set();
    D.threads.forEach((t, i) => {
      const fs = t.findings.map(id => byId[id]).filter(Boolean); fs.forEach(f => used.add(f.id));
      html += `<div class="group"><div class="ghead">${tierTag(t.tier)}<span class="eyebrow">Hypothesis ${i+1}</span></div><div class="gtitle">${esc(t.title)}</div>${fs.map(item).join("")}</div>`;
    });
    if (assess.length) html += `<div class="group"><div class="ghead"><span class="eyebrow">Document assessments</span></div><div class="gtitle muted">Summaries of several independent findings on one document. Not counted as separate findings.</div>${assess.map(item).join("")}</div>`;
    const rest = findings.filter(f => !used.has(f.id));
    if (rest.length) html += `<div class="group"><div class="ghead"><span class="eyebrow">Other observations</span></div>${rest.map(item).join("")}</div>`;
  } else {
    html = findings.filter(x => x.tier===state.filter).map(item).join("");
  }
  $("#rail").innerHTML = html || `<p class="muted">No findings in this tier.</p>`;
  $("#rail").onclick = e => { const b=e.target.closest(".fitem"); if(b) selectFinding(b.dataset.id); };
  $("#docsel").onchange = e => { const [d,p]=e.target.value.split("|"); state.doc=d; state.page=+p; state.boxes=[]; drawViewer(); };
  if (!state.finding && findings.length) state.finding = findings[0].id;
  if (state.finding) selectFinding(state.finding, true); else { drawViewer(); $("#detail").innerHTML = `<p class="muted">No findings for this case.</p>`; }
}
function selectFinding(id, quiet){
  const f = byId[id]; if (!f) return; state.finding = id;
  document.querySelectorAll(".fitem").forEach(b => b.setAttribute("aria-current", b.dataset.id===id));
  const evs = f.evidence.map(e => ({...e, color: tierColor(f.tier)}));
  const first = evs.find(e=>e.kind!=="file") || evs[0];
  state.boxes = evs; if (first){ state.doc = first.doc_id; state.page = first.page; }
  drawViewer();
  const ben = f.benign.length ? `<div class="tbl"><table><thead><tr><th>Innocent explanation</th><th>Deterministic test</th><th>Result</th></tr></thead><tbody>${
      f.benign.map(b=>`<tr><td>${esc(b.explanation)}</td><td class="muted">${esc(b.test)}${b.detail?`<br><span class="mono">${esc(b.detail)}</span>`:""}</td><td><span class="res ${b.result}">${b.result.replace("_"," ")}</span></td></tr>`).join("")}</tbody></table></div>` : `<p class="muted">No innocent explanations apply to this check type.</p>`;
  const rep = f.repair && f.repair.proposed!==undefined ? `<div class="callout"><b>Counterfactual repair.</b> Reads <span class="mono">${fmtV(f.repair.current)}</span>; every rule holds only if it were <span class="mono">${fmtV(f.repair.proposed)}</span>. Diagnosis ${esc(f.repair.diagnosis)} · cost ${f.repair.cost}${f.repair.ambiguous?" · <b>ambiguous</b>":""}${f.repair.claim?" · self-declared claim (L0)":""}</div>` :
      f.repair && f.repair.recovered_value ? `<div class="callout"><b>Recovered from the file:</b> <span class="mono">${esc(f.repair.recovered_value)}</span> was the value before <span class="mono">${esc(f.repair.displayed_value || f.repair.seen || "a new value")}</span> was drawn over it.</div>` : "";
  const cor = (f.corroborated_by||[]).length ? `<p><span class="eyebrow">Corroborated by</span><br>${f.corroborated_by.map(c=>byId[c]?`<button class="linkbtn" data-goto="${c}">${c}</button> <span class="muted">${esc(byId[c].title.slice(0,80))}</span>`:"").join("<br>")}</p>` : "";
  $("#detail").innerHTML = `<div class="stack">
    <div class="m" style="display:flex;gap:8px;align-items:center;flex-wrap:wrap">${tierTag(f.tier)}<span class="sev">${f.id} · ${esc(f.check.replace(/_/g," "))} · ${esc(f.family.replace("_"," "))} · <b>${esc(f.strength||"")}</b> · confidence ${Math.round(f.confidence*100)}% · severity ${f.severity}</span></div>
    <h3>${esc(f.title)}</h3><p>${esc(f.detail)}</p>${rep}
    <div><div class="eyebrow" style="margin-bottom:6px">Evidence (numbered boxes on the page)</div><div class="evlist">${f.evidence.map((e,i)=>`
      <div class="ev${e.kind==="peel"||e.kind==="reconstruction"?" wide":""}">${e.img?`<img src="${e.img}" alt="evidence crop ${i+1}">`:`<span class="muted mono">${e.kind==="file"?"file-level evidence":"—"}</span>`}
      <div><b>${i+1}.</b> ${esc(e.note)}<br><span class="mono muted">${esc(e.doc_id)} · ${esc(docs[e.doc_id]?.filename)} · page ${e.page+1} · bbox [${e.bbox.map(v=>Math.round(v)).join(", ")}]${e.value?` · value "${esc(e.value)}"`:""}</span><br>
      ${e.kind!=="file"?`<button class="linkbtn" data-show="${i}">Show in source document</button>`:""}</div></div>`).join("")}</div></div>
    <div><div class="eyebrow" style="margin-bottom:6px">Devil's advocate</div>${ben}</div>
    ${cor}${f.verify_next?`<p><span class="eyebrow">Verify next</span><br>${esc(f.verify_next)}</p>`:""}
    ${f.fields.length?`<p class="mono muted">fields: ${f.fields.map(esc).join(", ")}</p>`:""}</div>`;
  $("#detail").onclick = e => { const s=e.target.closest("[data-show]"); if (s){ const ev=evs[+s.dataset.show]; state.doc=ev.doc_id; state.page=ev.page; drawViewer(); $("#viewer").scrollIntoView({block:"nearest",behavior:"smooth"}); }
    const g=e.target.closest("[data-goto]"); if (g){ state.filter="ALL"; investigate(); selectFinding(g.dataset.goto); } };
  if (!quiet) $("#detail").scrollIntoView({block:"nearest", behavior:"smooth"});
}

/* ---------------- 7.1 overview ---------------- */
function overview(){
  const cc = D.cross_case||{};
  $("#main").innerHTML = `<p class="section-note">Identification, type, source and processing status of every submitted document. Witness level sets how much a document counts when documents disagree. Cross-case memory: ${cc.enabled?`on, compared with ${cc.prior_cases} earlier case(s)`:"off for this run"}.</p><div class="stack">${D.documents.map(d=>`
    <div class="panel"><div style="display:flex;justify-content:space-between;gap:12px;flex-wrap:wrap"><h2>${esc(d.doc_id)} · ${esc(d.filename)}</h2><span class="pill">${esc(d.status)}</span></div>
    <dl class="kv"><dt>Type</dt><dd>${esc(d.type_label)} (confidence ${Math.round(d.type_confidence*100)}%) · cues: ${d.type_evidence.map(esc).join(", ")||"none"}</dd>
    <dt>Source</dt><dd>${esc(d.modality.replace("_"," "))}, ${d.pages.length} page(s), skew ${d.pages[0]?.skew_deg}°${d.pages[0]?.noise_sigma?`, sensor noise σ≈${d.pages[0].noise_sigma}`:""}</dd>
    <dt>Witness level</dt><dd>${WIT[d.witness]}</dd>
    ${d.structure.table_layout?`<dt>Statement layout</dt><dd>${esc(d.structure.table_layout.replace(/_/g," "))}, balance fit ${Math.round((d.structure.transition_fit||0)*100)}%</dd>`:""}
    <dt>SHA-256</dt><dd class="mono">${esc(d.sha256)}</dd>
    ${Object.keys(d.pdf_meta||{}).length?`<dt>PDF metadata</dt><dd class="mono">${Object.entries(d.pdf_meta).filter(([k])=>!["format","encryption","trapped"].includes(k)).map(([k,v])=>`${esc(k)}: ${esc(v)}`).join("<br>")}</dd>`:""}
    <dt>Sections</dt><dd>${(d.structure.sections||[]).map(esc).join(" → ")}</dd>
    <dt>Sensors</dt><dd>${Object.entries(d.capabilities).map(([k,v])=>`<span class="pill">${esc(k)}: ${esc(typeof v==="object"?Object.entries(v).map(([a,b])=>a+" "+b).join(", "):v)}</span>`).join(" ")}</dd>
    ${d.notes.length?`<dt>Notes</dt><dd>${d.notes.map(esc).join("<br>")}</dd>`:""}</dl></div>`).join("")}
    ${D.rejected.length?`<div class="panel"><h2>Rejected inputs</h2>${D.rejected.map(r=>`<p><b>${esc(r.file)}</b>: ${esc(r.reason)}</p>`).join("")}</div>`:""}</div>`;
}

/* ---------------- 7.2 extracted ---------------- */
function fieldRows(d){
  return d.fields.map(f=>`<tr><td>${esc(f.name.replace(/_/g," "))}</td><td class="mono">${esc(f.raw)}</td><td class="mono">${fmtV(f.value)}</td>
    <td class="num">${Math.round(f.conf*100)}%</td><td class="muted">${esc(f.method)}</td><td><button class="linkbtn" data-loc="${d.doc_id}|${f.page}|${f.bbox.join(",")}">p${f.page+1} [${f.bbox.map(v=>Math.round(v)).join(",")}]</button></td></tr>`).join("");
}
function extracted(){
  $("#main").innerHTML = `<p class="section-note">Every value with its OCR confidence, extraction method and its location on the original page. Confidence is never treated as truth: low-confidence values are cheaper to blame in the repair solver.</p>
  <div class="stack">${D.documents.map(d=>{
    const t = d.tables||{}; const tx = (t.transactions||[]);
    const comp = [...(t.earnings||[]).map(f=>["Earning",f]), ...(t.deductions||[]).map(f=>["Deduction",f])];
    return `<div class="panel"><h2>${esc(d.doc_id)} · ${esc(d.type_label)}</h2>
      <div class="tbl"><table><thead><tr><th>Field</th><th>As read</th><th>Normalized</th><th>Conf.</th><th>Method</th><th>Location</th></tr></thead><tbody>${fieldRows(d)||`<tr><td colspan="6" class="muted">No labelled fields extracted.</td></tr>`}</tbody></table></div>
      ${comp.length?`<h3 style="margin:14px 0 6px">Earnings and deductions</h3><div class="tbl"><table><thead><tr><th>Side</th><th>Component</th><th>Amount</th><th>Conf.</th><th>Location</th></tr></thead><tbody>${comp.map(([s,f])=>`<tr><td>${s}</td><td>${esc(f.name.replace(/_/g," "))}</td><td class="num">${fmtV(f.value)}</td><td class="num">${Math.round(f.conf*100)}%</td><td><button class="linkbtn" data-loc="${d.doc_id}|${f.page}|${f.bbox.join(",")}">show</button></td></tr>`).join("")}</tbody></table></div>`:""}
      ${tx.length?`<h3 style="margin:14px 0 6px">Transactions (${tx.length} rows)</h3><div class="tbl"><table><thead><tr><th>Date</th><th>Description</th><th>Debit</th><th>Credit</th><th>Balance</th><th></th></tr></thead><tbody>${tx.map(r=>`<tr><td class="mono">${esc(r.date)}</td><td>${esc(r.description)}</td><td class="num">${r.debit?fmtV(r.debit.value):""}</td><td class="num">${r.credit?fmtV(r.credit.value):""}</td><td class="num">${r.balance?fmtV(r.balance.value):""}</td><td><button class="linkbtn" data-loc="${d.doc_id}|${r.page}|${r.bbox.join(",")}">row</button></td></tr>`).join("")}</tbody></table></div>`:""}
      ${d.structure.table_layout?`<p class="callout" style="margin-top:12px">Table layout worked out from the running balance: <b>${esc(d.structure.table_layout.replace(/_/g," "))}</b> (balance equation holds on ${Math.round((d.structure.transition_fit||0)*100)}% of rows). ${(d.structure.healed||[]).length?`OCR re-reads: ${d.structure.healed.map(h=>`"${esc(h.first_read)}" re-read as "${esc(h.second_read)}"`).join("; ")}.`:"No cell needed a re-read."}</p>`:""}
      ${d.pages.some(p=>p.hidden_words.length)?`<p class="callout" style="margin-top:12px">Text present in the file but painted over (not visible to a reader): <span class="mono">${d.pages.flatMap(p=>p.hidden_words).map(esc).join(", ")}</span></p>`:""}
      ${(d.structure.missing||[]).length?`<p class="muted">Missing required fields: ${d.structure.missing.map(esc).join(", ")}</p>`:""}
    </div>`;}).join("")}</div>`;
  bindLoc();
}
function bindLoc(){
  $("#main").onclick = e => { const b = e.target.closest("[data-loc]"); if (!b) return; const [d,p,bb] = b.dataset.loc.split("|");
    state.finding = null; go("investigate"); state.doc=d; state.page=+p; state.boxes=[{doc_id:d,page:+p,bbox:bb.split(",").map(Number),color:"var(--accent)"}]; drawViewer();
    $("#detail").innerHTML = `<p class="muted">Showing the location of a value from section 7.2. Pick a finding on the left to see evidence.</p>`; };
}

/* ---------------- 7.3 context ---------------- */
function context(){
  const rules = D.rules; const broken = rules.filter(r=>r.status==="broken");
  const ctxF = findings.filter(f=>["logical","cross_document","identity","fusion","pattern","statutory","cross_case"].includes(f.family));
  $("#main").innerHTML = `<p class="section-note">SAKSHI treats each document as a program with rules, and the application as one system of documents. ${rules.length} rules were checked; ${broken.length} are broken.</p>
  <div class="stack"><div class="panel"><h2>Claim graph</h2><p class="muted" style="margin-top:-4px">Documents on the left, the facts they assert on the right. Red edges are values blamed by a diagnosis or conflicting with the majority.</p><div class="tbl" style="border:0">${graph()}</div></div>
  <div class="panel"><h2>Counterfactual diagnoses</h2>${D.diagnoses.length?D.diagnoses.map(dg=>`<div class="thread"><div><span class="pill">${esc(dg.id)}</span><b>${dg.violated.length} broken rule(s)</b> <span class="muted">· ${dg.candidates} candidate fields searched</span></div>
    <ul style="margin:0;padding-left:18px">${dg.violated_text.map(t=>`<li>${esc(t)}</li>`).join("")}</ul>
    ${dg.best?`<div class="callout">Smallest consistent explanation (${dg.best.k} change${dg.best.k>1?"s":""}, cost ${dg.best.cost}): ${Object.entries(dg.best.fields).map(([k,v])=>`<span class="mono">${esc(k)}</span> → <b class="mono">${fmtV(v)}</b>`).join("; ")}${dg.ambiguous?" · <b>ambiguous</b>":""}</div>`:`<p class="muted">No explanation with up to 3 changes.</p>`}
    ${(dg.alternatives||[]).length?`<p class="muted">Alternatives: ${dg.alternatives.map(a=>Object.entries(a.fields).map(([k,v])=>`${esc(k)}→${fmtV(v)}`).join(", ")+` (cost ${a.cost})`).join(" | ")}</p>`:""}</div>`).join(""):`<p class="muted">No arithmetic or cross-document rule is broken.</p>`}</div>
  <div class="panel"><h2>Contextual and cross-document findings</h2>${listOf(ctxF)}</div>
  <div class="panel"><h2>Expected records</h2>${(D.expectations||[]).map(x=>`<p>${x.found?"✓":"✗"} ${esc(x.text)}${x.found?` <span class="muted mono">matched ${esc(x.ref)}</span>`:""}</p>`).join("")||`<p class="muted">No expectations generated.</p>`}</div>
  <div class="panel"><h2>All rules checked</h2><div class="tbl"><table><thead><tr><th>Status</th><th>Rule</th><th>Scope</th><th>Residual / values</th></tr></thead><tbody>${rules.map(r=>`<tr><td><span class="res ${r.status==="broken"?"plausible":"ruled_out"}">${r.status}</span>${r.soft?' <span class="pill">soft</span>':""}</td><td>${esc(r.text)}</td><td>${esc(r.scope)}</td><td class="mono">${r.residual!==undefined?fmtV(r.residual):(r.values||[]).map(esc).join(" | ")}</td></tr>`).join("")}</tbody></table></div></div></div>`;
  bindList();
}
function listOf(fs){
  return fs.length ? `<div class="stack">${fs.map(f=>`<button class="fitem ${f.tier}" data-id="${f.id}"><span class="stripe"></span><span><span class="m">${tierTag(f.tier)}<span class="sev">${f.id} · severity ${f.severity}</span></span><span class="t">${esc(f.title)}</span></span></button>`).join("")}</div>` : `<p class="muted">None.</p>`;
}
function bindList(){ $("#main").onclick = e => { const b=e.target.closest(".fitem"); if(b){ state.filter="ALL"; state.finding=b.dataset.id; go("investigate"); } }; }
function graph(){
  const G = D.claim_graph; const dn = G.nodes.filter(n=>n.type==="doc"), an = G.nodes.filter(n=>n.type==="attr");
  const H = Math.max(dn.length, an.length)*46+30, W = 760;
  const ys = (arr, id) => 30 + arr.findIndex(n=>n.id===id)*46 * (Math.max(dn.length,an.length)/Math.max(1,arr.length));
  const e = G.edges.map(x=>`<line x1="250" y1="${ys(dn,x.from)}" x2="520" y2="${ys(an,x.to)}" stroke="${x.status==="conflict"?"var(--pm)":"var(--line)"}" stroke-width="${x.status==="conflict"?2.5:1.2}"><title>${esc(x.value)}</title></line>`).join("");
  const dl = dn.map(n=>`<rect x="10" y="${ys(dn,n.id)-15}" width="240" height="30" rx="4" fill="var(--sunk)" stroke="var(--line)"/><text x="20" y="${ys(dn,n.id)+4}">${esc(n.id)} · ${esc(n.label.slice(0,28))}</text>`).join("");
  const al = an.map(n=>`<rect x="520" y="${ys(an,n.id)-15}" width="200" height="30" rx="15" fill="var(--accent-soft)" stroke="var(--line)"/><text x="534" y="${ys(an,n.id)+4}">${esc(n.label)}</text>`).join("");
  return `<svg class="graph" viewBox="0 0 ${W} ${H}" style="min-width:600px;width:100%">${e}${dl}${al}</svg>`;
}

/* ---------------- 7.4 visual ---------------- */
function visual(){
  const vf = findings.filter(f=>["visual","file_structure","pixel","optics","typography","geometry","signature"].includes(f.family));
  const heat = D.documents.flatMap(d=>Object.entries(d.heatmaps||{}).map(([k,v])=>({d,v})));
  const sigs = D.documents.flatMap(d=>(d.structure.signatures||[]).map(s=>({...s,d})));
  $("#main").innerHTML = `<p class="section-note">Observed visual and file-structure characteristics. These are observations about pixels and file objects; whether they amount to manipulation is decided in the fusion step with innocent explanations tested.</p>
  <div class="stack"><div class="panel"><h2>Visual and file-structure findings</h2>${listOf(vf)}</div>
  <div class="panel"><h2>Signatures found</h2><div class="sigs">${sigs.map(s=>`<figure>${s.img?`<img src="${s.img}" alt="signature on ${esc(s.d.filename)}">`:""}<figcaption>${esc(s.d.doc_id)} · ${esc(s.d.filename)} · p${s.page+1}</figcaption></figure>`).join("")||`<p class="muted">No blue-ink signatures detected.</p>`}</div></div>
  <div class="panel"><h2>Sensor-noise maps</h2><p class="muted" style="margin-top:-4px">Blue = cleaner than the page's own scanner noise, red = noisier. A pasted or whited-out region shows up as a solid block.</p><div class="grid2">${heat.map(h=>`<figure style="margin:0"><img src="${h.v}" alt="noise map ${esc(h.d.filename)}"><figcaption class="muted">${esc(h.d.doc_id)} · ${esc(h.d.filename)}</figcaption></figure>`).join("")||`<p class="muted">No scanned pages.</p>`}</div></div></div>`;
  bindList();
}

/* ---------------- 7.5 evidence ---------------- */
function evidence(){
  const rows = findings.flatMap(f=>f.evidence.map((e,i)=>({f,e,i})));
  $("#main").innerHTML = `<p class="section-note">Every finding traced to its original document location. Status distinguishes confirmed observations from potential anomalies.</p>
  <div class="tbl"><table><thead><tr><th>Finding</th><th>Status</th><th>Evidence</th><th>Document</th><th>Page · bbox (px)</th><th>Linked fields</th><th>Confidence</th></tr></thead><tbody>${rows.map(({f,e,i})=>`<tr>
    <td class="mono">${f.id}.${i+1}</td><td>${tierTag(f.tier)}</td><td>${esc(e.note)}${e.value?` <span class="mono">"${esc(e.value)}"</span>`:""}</td><td>${esc(docs[e.doc_id]?.filename)}</td>
    <td>${e.kind==="file"?`<span class="muted">file-level</span>`:`<button class="linkbtn" data-loc="${e.doc_id}|${e.page}|${e.bbox.join(",")}">p${e.page+1} [${e.bbox.map(v=>Math.round(v)).join(",")}]</button>`}</td>
    <td class="mono">${f.fields.slice(0,3).map(esc).join("<br>")}</td><td class="num">${Math.round(f.confidence*100)}% · ${esc(f.strength||"")}</td></tr>`).join("")}</tbody></table></div>`;
  bindLoc();
}

/* ---------------- 7.6 summary ---------------- */
function summary(){
  const verify = findings.filter(f=>f.tier!=="OBSERVATION" && f.verify_next);
  $("#main").innerHTML = `<div class="stack"><div class="panel"><h2>Investigation summary</h2><div style="white-space:pre-line;max-width:90ch">${esc(D.summary)}</div>
    ${D.llm_summary?`<div class="callout" style="margin-top:10px"><span class="eyebrow">AI-written restatement (${esc(D.llm_summary.model)}) · facts above are authoritative</span><br>${esc(D.llm_summary.text)}</div>`:""}</div>
  <div class="panel"><h2>Investigation threads</h2><div class="stack">${D.threads.map(t=>`<div class="thread"><div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap">${tierTag(t.tier)}<span class="sev">severity ${t.severity} · ${t.findings.length} finding(s) · ${t.families.map(esc).join(", ")}</span></div>
     <b>${esc(t.title)}</b>${t.lead&&t.lead!==t.title?`<span class="muted">${esc(t.lead)}</span>`:""}<div>${t.findings.map(id=>`<button class="linkbtn" data-goto="${id}">${id}</button>`).join(" ")}</div></div>`).join("")||`<p class="muted">No threads.</p>`}</div></div>
  <div class="panel"><h2>Areas requiring additional verification</h2>${verify.length?`<ul>${[...new Map(verify.map(f=>[f.verify_next+f.docs.join(), f])).values()].map(f=>`<li><b>${esc(f.docs.map(x=>docs[x]?.filename).join(", "))}</b>: ${esc(f.verify_next)} <span class="muted">(${f.id})</span></li>`).join("")}</ul>`:`<p class="muted">Nothing flagged for verification.</p>`}</div>
  <div class="panel"><h2>Investigation limitations</h2><ul>${D.limitations.map(l=>`<li>${esc(l)}</li>`).join("")}</ul></div></div>`;
  $("#main").onclick = e => { const g=e.target.closest("[data-goto]"); if(g){ state.filter="ALL"; state.finding=g.dataset.goto; go("investigate"); } };
}

/* ---------------- coverage ---------------- */
function coverage(){
  const C = D.coverage, s = C.summary, tot = s.STRONG+s.WEAK+s.BLIND || 1;
  $("#main").innerHTML = `<p class="section-note">Mutation testing of SAKSHI's own reasoning (${esc(C.baseline||"")}): each value is changed in memory and we check whether any rule notices and whether the repair solver points back at it. BLIND fields cannot be verified from these documents and need an outside check. For analysts only; never share with applicants.</p>
  <div class="stack"><div class="panel"><div class="bar"><span style="width:${s.STRONG/tot*100}%;background:var(--ok)"></span><span style="width:${s.WEAK/tot*100}%;background:var(--inc)"></span><span style="width:${s.BLIND/tot*100}%;background:var(--pm)"></span></div>
    <p><span class="cov STRONG">${s.STRONG} strong</span> (caught and localized, 2+ rules) · <span class="cov WEAK">${s.WEAK} weak</span> (caught, not pinned down) · <span class="cov BLIND">${s.BLIND} blind</span> (no rule watches it)</p></div>
  <div class="panel"><h2>Coordinated attack simulations</h2>${C.attacks.map(a=>`<div class="thread"><b>${a.caught?"Caught":"Missed"}: ${esc(a.attack)}</b><span class="muted">${esc(a.story)}</span>${a.caught_by.length?`<span>Caught by: ${a.caught_by.map(esc).join("; ")}</span>`:""}</div>`).join("")||`<p class="muted">Not applicable to these documents.</p>`}</div>
  <div class="panel"><h2>Field coverage</h2><div class="tbl"><table><thead><tr><th>Status</th><th>Field</th><th>Document</th><th>Value</th><th>Rules watching</th></tr></thead><tbody>${C.fields.sort((a,b)=>["BLIND","WEAK","STRONG"].indexOf(a.status)-["BLIND","WEAK","STRONG"].indexOf(b.status)).map(r=>`<tr><td><span class="cov ${r.status}">${r.status}</span></td><td class="mono">${esc(r.label)}</td><td>${esc(r.doc)}</td><td class="mono">${esc(r.value)}</td><td class="num">${r.anchors}</td></tr>`).join("")}</tbody></table></div></div></div>`;
}

/* ---------------- audit ---------------- */
function audit(){
  const R = D.audit.records||[];
  $("#main").innerHTML = `<p class="section-note">Append-only, hash-chained log in the spirit of ISO/IEC 27037 chain of custody. Each event stores the hash of the previous one; editing any event breaks the chain. Status: <b style="color:var(${D.audit.verified?'--ok':'--pm'})">${esc(D.audit.message)}</b>.</p>
  <div class="stack"><div class="panel"><h2>Processing timeline</h2><div class="timeline">${R.filter(r=>r.event==="stage").map(r=>`<div><span class="mono">${esc(r.ts.slice(11,19))}</span><span>${esc(r.payload.stage)}${r.payload.note?` · <span class="muted">${esc(r.payload.note)}</span>`:""}</span></div>`).join("")}</div></div>
  <div class="panel"><h2>Events (${R.length})</h2><div class="tbl"><table><thead><tr><th>Time</th><th>Event</th><th>Details</th><th>Hash</th></tr></thead><tbody>${R.map(r=>`<tr><td class="mono">${esc(r.ts.slice(11,19))}</td><td>${esc(r.event.replace(/_/g," "))}</td><td class="mono" style="max-width:520px;overflow-wrap:anywhere">${esc(JSON.stringify(r.payload).slice(0,240))}</td><td class="mono muted">${esc(r.hash.slice(0,12))}…</td></tr>`).join("")}</tbody></table></div></div></div>`;
}

header(); tabs();
go((location.hash||"#investigate").slice(1));
window.addEventListener("hashchange", () => go(location.hash.slice(1)));
</script>
"""
