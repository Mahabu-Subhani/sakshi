# SAKSHI

**Evidence-first document forensics and contextual intelligence for loan and KYC files.**

*Sakshi* (साक्षी) is Hindi for *witness*. SAKSHI treats every document in an application as a witness: it reads each one, weighs how reliable it is, cross-examines it against the others, and reports what the evidence shows. It never says "fraud". It gives an analyst findings they can check in seconds, each tied to the exact pixels or PDF objects behind it, and leaves the decision to a human.

Built for the DataOps Innovation Hackathon problem *AI-Powered Document Forensics and Contextual Intelligence System*. Runs offline on a laptop CPU by default: no GPU, no cloud service, no training data. (An optional narrator can call an LLM API to reword the summary; it is off by default.)

**Demo video (2:50):** [`docs/demo/SAKSHI_demo.mp4`](docs/demo/SAKSHI_demo.mp4). It was recorded by driving the real console: file uploads, three cases, the dossier. Waits are sped up 10x and labelled; explanatory animations are labelled as such. Subtitles: [`SAKSHI_demo.srt`](docs/demo/SAKSHI_demo.srt). Timed narration: [`voiceover_script.txt`](docs/demo/voiceover_script.txt).

---

## The problem

The forgery that matters in lending is rarely a fake document. It is one changed number in a real one: a net pay raised from 68,500 to 86,500, an EMI hidden from a bank statement, a retyped date of birth. Error-level heatmaps and opaque "fraud scores" often fire on benign noise and give an analyst nothing concrete to verify. SAKSHI asks a different question: *what would the documents have to say for every rule to hold?* The answer localises the edited field and often recovers its original value.

## How it works

### Ten stages

`Document submission -> Document classification -> OCR & information extraction -> Structural understanding -> Visual forensic analysis -> Contextual verification -> Cross-document correlation -> Anomaly investigation -> Evidence generation -> Investigation dossier`

Each document is first read on its own (type, text, fields, tables, pixels, PDF structure), then all documents are judged together (cross-document rules, repair, triangulation). [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) has the diagram and data flow, and [`docs/TECHNICAL.md`](docs/TECHNICAL.md) has every method and threshold.

### Witness weight

| Level | Source | Example |
|---|---|---|
| L0 | Self-declared by the applicant | application form |
| L1 | Scanned, unverifiable issuer document | employment letter |
| L2 | Standard issuer document | payslip, bank statement, ID card |
| L3 | Digitally signed by a trusted issuer | modelled, not verified in this prototype |
| L4 | Fetched from the source (e.g. Account Aggregator) | modelled, out of scope |

A mismatch on an L0 claim is reported as a false declaration, never as a forged document.

### Three rungs, never a verdict

| Rung | Meaning | Example |
|---|---|---|
| OBSERVATION | Something differs, and an innocent reason explains it. | `MOHD ARIF KHAN` vs `Mohammed Arif Khan` |
| INCONSISTENCY | A rule is broken, but an innocent reason is still possible. | a date of birth that differs between two documents |
| POTENTIAL MANIPULATION | Two independent evidence families agree, or there is a smoking gun, and no innocent explanation survives. | demo payslip: 68,500 still in the file under a white box, 86,500 typed on top |

Every finding faces a **devil's advocate** first: a catalogue of innocent explanations (rounding, OCR misread, transliteration, JBIG2 compression, salary revision, timing and more), each paired with a deterministic test. A finding cannot escalate while an innocent explanation is still plausible.

### Core techniques

