# SAKSHI technical documentation

All coordinates are page pixels at the analysis resolution (200 DPI for rendered PDFs, native resolution for scans and images).

## 1. Ingestion (`ingest.py`)
* SHA-256 of every input, logged before anything else is read.
* **Born-digital PDF** (15+ words in the text layer): words come from the text layer with font name and size (PyMuPDF `rawdict`, character-level boxes merged into words). The page is also rendered and OCR'd as a second, independent reader (dual read).
* **Scanned PDF** (v1.0 rule): every page is one dominant image covering >= 85% of the page with fewer than 15 **visible** words on top. Invisible words (render mode 3, zero opacity) do not count, so CamScanner / Adobe Scan "searchable" PDFs are analysed as scans and their OCR layer is ignored. The embedded image is extracted at native resolution (rendering would resample the sensor noise).
* **Overlay peel** (v1.0): for every scan page the page is also rendered on the scan's own pixel grid (what a reader sees) and compared with the bare embedded scan, both through the PDF object list (visible text spans, filled/stroked shapes, extra images) and through a pixel difference (max channel difference > 48, opened 2x2, regions >= 40 px), which also catches annotations and edits nested in Form XObjects. If anything is drawn on top, the rendered page becomes the analysis image and the bare scan is kept for `forensics/scan_overlay.py`. Rotated pages and pages where > 20% of pixels differ (misaligned) fall back to the object list.
* **Images**: decoded to RGB. If projection-profile skew exceeds 1 degree (phone photo), a deskewed copy is used for OCR and the dossier notes that pixel forensics ran on resampled pixels.
* **Page limits** (v1.0.1): every page up to 40 is read (text layer or OCR), so arithmetic, cross-document, PDF-structure, layout and overlay-peel checks see a whole statement; pixel forensics (noise, copy-move, glyphs, erasure and ghosts, strokes, optics, signatures, scan clones, canaries) run on the first 6 pages only, for cost. Both limits are noted in the dossier when they apply.
* **Password-protected PDFs** (v1.0.1): opened only with a password supplied by the analyst (`--password`, repeatable, or the console field); every supplied password is tried on every locked PDF. The password lives in process memory for the duration of the case (keyed by the resolved file path, and removed in a `finally` even when the case fails), is never written to the dossier or audit trail, and the dossier notes only that one was used.
* Fails safely on unsupported types, corrupt files and locked PDFs without a working password (document rejected with a reason, case continues).

## 2. Classification (`classify.py`)
Weighted cue phrases per type. A type is accepted only with score >= 3 and a margin >= 2 over the runner-up; otherwise `unknown` (generic extraction, contextual rules skipped). Witness level by type: application form L0 (self-declared claim), scanned employment letter L1, statement / payslip / ID L2.

## 3. Extraction and structure (`extract.py`)
* Lines: Tesseract's own line structure for OCR words; vertical-overlap grouping for PDF words.
* Label-anchored fields: OCR-tolerant label regex (e.g. `EMls` still matches `EMIs`); value = first word run after the label, ending at a gap > 40 px, which separates two-column layouts. Card layouts take the value from the next line.
* Tables (v1.0, `forensics/table_parser.py`): four layout hypotheses (debit/credit/balance, credit/debit/balance, amount + Dr/Cr, signed amount) scored by how many balance transitions each makes true; header synonyms; multi-line narrations; B/F, C/F and total rows classified; page footers skipped. Low-confidence cells are re-read by an independent crop-only OCR (digits whitelist, psm 7) and healed only if the second read makes this and the next transition hold ("re-read, never rewrite"). Payslip earnings / deductions split by page half.
* Column sanity (v1.0): a balance cell whose right edge is more than 40 px from the balance column's median is moved to the debit/credit column it sits in, or dropped (row marked unreadable). The balance fit used for gating is computed only over transitions whose cells were read with confidence >= 0.6.
* Masked identifiers (`XXXXXX821Q`, `****7812`) are removed from the field set and reported as masked, never as missing or mismatched.
* Normalizers: Indian digit grouping, `14 500.00` OCR splits, DD-MM-YYYY to ISO, names upper-cased without honorifics, IDs stripped. Amount in words parsed with the Indian system (thousand, lakh, crore).
* Field confidence = minimum word confidence for numbers/IDs/dates (one bad glyph spoils a number), mean otherwise.
* Structure: required fields per type, missing and duplicated fields, section list.

