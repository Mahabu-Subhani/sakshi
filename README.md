# SAKSHI

**Evidence-first document forensics and contextual intelligence for loan and KYC files.**
*Sakshi* (साक्षी) means *witness*. Every line of evidence is treated as a witness, weighed by how reliable it is, and cross-examined before it is allowed to say anything.

Built for the DataOps Innovation Hackathon problem *AI-Powered Document Forensics and Contextual Intelligence System*. v0.9 was designed in a four-round debate between Claude (Anthropic) and Gemini 2.5 Pro; **v1.0** was built with **Gemini 4 Argon** in four more rounds: Argon designed a blind red team, wrote two modules, and reviewed everything Claude wrote. See [`docs/COLLABORATION_LOG.md`](docs/COLLABORATION_LOG.md).

## Scoreboard (v1.0, all on synthetic data, reproducible with the commands below)

| Test | v0.9 | v1.0 |
|---|---|---|
| Regression (`tests/run_eval.py`): 14 planted manipulations, decoy, original value recovered, genuine case clean | all pass | all pass (genuine case: 0 inconsistencies; 1 to 3 explained observations, depending on the Tesseract build, see `docs/TECHNICAL.md` section 10) |
| Red team (`tests/run_redteam.py`: Argon's blind briefs RT1-RT6, then later cases from both sides): manipulated cases detected | 3 of 5 (1 at potential manipulation) | **9 of 9** (6 at potential manipulation); on Argon's original five, 5 of 5 (3 at potential manipulation) |
| Red team: genuine traps with **no** inconsistency or potential manipulation | 0 of 2 | **7 of 7** |
| Forgery Lab (`tests/forgery_lab.py`, 2 seeds): forgeries detected | | 12 of 12 (9 at potential manipulation); the regenerated-statement recipe is a planned miss (0 of 2) |
| Forgery Lab: genuine re-scans clean | | 2 of 2 |
| Cross-case memory chain (`tests/run_registry_chain.py`): every case back to back, only the identity ring flagged | | all pass (20 runs, including the genuine applicant returning after the ring was remembered) |

Forgery Lab figures above were measured on Linux with Liberation fonts. On Windows (v1.0.1, Arial in their place) it detects 12 of 12 forgeries (10 at potential manipulation), still misses the planned recipe (0 of 2), and keeps 1 of 2 genuine re-scans clean: on one seed, OCR did not read the "Valid till" label of the re-rendered ID card, which raises a missing-field inconsistency.

The genuine traps are the hard part: a Dr/Cr statement with `05-Oct-2026` dates, two separately scanned payslips from one payroll system, a two-page statement with C/F and B/F rows, searchable scans with an e-sign stamp, WhatsApp-forwarded phone photos, a self-redacted PAN and a re-submitted case. The one recipe SAKSHI misses (a statement row changed with every balance regenerated, no pixel trace) is a deliberate miss: nothing in the documents contradicts it, so SAKSHI lists that field as blind instead of guessing.

## Real-data stress test (public dataset, not made by us)

Every number above comes from documents we generated. To test outside that echo chamber we ran SAKSHI, with detection code and thresholds unchanged, on [Find it again!](https://l3i-share.univ-lr.fr/2023Finditagain/index.html) (ICDAR 2023, L3i La Rochelle): real scanned receipts, some forged by people with image editors, with the forged regions annotated. Each receipt is investigated alone (`tests/run_findit.py`; the dataset is not bundled).

| Split | Receipts (forged / genuine) | Forged flagged | Evidence on the forged region | Genuine falsely flagged | Genuine at potential manipulation |
|---|---|---|---|---|---|
| test | 218 (35 / 183) | 18 (51%) | 6 | 102 (56%) | 0 |
| val | 193 (34 / 159) | 19 (56%) | 12 | 85 (53%) | 0 |

The result is poor and we report it as such: at the INCONSISTENCY tier, SAKSHI flags forged and genuine receipts at the same rate. Receipts are single images, so the arithmetic, cross-document and PDF checks that carry our target cases cannot run; this tests the pixel sensors alone, outside the documents they were built for. Most false alarms come from the glyph, intra-number stroke and noise sensors on low-resolution thermal prints (the glyph sensor has no resolution gate yet). No genuine receipt was escalated to POTENTIAL MANIPULATION.

## New in v1.0.1

| Change | What it does | Where |
|---|---|---|
| **Long and locked statements** | Every page up to 40 is read, so arithmetic, cross-document and PDF-structure checks see a 15-40 page statement; pixel forensics stay on the first 6 pages. Locked PDFs open with a password supplied by the analyst (`--password`, or the field in the console), which is kept in memory only and never written to the dossier or audit trail. An edited amount on page 8 of a 13-page statement was missed by the old 6-page limit and is now caught (`tests/run_long_statement.py`). | `ingest.py`, `pipeline.py` |
| **Faster copy-move** | The nine alignment shifts of each glyph pair are scored in one array pass: 3.9x faster on 44,390 real pairs, with every score identical to the previous code. | `forensics/copy_move.py` |
| **Cross-platform fonts** | The dataset generator and the evidence labels find Liberation fonts on Linux and Arial (metric-compatible) on Windows and macOS, so `dataset/generate.py` and `tests/forgery_lab.py` run outside Linux. | `dataset/generate.py`, `fonts.py` |

## New in v1.0

| Idea | What it does | Where |
|---|---|---|
| **Overlay peel** | The commonest real edit is a white box and a new number typed over a scanned PDF in a PDF editor. The scan inside the file is untouched. SAKSHI renders what a reader sees, extracts the bare scan from the same file, and shows both side by side: *88,500.00 on top, 68,500.00 on the paper underneath*. Objects, comment annotations and nested XObjects are all caught by a pixel comparison. Redactions are recognised and never called a replaced value. | `forensics/scan_overlay.py` |
| **Income triangulation with impeachment** | Lists every independent witness to monthly income. A document that contradicts itself is impeached, but the part that exposes the contradiction (PF actually deducted, the scan under an overlay) is a *confession* and keeps full weight. One document cannot outvote others by repeating itself. With no clear majority SAKSHI refuses to blame anyone, so a coordinated forgery cannot trick it into accusing the honest employer letter. | `reasoning/engine.py` |
| **Statutory payroll physics** | Payroll software computes PF from the basic it prints. PF 4,800 on a slip that says basic 60,000 means the basic was 40,000. | `reasoning/invariants.py` |
| **Deleted-row detection** | A running-balance break whose gap equals an EMI that is missing that month, with no printed line between the rows, is a removed row, not a parsing error. | `reasoning/engine.py` |
| **Scan-clone detection** | Two real scans never share paper grain. Align page B onto page A; if their grain correlates, one was made by editing the other, and the pixels where they differ are the edits. | `forensics/raster.py` |
| **Intra-number stroke consistency** | Digits of one printed number share one font and one pass of ink. Two thinner digits inside a date of birth were retyped. | `forensics/raster.py` |
| **Scanner optics** | Text typed onto an image after scanning never went through the scanner's lens, so its edges are sharper than every other word. Independent of paper-noise sensors. | `forensics/raster.py` |
| **Constraint-guided statement parser** (Argon) | Picks the column layout (Dr/Cr, signed, debit/credit...) that makes the running balance hold; re-reads doubtful cells with a blind second OCR, never rewrites them. | `forensics/table_parser.py` |
| **Erasure patches and JPEG ghosts** (Argon) | Painted-over paper has no scanner grain; pasted regions carry a different compression history. | `forensics/compression.py` |
| **Cross-case memory** | Remembers fingerprints (photo hash, PAN, account, file hashes, signature grids) of earlier cases on the machine. A new applicant using someone else's ID photo or salary account is an identity ring. | `registry.py` |
| **Safe failure everywhere** | Sensors report *blind* instead of guessing on small images, bimodal pages and unfamiliar statement layouts; unreadable fields are "could not be read", never "missing". | all |

---

## Core design (from v0.9)

Most systems do OCR, a few regex checks, an error-level-analysis heatmap and an LLM summary. SAKSHI reasons like an investigator:

| Idea | What it does | Where |
|---|---|---|
| **Counterfactual repair** | Treats every document as a program with invariants (gross = sum of earnings, net = gross - deductions, running balance chain, payslip net = bank salary credit, declared EMI = EMI debits...). When rules break, it searches for the *smallest, most plausible set of field changes that makes every rule hold again*, which both **localizes the forged field** and **reconstructs its original value**. | `reasoning/repair.py` |
| **PDF layer archaeology** | Finds values painted over with a white box in born-digital PDFs and **recovers the hidden original** from the content stream. | `forensics/pdf_layers.py` |
| **Independent convergence** | On the demo case the repair solver (pure logic over extracted numbers) and the PDF archaeology (pure file structure) independently arrive at the same original net pay, 68,500.00. | dossier, thread 1 |
| **Witness levels L0-L4** | A self-declared application counts less than a bank statement. A mismatch on a claim is reported as a false declaration, never as a forged document. | `models.py`, `repair.py` |
| **Devil's advocate** | Every finding faces innocent explanations (rounding, OCR misread, transliteration, JBIG2 compression, salary revision, timing...), each with a deterministic test. A finding cannot escalate while an innocent explanation is still plausible. | `reasoning/devils_advocate.py`, `benign_catalog.json` |
| **Verification coverage map** | Mutation-tests SAKSHI's own reasoning: which fields are strongly verified, weakly verified, or **blind** (no rule can check them). Plus coordinated-attack simulations (internally consistent payslip inflation, regenerated balance column). | `reasoning/coverage.py` |
| **Forgery canaries** | Before trusting a pixel sensor's silence, SAKSHI forges each uploaded document itself in memory, using its own pixels, and checks the sensor catches it. Otherwise it reports "blind on this document". | `reasoning/selftest.py` |
| **Scanner-grain copy-move** | Two scanned glyphs never share sensor noise. Identical paper grain around two digits means one was copied after scanning. | `forensics/copy_move.py` |
| **Epistemic ladder** | OBSERVATION -> INCONSISTENCY -> POTENTIAL MANIPULATION. Never "fraud". Decisions stay with the analyst. | `reasoning/fusion.py` |

## Quick start

```bash
# system dependency: Tesseract OCR 5 (with eng; hin optional)
sudo apt install tesseract-ocr tesseract-ocr-hin   # Windows: UB Mannheim installer, add to PATH; macOS: brew install tesseract tesseract-lang
pip install -r requirements.txt

python -m sakshi demo                 # builds the demo dataset, investigates both cases, writes out/*/dossier.html
python tests/run_eval.py              # checks every planted manipulation is found and the genuine case stays clean
python -m sakshi redteam              # builds the blind red-team cases and scores SAKSHI on them
python tests/forgery_lab.py --seeds 2 # forgery recipes on fresh genuine documents + genuine re-scans
python tests/run_registry_chain.py    # every case back to back into one cross-case memory
python tests/run_long_statement.py    # 13-page statement edited on page 8, and a password-locked copy
python tests/run_findit.py --data PATH/TO/findit2   # real-data stress test (download the dataset first)
streamlit run app.py                  # upload console with live progress and the interactive dossier
python -m sakshi run a.pdf b.jpg --out out/mycase --case-id HL-123 [--lang eng+hin] [--memory registry.json] [--password PW]
python -m sakshi verify-audit out/mycase/audit.jsonl
```

Measured on a Windows 11 laptop (CPU only, no GPU, no internet, another evaluation running in parallel): the 5-document demo case takes about 31 s with the v1.0.1 copy-move speed-up, against 68-80 s before it. A profile of the earlier run put 38% of the time in the copy-move pair loop and 24% in Tesseract. The original 15-20 s figure was measured on the authors' machine and is not reproduced here.

## Pipeline

`Submission -> Classification -> OCR & extraction -> Structure -> Visual forensics -> Contextual verification -> Cross-document correlation -> Anomaly investigation -> Evidence -> Dossier`

See [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) for the diagram and data flow, and [`docs/TECHNICAL.md`](docs/TECHNICAL.md) for every method and threshold.

## Outputs (per case)

| File | What |
|---|---|
| `dossier.html` | Self-contained interactive dossier (sections 7.1 to 7.6 of the brief, plus coverage map and audit trail). Click any finding to see its evidence boxes on the original page. |
| `dossier.json` | Machine-readable version of everything above. |
| `audit.jsonl` | Hash-chained audit trail (chain of custody). `verify-audit` detects any edit. |
| `evidence/` | Evidence crops, noise heatmaps, signature crops. |
| `pages/` | Page rasters the analysis ran on (native resolution, no resampling). |

## Demo dataset

`dataset/generate.py` builds two cases for one fictional applicant. Every document is synthetic, carries a visible SYNTHETIC SPECIMEN label and uses invented institutions.

* `case_genuine`: five consistent documents (control). Expected: no potential-manipulation findings.
* `dataset/redteam/`: 16 more cases (9 manipulated, 7 genuine traps), each with `MANIFEST_ground_truth.json` stating who designed it (Argon or Claude) and the brief. Built by `dataset/redteam.py`.
* `case_tampered`: nine planted manipulations, listed in `MANIFEST_ground_truth.json`: payslip white-box overlay with a different font; copy-moved digit in a scanned statement (hiding a loan EMI); digital white-out and retyped value on the application; false income declaration; DOB mismatch; spliced ID photo; employer letter with a reproduced signature, inflated tenure and inflated salary. Plus one benign decoy (MOHD vs Mohammed) that must not escalate.

## Deliverables map (brief section 9)

| Deliverable | Where |
|---|---|
| Working prototype | `sakshi/`, `app.py`, CLI |
| Architecture overview | `docs/ARCHITECTURE.md` |
| Sample investigation dossier | `samples/DEMO-TAMPERED_dossier.html` (+ genuine control, + `RT8-SCANNED-PDF-EDITOR_dossier.html` showing the overlay peel) |
| Source repository | this repo |
| Demonstration dataset | `dataset/` (generator + generated cases + ground truth; `dataset/redteam/` blind red team) |
| Technical documentation | `docs/TECHNICAL.md` |
| Evidence traceability demonstration | dossier tab 7.5 and click-through; `docs/DEMO_SCRIPT.md` |
| Limitations and assumptions | `docs/LIMITATIONS.md` |

## Licensing assumptions

SAKSHI's own code: MIT (see `LICENSE`). Dependencies keep their own licences: **PyMuPDF is AGPL-3.0** (or commercial licence from Artifex), which matters for any hosted or commercial deployment; Tesseract is Apache-2.0; OpenCV Apache-2.0; scikit-image BSD-3; NumPy BSD; Pillow HPND; ReportLab BSD; Streamlit Apache-2.0. Fonts used by the dataset generator are Liberation / FreeFont (SIL OFL / GPL with font exception). The optional LLM narrator calls the Gemini or Claude API under their providers' terms and is off by default.

## Safety and ethics

Use only authorised or synthetic documents. SAKSHI never labels anything as fraud, never auto-rejects, treats OCR as a fallible witness, keeps a tamper-evident audit trail, and states what it could not check. See [`docs/LIMITATIONS.md`](docs/LIMITATIONS.md).
