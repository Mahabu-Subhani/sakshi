<div align="center">

# SAKSHI

**Evidence-first document forensics for loan and KYC files.**<br>
Offline · CPU only · deterministic · every finding traced to the exact spot on the page

![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-1B3FD1) ![Runs offline](https://img.shields.io/badge/runs-offline-051C2C) ![CPU only](https://img.shields.io/badge/GPU-not%20needed-051C2C) ![Licence MIT](https://img.shields.io/badge/licence-MIT-1B3FD1)

<img src="docs/assets/hero.gif" width="800" alt="SAKSHI console: the payslip says 86,500, and SAKSHI finds 68,500 still in the file under a filled shape">

<sub>Real console footage (recorded with v1.0.2). The payslip says 86,500; SAKSHI finds 68,500 still inside the file, and recovers it.</sub>

**[Watch the 4-minute demo (v1.0.4)](https://mahabu-subhani.github.io/sakshi/#demo)** · **[Sample dossier](https://mahabu-subhani.github.io/sakshi/samples/DEMO-TAMPERED_dossier.html)** · **[Quick start](#quick-start)** · **[Results](#results)**

</div>

*Sakshi* (साक्षी) is Hindi for *witness*. SAKSHI reads every document in a loan application, weighs how reliable each one is, and cross-examines them against each other. Instead of a fraud score it asks one question: **what would the documents have to say for every rule to hold?** The answer points at the edited field, often recovers its original value, and comes with the exact evidence an analyst can check in seconds. It never says "fraud"; a human decides.

Built for the DataOps Innovation Hackathon problem *AI-Powered Document Forensics and Contextual Intelligence System*.

<details>
<summary><b>How SAKSHI covers the problem statement</b></summary>

| The brief asks for | Where SAKSHI does it |
|---|---|
| Upload and process multiple documents of one application | console uploader and `python -m sakshi run`; each case in its own worker process; a capability matrix in the console states what is implemented, partial, planned and unsupported |
| Classification and OCR | dossier 7.1: type, confidence, cues, modality, witness level, SHA-256 |
| Structured representation of the content | dossier 7.2: every field with raw and normalised value, confidence, method and location |
| Visual forensics with suspicious regions highlighted | nine pixel sensors, PDF layer archaeology and overlay peel; every hit boxed on its page (7.4) |
| Contextual and cross-document verification | rules, counterfactual repair, claim graph and income triangulation (7.3) |
| Relationships between findings | findings grouped into hypotheses that support each other |
| Potential versus confirmed anomalies | three rungs, devil's advocate, witness levels; never "fraud" |
| Traceable evidence and a final dossier | 7.5 traceability (click to the boxed region), 7.6 summary, HTML / JSON / hash-chained audit |
| Safe failure and stated limits | damaged files rejected with a reason, forgery canaries, coverage map, `docs/LIMITATIONS.md` |

</details>

## What it finds

| Demo payslip · counterfactual repair | Red-team payslip RT8 · overlay peel |
|---|---|
| ![As submitted 86,500; expected value reconstruction 68,500](docs/assets/counterfactual.jpg) | ![What a reader sees 88,500; the scan inside the same file 68,500](docs/assets/overlay-peel.jpg) |
| The payslip's own arithmetic and the amount in words only add up if net pay were **68,500**. SAKSHI finds the smallest set of field changes that makes every rule hold, and PDF layer archaeology independently finds 68,500 painted over in the file. | A scanned payslip edited in a PDF editor: a box hides the real figure and new text is typed on top. The scan itself is untouched, so pixel forensics alone see nothing. SAKSHI peels the layers apart. |

It also recovers the earlier saved version of an edited PDF and shows what changed (on the demo payslip: 68,500.00 before the later save, 86,500.00 after), flags hidden text that tells automated reviewers to ignore anomalies, and catches a digit copied from elsewhere on a scanned statement, a white-out and retype on an application form, an EMI row deleted from a statement, an October payslip made from September's scan, a spliced ID photo, and the same ID photo or salary account reused by a "different" applicant across cases.

## See it

| The review console | The investigation dossier |
|---|---|
| ![Console with the demo case: REFER, 7 potential manipulation, 11 inconsistencies, 3 observations](docs/assets/console.png) | ![Dossier: value 68,500 hidden under a filled shape, recovered from the file, with the devil's advocate table](docs/assets/dossier-investigation.png) |
| **Cross-document claim graph** | **Coverage map** |
| ![Claim graph: documents linked to the facts they state, conflicts in red](docs/assets/claim-graph.png) | ![Coverage map: every field marked blind, weak or strong](docs/assets/coverage-map.png) |

Each case produces a self-contained `dossier.html` (every finding clickable to its box on the original page), a machine-readable `dossier.json`, and a hash-chained `audit.jsonl`. Open the samples in your browser on the [project page](https://mahabu-subhani.github.io/sakshi/#samples), or download one from [`samples/`](samples) and open it locally.

## How it decides

| Rung | Meaning |
|---|---|
| **OBSERVATION** | Something differs, and an innocent reason explains it (`MOHD ARIF KHAN` vs `Mohammed Arif Khan`). |
| **INCONSISTENCY** | A rule is broken, but an innocent reason is still possible (a date of birth one digit apart). |
| **POTENTIAL MANIPULATION** | Two independent evidence families agree, or there is a smoking gun, and no innocent explanation survives. |

Every finding states its **strength of evidence** in words (strong, moderate or weak support; or explained), the way forensic reports do, next to its confidence. Every finding first faces a **devil's advocate**: a catalogue of innocent explanations (rounding, OCR misread, transliteration, JBIG2 compression, salary revision, timing), each with a deterministic test. Evidence is weighed by **witness level**: an applicant's own form (L0) counts less than a scanned letter (L1), which counts less than a payslip, statement or ID (L2). A **coverage map** marks every field strong, weak or blind, so silence is never reported as "clean".

<img src="docs/assets/devils-advocate.png" width="620" alt="A name written as MOHD ARIF KHAN and Mohammed Arif Khan stays an OBSERVATION: transliteration explains it, so the strength is explained, no support">

## How it works

<img src="docs/assets/architecture.png" alt="Input, read each document, judge together, output">

Every number SAKSHI reports comes from deterministic code: rules, solvers and image statistics. OCR is Tesseract; nothing is decided by a language model. An optional narrator can call an LLM API to reword the final summary; it is off by default and never decides a rung.

<details>
<summary><b>The core techniques</b></summary>

| Technique | What it does | Code |
|---|---|---|
| Counterfactual repair | Treats the documents as a program with invariants (gross = sum of earnings, net = gross - deductions, running balances, payslip net = salary credit, declared EMI = EMI debits) and finds the smallest, most plausible set of field changes (up to 3, weighted by witness level and OCR confidence) that makes every rule hold. | `reasoning/repair.py` |
| PDF layer archaeology | Finds values covered by a filled shape in born-digital PDFs and recovers the hidden original from the content stream. | `forensics/pdf_layers.py` |
| Overlay peel | Renders what a reader sees, extracts the bare scan from the same file and compares them; covers objects, comment annotations and nested XObjects, and recognises redactions. | `forensics/scan_overlay.py` |
| Nine pixel sensors | Paper noise, copy-move (scanner grain), scanner optics, glyph typography, intra-number strokes, erasure patches, JPEG ghosts, scan clones, blue-ink signatures. | `forensics/` |
| Constraint-guided statement parser | Picks the column layout (debit/credit, credit/debit, amount + Dr/Cr, signed amount) that makes the running balance hold; doubtful cells get a second OCR pass that never sees the expected value. | `forensics/table_parser.py` |
| Income triangulation | Weighs every independent witness to monthly income; a self-contradicting document is impeached, but the part that exposes the contradiction keeps its weight. Without a clear majority, nobody is blamed. | `reasoning/engine.py` |
| Payroll physics, deleted rows | Employee PF must be at least 12% of the basic printed; a balance break whose gap equals a missing recurring EMI, with no printed line between the rows, is a removed row. | `reasoning/invariants.py`, `reasoning/engine.py` |
| Forgery canaries | Before trusting a sensor's silence, SAKSHI forges each upload in memory from its own pixels; a sensor that misses its own canary reports "blind on this document". | `reasoning/selftest.py` |
| Earlier-version recovery | An incremental save appends changes after the original end-of-file marker; cutting the file there recovers the document as it was, and values that changed at the same place are reported with their earlier reading. | `forensics/pdf_layers.py` |
| Hidden instructions, grounded narrator | Invisible text addressed to automated reviewers is a finding. The optional LLM narrator gets document text only as quoted data; its output is discarded unless every sentence cites a real finding id and every potential-manipulation finding is covered. | `forensics/pdf_layers.py`, `reasoning/narrator.py` |
| Cross-case memory | Fingerprints of earlier cases (photo hash, PAN, account numbers, file hashes, signature grids) expose identity rings. | `registry.py` |
| Hash-chained audit | Every stage and finding is logged with the hash of the previous entry; `verify-audit` detects any later edit. | `audit.py` |

The ten stages follow the brief: document submission, classification, OCR and extraction, structural understanding, visual forensic analysis, contextual verification, cross-document correlation, anomaly investigation, evidence generation, investigation dossier. Methods and thresholds are in [`docs/TECHNICAL.md`](docs/TECHNICAL.md); the data flow is in [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md).

</details>

## Results

<img src="docs/assets/results.png" width="760" alt="Red team: 9 of 9 attacks caught, 6 at the top rung. Forgery Lab: 12 of 12, 10 at the top rung; planned miss: 0 of 2 detected. Genuine: demo control clean, 7 of 7 look-alikes clean, 1 of 2 re-scans clean">

Extraction is measured against the generator's ground truth: **48 of 48 fields** and **13 of 13 statement rows** exact on the clean demo documents, **18 of 19 fields** on WhatsApp-forwarded phone photos (one PAN not read), with no wrong value extracted. On the demo application, all **9 planted manipulations** are found (14 of 14 expected detections) and the original net pay of **68,500** is recovered; the same applicant's genuine documents come back with **0 potential manipulation and 0 inconsistencies**. The synthetic suites were built for this project, and the red team is a regression suite for known attacks, not a blind test. So SAKSHI was also run, unchanged, on public data it was never tuned for:

<img src="docs/assets/receipts.png" width="760" alt="Public receipts: the middle rung flags forged and genuine receipts at about the same rate; 0 of 342 genuine receipts reach the top rung">

On real receipts the middle rung cannot separate forged from genuine, and that is stated plainly. The rung an analyst acts on held: **none of 342 genuine receipts** was escalated to potential manipulation. A five-document case takes **25-80 s** on a laptop CPU. Full tables, commands and caveats: [`docs/RESULTS.md`](docs/RESULTS.md).

## Quick start

Python 3.10+ and the Tesseract OCR 5 binary (English; Hindi optional).

```bash
# Ubuntu: sudo apt install tesseract-ocr tesseract-ocr-hin
# Windows: UB Mannheim installer, then add it to PATH.  macOS: brew install tesseract tesseract-lang
pip install -r requirements.txt

streamlit run app.py              # review console: upload documents or pick a demo case
python -m sakshi demo             # investigate both demo cases (--regenerate rebuilds them on this machine first)
python -m sakshi run a.pdf b.jpg --out out/mycase [--lang eng+hin] [--memory registry.json] [--password PW]
python -m sakshi verify-audit out/mycase/audit.jsonl
```

**Or with Docker** (Tesseract with English and Hindi included, no local install):

```bash
docker build -t sakshi .
docker run --rm -p 8501:8501 sakshi          # review console at http://localhost:8501
docker run --rm -v "$PWD/in:/data" sakshi python -m sakshi run /data/a.pdf /data/b.jpg --out /data/out
```

The image uses Tesseract 5.5, which reads one character of the IFSC differently on the scanned statement and application form (`DCBLO0001234` for `DCBL0001234`, at OCR confidence 0.30). In Docker the demo case therefore shows 7 / 11 / 5 instead of 7 / 11 / 3, the genuine control 0 / 0 / 3 instead of 0 / 0 / 1, and extraction 46 / 48 instead of 48 / 48. The extra findings are observations explained as an OCR confusion; every other result is the same.

The image ships Tesseract 5.5, which reads a few characters differently from the Tesseract 5.4 used for the numbers above: on the demo cases the potential-manipulation and inconsistency counts are identical, with up to two more explained observations (for example an IFSC read as `DCBLO0001234` is reported as a format observation, not an inconsistency). `tests/run_eval.py` passes inside the container.

<details>
<summary><b>Run the test suites</b></summary>

```bash
python tests/run_eval.py                  # every planted manipulation found, genuine control clean
python tests/run_redteam.py               # red-team cases and genuine look-alikes
python tests/forgery_lab.py --seeds 2     # forgery recipes on fresh documents + genuine re-scans
python tests/run_long_statement.py        # 13-page statement edited on page 8, and a locked copy
python tests/run_registry_chain.py        # every case back to back into one cross-case memory
python tests/run_registry_lock.py         # eight cases written to the memory at the same moment
python tests/run_console_worker.py        # the console's isolated worker
python tests/run_extraction_accuracy.py   # field-level extraction accuracy against ground truth
python tests/run_signatures.py            # black-ink signatures: detection, identity, no false signatures
python tests/run_prompt_injection.py      # hidden instructions caught; the narrator cannot be steered
python tests/run_findit.py --data PATH/TO/findit2   # public receipts (download the dataset first)
```

</details>

## Limitations

* Thresholds were calibrated on synthetic data; SAKSHI has not been tested on real Indian payslips or statements.
* On low-resolution images such as thermal receipts, the middle rung does not separate forged from genuine.
* A statement row changed with every later balance regenerated leaves no trace; that field is reported blind.
* Pixel forensics run on the first 6 pages (up to 40 are read); no handwriting analysis; black-ink signatures are found only just above a readable signature caption.
* Issuer verification (bank, UIDAI) is modelled as witness levels L3-L4, not connected; cross-case memory has no per-applicant erasure yet.

More in [`docs/LIMITATIONS.md`](docs/LIMITATIONS.md). Next: a resolution gate for the pixel sensors judged once on the 577 unread receipts, calibration on consented real documents, and Account Aggregator and UIDAI as witnesses that outrank any upload.

## Built with

Python · PyMuPDF · Tesseract 5 · OpenCV · scikit-image · NumPy · Pillow · Streamlit · ReportLab (synthetic test data). Everything runs on one laptop and documents never leave it (if the optional narrator is switched on, it sends only the structured findings to an LLM API, never the documents).

Use only authorised or synthetic documents. Every document in this repository is synthetic and labelled SYNTHETIC SPECIMEN, except the public receipts, which are not bundled.

Built by **Mahabu Subhani Mohammed**.

**Licence:** MIT ([`LICENSE`](LICENSE)). PyMuPDF is AGPL-3.0, which matters for any hosted or commercial deployment. [Changelog](docs/CHANGELOG.md).