## 4. Visual forensics (`forensics/`)
| Sensor | Method | Key thresholds | Applies to |
|---|---|---|---|
| PDF archaeology | content-stream sequence numbers of text spans (`get_texttrace`) vs filled shapes (`get_drawings`): value-like text painted before an opaque shape that overlaps it >60%, with different text drawn after | occlusion 0.6, overlay 0.5 | digital PDF |
| Font mix | numeric spans whose font family is a minority (<=20%) on the page | | digital PDF |
| Invisible text | render mode 3, zero opacity, or white text on a white background | rendered mean > 235 | digital PDF |
| Incremental update / metadata | `%%EOF` count > 1; creation vs modification date > 60 s apart | | digital PDF |
| Noise consistency (page) | 16 px windows, stride 8, mean absolute median-filter residual on flat pixels (gradient < 18), ratio to page median | too clean < 0.42, too noisy > 3.0; drop aspect > 9 or fill < 0.35 (creases) | scans |
| Noise consistency (value box) | same estimator restricted to paper pixels between the glyphs of each extracted value | ratio to the median of other value boxes < 0.35 | scans |
| Copy-move | digit glyph components inside numeric tokens; shape IoU > 0.8 prefilter; median absolute difference on paper pixels, +-1 px alignment, normalized by page noise x sqrt(2) | < 0.40 (genuine pairs score 0.6-1.0); skips noise-free paper and digits within one token | scans |
| Typography | per numeric token: ink darkness, stroke width / height, digit height vs page digit height, baseline vs line-mates, edge sharpness; robust z vs the document's own tokens | 2+ features beyond 3.5 sd or one beyond 7; singleton guard | scans |
| Layout rhythm | value left edges (forms) and amount right edges (tables) fitted with Theil-Sen over y (skew-proof); row pitch | residual > max(4 px, 4 x MAD) | forms, statements |
| Erasure patch | value box vs a ring outside a 6 px pad: robust MAD x 1.6 of `gray - medianBlur(gray, 3)` | ring std > 1.5 and inner < 0.25 x ring | scans |
| JPEG ghosts | full-page re-encode at q 50-95, gradient-normalized error per box, robust z | z > 4 and box quality != page quality | scans |
| Intra-number stroke consistency | digits of one pure number (4+ digits): stroke width = ink area / skeleton length; every contiguous run of 2+ digits vs the rest | rest spread <= 8%, run z >= 4.5 and >= 15% off; blind below 16 px digit height | scans, photos |
| Scanner optics | edge sharpness = p98 gradient / ink contrast per word; baseline from confident words; numeric candidates | z >= 4.0; page vetoed if > 8% of words have z > 3 or > 5 hits; blind if text < 18 px | scans, photos |
| Scan clones (between documents) | ORB 3000 on half resolution, RANSAC homography (>= 60 inliers), 64 px block correlation of the median-filter residual | median correlation >= 0.45, smoking gun > 0.6; difference regions = the edits | scans |
| Overlay peel | rendered page vs embedded scan at each drawn region: hidden scan ink (scan < 130, render > 200), added ink; OCR of both sides | smoking gun if a different number is typed over a number; redaction if masking characters or a dark empty box; hidden ink must form >= 2 character-sized blobs | scanned PDFs |
| Signatures | blue-ink HSV mask, stroke-width filter (rejects photos and logos), placement relative to "Signature/Signatory" captions; cross-document dilated IoU of normalized masks | identical >= 0.72 (natural variation on this data 0.0-0.6) | all |