| Technique | What it does | Code |
|---|---|---|
| Counterfactual repair | Treats the documents as a program with invariants (gross = sum of earnings, net = gross - deductions, running balance chain, payslip net = salary credit, declared EMI = EMI debits). When rules break, it finds the smallest, most plausible set of field changes (up to 3, weighted by witness level and OCR confidence) that makes every rule hold. That localises the edited field and reconstructs its original value. | `reasoning/repair.py` |
| PDF layer archaeology | Finds values covered by a white box in born-digital PDFs and recovers the hidden original from the content stream. | `forensics/pdf_layers.py` |
| Overlay peel | For a scanned PDF edited in a PDF editor (red-team case RT8), renders what a reader sees, extracts the bare scan from the same file and compares the two: *88,500.00 on top, 68,500.00 on the paper underneath*. Covers objects, comment annotations and nested XObjects, and recognises redactions. | `forensics/scan_overlay.py` |
| Nine pixel sensors | Paper noise, copy-move (scanner grain), scanner optics, glyph typography, intra-number strokes, erasure patches, JPEG ghosts, scan clones and blue-ink signatures. Each reads a physical trace an edit leaves behind. | `forensics/` |
| Constraint-guided statement parser | Picks the column layout (debit/credit, credit/debit, amount + Dr/Cr, signed amount) that makes the running balance hold. Doubtful cells get a second OCR pass that never sees the expected value. | `forensics/table_parser.py` |
| Income triangulation | Lists every independent witness to monthly income. A self-contradicting document is impeached, but the part that exposes the contradiction keeps full weight. Without a clear majority SAKSHI blames no one. | `reasoning/engine.py` |
| Payroll physics and deleted rows | Employee PF must be at least 12% of the basic printed on the slip (PF 4,800 points to a basic of 40,000, not the 60,000 printed). A balance break whose gap equals a missing recurring EMI, with no printed line between the rows, is a removed row, not a parse error. | `reasoning/invariants.py`, `reasoning/engine.py` |
| Forgery canaries | Before trusting a sensor's silence, SAKSHI forges each upload in memory from its own pixels. A sensor that misses its own canary reports "blind on this document", not "clean". | `reasoning/selftest.py` |
| Coverage map | Changes each field in memory and asks whether any rule would notice. Every field is marked strong, weak or blind; coordinated attacks are simulated too. | `reasoning/coverage.py` |
| Cross-case memory | Remembers fingerprints of earlier cases on the machine (photo hash, PAN, account numbers, file hashes, signature grids). A new applicant using an earlier applicant's ID photo or salary account is an identity ring. | `registry.py` |
| Hash-chained audit trail | Every stage and finding is logged with the hash of the previous entry; `verify-audit` detects any later edit. | `audit.py` |

On the demo case, the repair solver (pure arithmetic over extracted numbers) and PDF layer archaeology (pure file structure) arrive independently at the same original net pay, 68,500.00.

---

## Results

All numbers below were measured on a Windows 11 laptop on 6-7 November 2026 and can be rerun with the commands in [Tests](#tests). Detection code and thresholds were the same for every run reported here, and nothing was tuned on the public receipts.

| Suite | Data | Result |
|---|---|---|
| Regression, `tests/run_eval.py` | synthetic demo case: 9 planted manipulations + 1 benign decoy | all 9 found, through 14 of 14 expected detections; original net pay 68,500.00 recovered; the MOHD/Mohammed decoy stays an observation; genuine control: 0 potential manipulation, 0 inconsistencies, 1 explained observation |
| Red team, `tests/run_redteam.py` | 16 cases: 9 attacks, 7 genuine look-alikes | 9 of 9 manipulated cases detected (6 at POTENTIAL MANIPULATION); 7 of 7 genuine cases clean |
| Forgery Lab, `tests/forgery_lab.py` | 6 forgery recipes x 2 seeds + a planned miss, on fresh documents | 12 of 12 detected (10 at POTENTIAL MANIPULATION); planned miss 0 of 2; genuine re-scans clean 1 of 2 |
| Long and locked statements, `tests/run_long_statement.py` | 13-page statement edited on page 8; password-locked copy | all pass: the page-8 edit is caught; passwords are never written to the dossier or audit trail and are forgotten even after a crash |
| Cross-case memory, `tests/run_registry_chain.py` | every case back to back into one memory | all pass (20 runs): only the identity ring is flagged |
| Console isolation, `tests/run_console_worker.py` | demo case through the console's worker process | all pass |

How to read these honestly:

* The red-team cases were written as attack briefs without looking at SAKSHI's thresholds, but the detectors were then improved against them (the first version caught 3 of the first 5). Treat 9 of 9 as a regression test for known attacks, not a blind test.
* The one genuine re-scan that Forgery Lab flags: on one seed, OCR did not read the "Valid till" label of the re-rendered ID card, which raises a missing-field inconsistency. (On Linux with Liberation fonts the same suite kept 2 of 2 genuine re-scans clean and detected 12 of 12, 9 at the top rung.)
* The planned miss is a statement row changed with every later balance regenerated. Nothing in the documents contradicts it, so SAKSHI marks that field blind instead of guessing.

### Public data: Find it again! receipts

To test outside synthetic data, SAKSHI ran unchanged on [Find it again!](https://l3i-share.univ-lr.fr/2023Finditagain/index.html) (ICDAR 2023, L3i La Rochelle): real scanned receipts, some forged with image editors, with forged regions annotated. Each receipt is investigated alone (`tests/run_findit.py`; the dataset is not bundled).

| Split | Receipts (forged / genuine) | Forged flagged | Evidence on the forged region | Genuine flagged | Genuine at POTENTIAL MANIPULATION |
|---|---|---|---|---|---|
| test | 218 (35 / 183) | 18 (51%) | 6 | 102 (56%) | 0 |
| val | 193 (34 / 159) | 19 (56%) | 12 | 85 (53%) | 0 |

This result is poor and is reported as such: at the INCONSISTENCY rung SAKSHI flags forged and genuine receipts at about the same rate. A receipt is a single low-resolution image, so the arithmetic, cross-document and PDF checks that carry loan files cannot run; this tests the pixel sensors alone, mostly the glyph, stroke and noise sensors on thermal prints. No genuine receipt reached POTENTIAL MANIPULATION. The 577-receipt train split is held out, unread, for one future evaluation of a resolution gate.

### Runtime

A five-document case takes 25-80 s on the test laptop, depending on load (console when idle 25-28 s; clean command-line medians 41 s for the tampered case and 35 s for the genuine one; up to 76 s under load). Version 1.0.1 made copy-move scoring 3.9x faster on 44,390 real glyph pairs with identical scores; back to back, the demo case went from about 69 s to about 55 s.

---

## Quick start

Requirements: Python 3.10+ and the Tesseract OCR 5 binary (English; Hindi optional).

```bash
# Tesseract: Ubuntu
sudo apt install tesseract-ocr tesseract-ocr-hin
# Windows: UB Mannheim installer, then add it to PATH.  macOS: brew install tesseract tesseract-lang

pip install -r requirements.txt
```

Review console (upload documents or pick a demo case, watch the stages, read the dossier):

```bash
streamlit run app.py
```

Command line:

```bash
python -m sakshi demo                     # build the demo dataset and investigate both demo cases
python -m sakshi run a.pdf b.jpg --out out/mycase --case-id HL-123 [--lang eng+hin] [--memory registry.json] [--password PW]
python -m sakshi verify-audit out/mycase/audit.jsonl
```

In the console each case runs in its own worker process with a hard timeout (`SAKSHI_CASE_TIMEOUT`, default 600 s). A stalled case is stopped with a clear message, nothing is left running, and a second click during a run is refused.

## Tests

```bash
python tests/run_eval.py                  # every planted manipulation found, genuine control clean
python -m sakshi redteam                  # build the red-team cases and score them (or: python tests/run_redteam.py)
python tests/forgery_lab.py --seeds 2     # forgery recipes on fresh documents + genuine re-scans
python tests/run_long_statement.py        # 13-page statement edited on page 8, and a password-locked copy
python tests/run_registry_chain.py        # every case back to back into one cross-case memory
python tests/run_console_worker.py        # the console's isolated worker: results, timeout, no leftovers
python tests/run_findit.py --data PATH/TO/findit2   # public receipts (download the dataset first)
```

## Outputs (per case)

| File | Contents |
|---|---|
| `dossier.html` | Self-contained interactive dossier: document overview, extracted information, contextual analysis, visual forensics, evidence and traceability, investigation summary, coverage map and audit trail. Click any finding to see its evidence boxes on the original page. |
| `dossier.json` | Machine-readable version of the dossier (paths are relative, so a shared dossier leaks no local paths). |
| `audit.jsonl` | Hash-chained audit trail; `python -m sakshi verify-audit` detects any edit. |
| `evidence/` | Evidence crops, noise heatmaps, signature crops, before/after reconstructions. |
| `pages/` | Page rasters the analysis ran on, at native resolution. |

Sample dossiers are in [`samples/`](samples): the tampered and genuine demo cases, and red-team case RT8 showing the overlay peel.

## Repository layout

```
app.py                     Streamlit review console
sakshi/
  pipeline.py              the ten stages, run_case()
  ingest.py, classify.py   reading PDFs and images, document type, OCR
  extract.py               fields, tables, statement rows
  console_worker.py        isolated worker process for the console
  registry.py, audit.py    cross-case memory, hash-chained audit trail
  forensics/               pixel sensors, PDF layers, overlay peel, statement parser
  reasoning/               invariants, repair solver, devil's advocate, fusion, coverage, canaries, optional narrator
  dossier/render.py        HTML dossier
dataset/                   demo-case generator, red-team generator and cases, ground-truth manifests
tests/                     the suites listed above
samples/                   example dossiers and audit trails
docs/                      architecture, technical detail, limitations, Forgery Lab results, demo script, demo video
```

## Tech stack

| Layer | Tools | Licence |
|---|---|---|
| Language | Python | |
| PDF internals | PyMuPDF | AGPL-3.0 (or commercial licence from Artifex) |
| OCR | Tesseract 5 (LSTM) via pytesseract | Apache-2.0 |
| Image forensics | OpenCV, scikit-image, NumPy, Pillow | Apache-2.0, BSD-3, BSD, HPND |
| Interface | Streamlit, command line, HTML dossier | Apache-2.0 |
| Integrity | SHA-256 hash chain | |
| Test data | ReportLab | BSD |
| Optional narrator | Gemini or Claude API, off by default; rewrites the summary in plain language and never decides a rung | provider terms |

## Demo data

Every document is synthetic, carries a visible SYNTHETIC SPECIMEN label and uses invented institutions.

* `dataset/cases/case_tampered`: five documents for one fictional applicant with 9 planted manipulations, listed in `MANIFEST_ground_truth.json`: a white-box overlay with a retyped net pay in a different font; a copy-moved digit in a scanned statement hiding an EMI; a digital white-out and retyped EMI on the application; a false income declaration; a date-of-birth mismatch; a spliced ID photo; an employment letter with a reproduced signature, an inflated tenure and an inflated salary. Plus one benign decoy (MOHD vs Mohammed) that must not escalate.
* `dataset/cases/case_genuine`: the same applicant's five consistent documents, the control.
* `dataset/redteam/`: 16 more cases (9 manipulated, 7 genuine look-alikes), each with its brief in `MANIFEST_ground_truth.json`, built by `dataset/redteam.py`. The genuine look-alikes are the hard part: a Dr/Cr statement with `05-Oct-2026` dates, two separately scanned payslips from one payroll system, a two-page statement with C/F and B/F rows, searchable scans with an e-sign stamp, WhatsApp-forwarded phone photos, a self-redacted PAN and a re-submitted case.

## Limitations

The full list is in [`docs/LIMITATIONS.md`](docs/LIMITATIONS.md). The main ones:

* Thresholds were calibrated on synthetic data; SAKSHI has not been tested on real Indian payslips or statements.
* On low-resolution images such as thermal receipts, the middle rung does not separate forged from genuine.
* A statement row changed with every later balance regenerated leaves no trace; that field is reported blind.
* Pixel forensics run on the first 6 pages; up to 40 pages are read for arithmetic, cross-document, structure, layout and overlay checks.
* No handwriting analysis; signature checks work on blue ink only.
* Issuer verification (bank, UIDAI) is modelled as witness levels L3-L4, not connected.
* Cross-case memory is a local file without per-applicant erasure yet.
* The console froze once during a long recording session (stuck after Document submission on the 7th run; the command line ran the same case fine). The cause was not found in about 25 replays with a stack-dump watchdog; the isolated worker contains it rather than fixing a root cause.

## Roadmap

* A resolution gate for the pixel sensors, judged once on the unread 577-receipt train split.
* Calibration on consented real Indian statements and payslips; portrait-based photo hashing.
* Per-applicant erasure for India's DPDP Act.
* Account Aggregator and UIDAI connected as L3-L4 witnesses that outrank any upload.
* Configurable pixel-forensics page limit and parallel processing for volume.

## Changes

* **1.0.2**: isolated console worker with a hard timeout and its test; demo video; runtime stated as the measured 25-80 s range.
* **1.0.1**: statements up to 40 pages and password-locked PDFs (passwords kept in memory only); copy-move scoring 3.9x faster with identical scores; cross-platform fonts for the generators.
* **1.0**: overlay peel, income triangulation with impeachment, payroll physics, deleted-row detection, scan clones, intra-number strokes, scanner optics, constraint-guided statement parser, erasure patches and JPEG ghosts, cross-case memory, safe failure ("blind", never a guess).

## Safety and ethics

Use only authorised or synthetic documents. SAKSHI never labels anything as fraud and never auto-rejects. It treats OCR as a fallible witness, keeps a tamper-evident audit trail, never stores passwords, and states what it could not check.

## Licence

SAKSHI's code is MIT licensed (see [`LICENSE`](LICENSE)). Dependencies keep their own licences; note that **PyMuPDF is AGPL-3.0**, which matters for any hosted or commercial deployment. Fonts used by the dataset generator are Liberation / FreeFont (SIL OFL / GPL with font exception) on Linux, or the system's Arial on Windows and macOS.