## 5. Contextual and cross-document reasoning (`reasoning/`)
**Invariants** (`invariants.py`), all with provenance to field refs:
* Payslip: P1 sum(earnings) = gross; P2 sum(deductions) = total; P3 gross - total = net; P4 net in figures = net in words.
* Statement: B1 running balance per row (rows without a printed balance are bridged into the next row that has one; a row with an unreadable amount restarts the chain); B2 opening / total debits / total credits / closing; B3 recurring fixed obligations (EMI, loan, rent, SIP, insurance; salary as *soft*); B4 recurring obligation missing in a later month (an expectation). **Deleted row** (v1.0): a B1 break whose residual equals a recurring obligation missing that month, with no printed line between the two rows, is reported as a removed row.
* Statutory (v1.0, soft): S1 employee PF >= 12% of basic + DA, or exactly 1,800 / 3,600 (ceiling); only a PF *below* 12% contradicts (an inflated basic leaves it there); implied basic = PF / 0.12. S2 Karnataka professional tax 200 (300 in February) above 25,000 gross when the employer is in Karnataka.
* Cross-document: X1 payslip net = salary credit in the pay month or within 7 days of pay date (an *expected record*: if the statement covers the pay date and no salary-like credit exists, that absence is itself a finding); X2 declared income = payslip net; X3 letter salary = payslip net or gross (by the letter's wording); X4 declared EMI = EMI debits per month.
* Equality groups: name, DOB, PAN, account, IFSC, employer, designation, date of joining, employee ID, address.
* Formats: PAN (AAAAA9999A, 4th letter P for individuals, 5th = surname initial), IFSC (AAAA0XXXXXX), ID validity, statement date order and period.

**Counterfactual repair** (`repair.py`): broken linear rules are grouped into clusters sharing fields. Candidates = fields of broken rules plus one hop through rules that hold. For subsets of size 1, 2, 3 the solver solves the linear system exactly (least squares, residual < 0.51, full rank, every value actually changes). Cost of blaming a field = witness weight (L0 0.6, L1 1.0, L2 2.0, L3 4.0, L4 8.0) x (0.25 + 0.75 x OCR confidence). Minimal cardinality wins, then minimal cost; alternatives and ties are reported.

**Income triangulation** (v1.0): every independent witness to monthly income is listed with a weight: payslip net 2.0, net implied by the PF actually deducted 2.0, pay-month salary credit 2.0, other-month credits 1.0, value peeled from under a PDF overlay 2.0, employer letter 1.0 (2.0 if L2), declaration 0.6. A document that breaks its own arithmetic or statutory rule is impeached (x 0.5), except its *confession* witnesses (PF-implied net, peeled value). Witnesses within 1 rupee cluster; one document adds at most 2.0 to one value. A value wins only with >= 1.5x the support of the runner-up and no impeached witness in its group; otherwise SAKSHI refuses to pick a side and marks the solver's repair *contested* (it cannot escalate unless pixel or file-structure evidence backs that field). If only other-month credits disagree, it is an observation (increment, LOP, variable pay).

**Odd one out** for equality groups: values are clustered after normalization (transliteration dictionary for names, punctuation-insensitive text, fuzzy >= 90% for addresses); the cluster with the least total witness weight is the suspect; ties are reported.

## 6. Devil's advocate (`devils_advocate.py`, `benign_catalog.json`)
One deterministic test per innocent explanation in the catalog. Results: `ruled_out`, `plausible` (blocks escalation), `explains` (demotes to observation), `not_testable` (stated in the dossier). Examples: rounding (< Rs 1), OCR misread (confidence < 0.6 and one character apart), unlisted components (bonus / arrears keywords), timing (pay-date window), transliteration, day-month swap, one-character typo, OCR confusion O/0 I/1 S/5 B/8, JBIG2 symbol substitution (copy-move false positive in scanned PDFs), digital signature insertion, printed stored signature image, AcroForm fonts, e-sign incremental saves.

## 7. Fusion and tiers (`fusion.py`)
1. Visual findings are attached to the fields whose boxes they overlap (>30%).
2. For every field, the independent evidence families touching it are collected.
Evidence families (v1.0, split by physics): `pixel` (noise, copy-move, erasure, JPEG ghost, scan clone: one witness together), `optics`, `typography`, `geometry`, `signature`, `file_structure`, `logical`, `cross_document`, `identity`, `pattern`, `statutory`, `cross_case`.
3. Tier: explained -> OBSERVATION; any plausible innocent explanation -> INCONSISTENCY; otherwise POTENTIAL MANIPULATION if a smoking gun, or 2+ families converge on the field and the finding itself is strong (repair solver, smoking gun, or confidence >= 0.8). Weak sensors stay INCONSISTENCY and are marked *supporting*: a weak sensor alone can raise an INCONSISTENCY, but it can never lead a field to POTENTIAL MANIPULATION. (On the real-receipt stress test, lone glyph, stroke and noise findings are the main source of INCONSISTENCY false alarms; see section 10.) Findings about self-declared claims escalate only when the claim document itself shows visual or file-structure evidence.
4. Severity = tier base (10 / 40 / 70) + 8 per extra family + 10 for a smoking gun + 8 x confidence.
5. Hypotheses (threads): findings linked by shared fields or diagnoses. Document assessments summarize documents with 3+ anomalies across 2+ families and are not counted as findings.

## 8. Self-assessment
* **Coverage map** (`coverage.py`): on the counterfactually repaired values, each field is mutated in memory; STRONG = detected and localized by 2+ rules, WEAK = detected, BLIND = no rule notices. Coordinated attacks: internally consistent payslip inflation, hidden EMI with regenerated balance column, inflated salary credit with regenerated statement.
* **Forgery canaries** (`selftest.py`): same-source copy-move and white-out canaries on scans; an in-memory white-box edit on digital PDFs.

* Since v1.1.1 a sensor whose canary result is 0 of n is reported as "blind on this document" (capabilities, document notes, `self_test_warnings`, dossier header, console), and the PDF-layer canary calls the detector itself. Text hidden under a filled shape is matched per text run when 60% of the run is covered, otherwise per character (`pdf_layers.covered_text`), so one word under a box inside a whole-line run is found.

## 8b. Cross-case memory (`registry.py`, v1.0; contested until verified since v1.1)
Per investigated case, stored locally (no images, no raw documents): normalized names, PAN / account / mobile / ID number / employer + employee ID, SHA-256 per file, 64-bit pHash of each ID-card photo, 48 x 16 stroke-density grid per application signature. Checks against earlier cases of a *different* applicant: identical file, shared identifier, photo hash distance <= 8 bits (unrelated photos differ in about 32), signature grid IoU >= 0.8. The same applicant re-submitting the same files is a duplicate-submission observation. Since v1.1 order decides nothing: each conflict is reported once on this application, naming every remembered application involved, as CONTESTED (INCONSISTENCY, with the innocent explanation "this applicant is the genuine holder" left plausible), and a "contested by" notice is written to the other applications' memory records. Identifiers the bank's own record confirms for this applicant (holder name or PAN matches; account numbers ending in the bank's four digits; the holder's PAN) are stored as verified: a later application by someone else using a verified identifier is a smoking gun, and this applicant's own use of it is an observation. The Streamlit console shows how many cases are remembered and has a Reset button.

## 8c. The bank's own record (`issuer.py`, v1.1)
* Input: Account Aggregator FI data for a deposit account in the ReBIT schema shape (`Account` with `Profile/Holders`, `Summary`, `Transactions/Transaction`), as XML (namespaces ignored, no external entities) or its JSON rendering inside any envelope. Only `DEBIT` and `CREDIT` transactions are rows. It is an L4 witness; SAKSHI reads it from a file and is not an FIU.
* Account check first: the last four digits of the statement's account number against the masked account number. Different digits: one `issuer_account_mismatch` finding and no row compared. Unreadable on one side: the holder name (transliteration-aware) must match, or nothing is compared.
* Window: only rows inside both the bank data's period and the statement's own date range.
* Matching, in passes over unmatched rows: (1) same direction, amount within Rs. 0.005, same transaction or value date; (2) the same, one day apart, closest date first; (3) a statement credit equal to the sum of 2 or 3 bank credits on the same day (split salary); (4) one statement row and one bank transaction left on the same date and direction with different amounts.
* Findings, each boxed on the statement page: `issuer_amount_differs` (pass 4), `issuer_row_missing` (statement row with no bank match), `issuer_row_absent` (bank transaction missing from the statement; boxed at the nearest row by date), `issuer_balance_differs` (first matched row whose running balance differs from the bank's, with the number of rows and the gaps). All are smoking guns: the issuer's own record contradicts the document.
* Innocent explanations (devil's advocate): OCR misread (confidence below 0.60, and one character apart for changed amounts), a row SAKSHI did not read (balance-equation fit below 0.95 or unreadable rows), a different posting date (searched ±1 day), outside the period (excluded by construction), a second account (not testable). A plausible explanation keeps the finding at INCONSISTENCY.

## 8d. Digital signatures (`forensics/pdf_signature.py`, v1.1)
* pyHanko validates every embedded signature offline: integrity of the signed bytes, coverage (entire file or an earlier revision) and the kind of change made after signing.
* `signature_broken` (signed bytes changed or signature invalid) and `signed_then_modified` with content changes are smoking guns; changes limited to annotations stay at INCONSISTENCY (a reviewer's stamp is plausible).
* Trust: certificates in `SAKSHI_TRUST_DIR` (PEM or DER) are the only trust anchors; no fetching, no revocation checking. A valid signature that chains to them raises the document to witness level L3 (weight 4 in the repair solver); otherwise it is information only.

## 8e. Throughput and integration (`service.py`, v1.1)
* A thread pool hands each case to its own spawned worker process with a hard timeout (the console's isolation without its one-case lock). `sakshi batch` writes `summary.csv` and `summary.json` (cases per hour); `sakshi serve` is a Starlette app on Uvicorn: `POST /v1/cases`, `GET /v1/cases/{id}`, `GET /v1/cases/{id}/{dossier.html|dossier.json|audit.jsonl}`, `GET /v1/health`. Bearer token from `SAKSHI_API_TOKEN`, required before listening beyond localhost; upload names are reduced to a bare safe file name; at most 20 files of 50 MB.

## 9. Dossier and audit
* `dossier.json` holds everything; `dossier.html` is generated from it and is fully self-contained (embedded page images, no external scripts).
* `audit.jsonl`: each event stores `prev_hash` and its own SHA-256 over the canonical JSON; `verify()` reports the first broken link.

## 10. Evaluation
* `tests/run_eval.py` (regression, unchanged since v0.9): tampered case, 14 planted-manipulation checks, the benign decoy and recovery of the original net pay; genuine case, zero potential-manipulation findings. v1.0: all pass; genuine case 0 inconsistencies, 3 observations.
* `tests/run_redteam.py`: the red-team cases and genuine traps in `dataset/redteam/` (see README scoreboard). Manipulated = detected if any non-observation finding points at the target document/field; genuine = clean if no inconsistency or potential manipulation.
* `tests/forgery_lab.py`: forgery recipes applied to fresh genuine documents with several random seeds, plus genuine re-scans as a false-alarm check.
* `tests/run_registry_chain.py`: every case run back to back into one cross-case memory; the identity ring and the applications after it are contested, nothing before it; the bank's record settles the salary account; the same tiers whatever the order.
* `tests/run_long_statement.py` (v1.0.1): a 13-page born-digital statement and its scanned copy with one amount edited on page 8 (balances kept), plus an AES-256 password-locked copy. Passes when the page-8 edit is caught, the genuine statement stays clean, the locked copy is rejected without its password and reads like the unlocked file with it, and the password appears in neither the dossier nor the audit trail. With reading capped at 6 pages (the v1.0 limit), the same edit produces no finding at all.
* `tests/run_findit.py` (real-data stress test): every receipt of the public Find it again! dataset (ICDAR 2023, L3i) investigated alone with unchanged code. Forged = detected if any INCONSISTENCY or POTENTIAL MANIPULATION finding appears, localized if a finding's evidence box overlaps an annotated forged region; genuine = clean if none appears. Results are in the README. The test and val splits were inspected while diagnosing the false alarms, so any future fix must be judged on the train split and labelled post-hoc on the others.
* **Environment dependence of observations:** on the authors' build the genuine case had 3 observations, two of them `format_violation` because OCR read the IFSC `DCBL0001234` as `DCBLO0001234`; Tesseract 5.4 on Windows reads it correctly, leaving 1 observation (the name transliteration). Format rules sit on top of OCR, so their OBSERVATION count can vary with the Tesseract build; tiers above OBSERVATION did not change.
* **Runtime:** see the README for the measured figure and profile.

## References used as guidance (no compliance claimed)
ISO/IEC 27037 (identification, collection, preservation: hashing at intake, chain-of-custody log), ISO/IEC 27041 (method assurance: canaries, coverage map), ISO/IEC 27042 (analysis and interpretation: separation of observation, inconsistency and interpretation), NIST SP 800-86, OWASP ML Top 10 (input validation, no model trained on user data, LLM kept out of decisions).
