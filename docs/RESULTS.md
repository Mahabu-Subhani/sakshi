# Results in full

The synthetic suites were measured on a Windows 11 laptop (Tesseract 5.4) on 6-8 November 2026; the public receipts were re-run on 8 November 2026 with the release under test. Existing detection thresholds were the same for every run, and nothing was tuned on the public receipts. Every dossier records the exact software it was produced with. Every suite can be rerun with the command shown.

## Synthetic suites

| Suite | Command | Data | Result |
|---|---|---|---|
| Regression | `python tests/run_eval.py` | demo case: 9 planted manipulations + 1 benign decoy (v1.0.3 result 7 potential manipulation, 11 inconsistencies, 3 observations); genuine control | all 9 found, through 14 of 14 expected detections; original net pay 68,500.00 recovered; the MOHD/Mohammed decoy stays an observation; genuine control: 0 potential manipulation, 0 inconsistencies, 1 explained observation |
| Red team | `python tests/run_redteam.py` | 16 cases: 9 attacks, 7 genuine look-alikes | 9 of 9 attacks detected (5 at POTENTIAL MANIPULATION; 6 before 1.1, when the identity ring RT7 was escalated on arrival order alone and is now contested at INCONSISTENCY); 7 of 7 genuine cases clean |
| Forgery Lab | `python tests/forgery_lab.py --seeds 2` | 6 forgery recipes x 2 seeds on fresh documents, a planned miss, 2 genuine re-scans | 12 of 12 detected (10 at POTENTIAL MANIPULATION); planned miss 0 of 2; genuine re-scans clean 1 of 2 |
| Long and locked statements | `python tests/run_long_statement.py` | 13-page statement edited on page 8; password-locked copy | all pass: the page-8 edit is caught; passwords are never written to the dossier or audit trail and are forgotten even after a crash |
| Cross-case memory | `python tests/run_registry_chain.py` | every case back to back into one memory; the genuine applicant again after the identity ring, without and with the bank's record; a verified applicant first, then the ring; both orders | all pass: nothing is flagged before the identity ring; the ring and every later application sharing its identity are contested (INCONSISTENCY); the bank's record settles the salary account (observation for its holder, POTENTIAL MANIPULATION for the ring); the photo stays contested; both orders give the same tiers |
| Concurrent memory writes | `python tests/run_registry_lock.py` | 8 processes register different cases into one memory file at once; an unreadable memory file | all pass: all 8 cases kept, no lock or temporary file left, the unreadable file left untouched |
| Bank's own record (Account Aggregator data) | `python tests/run_issuer.py` | synthetic FI data in the ReBIT deposit format for the demo applicant, attached to the genuine case, the tampered case, the Forgery Lab's regenerated statement (each of the 5 rows the recipe can change), a statement regenerated without an EMI; data for another account; a longer period; a split salary; a JSON file that is not FI data | all pass: genuine 13 of 13 rows match, nothing new reported; tampered EMI reported as 14,500 against the bank's 24,500 at POTENTIAL MANIPULATION; regenerated statement caught 5 of 5 (missed 0 of 2 without bank data); the deleted EMI reported; another account compared nothing and says so; no false finding on the longer period or the split salary |
| Digital signatures | `python tests/run_pdf_signatures.py` | the genuine payslip signed with a test CA generated in the test; edited after signing; one byte flipped | all pass: with the CA in the trust store the payslip is issuer-signed (L3) and nothing is flagged; without it the signature is information only (L2); an edit after signing and a broken signature are each POTENTIAL MANIPULATION; the genuine case with the signed payslip stays clean |
| Batch mode and REST API | `python tests/run_service.py` | tampered, genuine and RT8 cases on 3 workers; a case posted to the API | all pass: identical counts to one-at-a-time runs, audit trails intact; requests without the bearer token refused (401); dossier and audit trail downloadable; upload names cannot leave the upload folder |
| Text under a box in whole-line text runs | `python tests/run_pdf_layer_lines.py` | a synthetic born-digital letter whose lines are single text runs, edited with a white box over one number; the unedited letter; a sensor forced to miss its canary | all pass: the hidden 68,500.00 is recovered under the displayed 86,500.00 at POTENTIAL MANIPULATION; the unedited letter is clean and its canary is caught; a sensor that misses its canary is reported blind (the edit was missed and the canary failed on 1.1.0) |
| Signatures on letters | `python tests/run_signature_images.py` | synthetic letters: navy-blue printed heading and footer; a signature image above "Authorised Signatory"; the same image pasted in a later save; a scan with navy printed text and a blue pen signature | all pass: no printed text reported as a signature; the pasted image found; the later paste reported as INCONSISTENCY, the original placement not; the pen signature found and the heading not |
| Console isolation | `python tests/run_console_worker.py` | demo case through the console's worker process | all pass: same counts as the pipeline, a stalled case is stopped with nothing left running, a second run during a run is refused |
| Unreadable files | `python tests/run_rejected_files.py` | an empty PDF, a file that is not a PDF, an unsupported type and a damaged image, alone and next to the genuine case | all pass: alone, the case reads NOTHING ANALYSED (not a clean result) with every file and its reason listed; next to the genuine case, the genuine documents give the same result as alone and the broken files are listed as skipped; the command line prints each skipped file |

| Black-ink signatures | `python tests/run_signatures.py` | scanned letter and payslip signed in black ink | all pass: reproduced signature flagged as identical, different signatures not, no signature invented from printed text |
| Prompt injection | `python tests/run_prompt_injection.py` | genuine payslip with hidden white text telling reviewers to ignore anomalies | all pass: reported as a finding above the observation rung; the narrator's output check rejects uncited, unknown, incomplete or "fraud" narratives |

## Extraction accuracy

`python tests/run_extraction_accuracy.py` compares every extracted field with the generator's ground truth (exact match: amounts to the paisa, dates as ISO dates, names and identifiers ignoring spacing and punctuation).

| Condition | Documents | Fields exact | Statement rows exact |
|---|---|---|---|
| Clean | born-digital payslip; scanned statement, application form, ID card, employment letter | 48 / 48 | 13 / 13 (date, amount and running balance) |
| Phone photos | payslip and employment letter photographed and forwarded on WhatsApp | 18 / 19 (the PAN on the payslip was not read) | n/a |

No extracted field was wrong; mean OCR confidence of the correct fields is 0.90. This is one synthetic applicant on layouts the extractor knows, so it shows the extraction works, not that it generalises to every issuer's layout.

How to read these:

* **The red team is a regression suite for known attacks, not a blind test.** The cases were written as attack briefs without looking at SAKSHI's thresholds, but the detectors were then improved against them (the first version caught 3 of the first 5).
* **The flagged genuine re-scan.** On one Forgery Lab seed, OCR did not read the "Valid till" label of the re-rendered ID card, which raises a missing-field inconsistency. On Linux with Liberation fonts the same suite kept 2 of 2 genuine re-scans clean and detected 12 of 12, 9 at the top rung.
* **The planned miss** is a statement row changed with every later balance regenerated. Nothing in the documents contradicts it, so SAKSHI marks that field blind instead of guessing.

## Public data: Find it again! receipts

[Find it again!](https://l3i-share.univ-lr.fr/2023Finditagain/index.html) (ICDAR 2023, L3i La Rochelle) contains real scanned receipts, some forged by people with image editors, with the forged regions annotated. SAKSHI ran unchanged and investigated each receipt alone (`python tests/run_findit.py --data PATH/TO/findit2`; the dataset is not bundled).

| Split | Receipts (forged / genuine) | Forged flagged | Evidence on the forged region | Genuine flagged | Genuine at POTENTIAL MANIPULATION |
|---|---|---|---|---|---|
| test | 218 (35 / 183) | 18 (51%) | 6 | 102 (56%) | 0 |
| val | 193 (34 / 159) | 19 (56%) | 12 | 85 (53%) | 0 |
| train | 577 (94 / 483) | 45 (48%) | 13 | 246 (51%) | 0 |
| **all** | **988 (163 / 825)** | **82 (50%)** | **31** | **433 (52%)** | **0** |

All three splits were re-run on 8 November 2026 with this release and gave exactly the numbers of the first run on 5 November.

**Correction.** Earlier versions of this page said the train split was "held out, unread" for a future evaluation. That was wrong: it had been run on 5 November together with the other two splits. No receipt in this dataset is unseen any more, so a resolution gate for the pixel sensors cannot be judged on it honestly; it needs newly collected receipts.

At the INCONSISTENCY rung SAKSHI flags forged and genuine receipts at about the same rate. A receipt is a single low-resolution image, so the arithmetic, cross-document, PDF and bank-record checks that carry loan files cannot run; this tests the pixel sensors alone, mostly the glyph, stroke and noise sensors on thermal prints, which have no resolution gate. No genuine receipt reached POTENTIAL MANIPULATION.

### A learned layer on the same receipts

`python tests/learn_receipts.py --runs OUTDIR` asks whether what the sensors report carries signal a model can use. Features fixed in advance (for each pixel sensor: fired, highest confidence, count; which sensors were blind; page size; measured noise; number of numeric tokens); an L2-regularised logistic regression whose strength was chosen by 5-fold cross-validation on the train split only; fitted on the train split and scored once on test and val.

| Split | Learned model: ROC AUC (95% bootstrap interval) | SAKSHI's own flag: ROC AUC | At the threshold that flags 10% of train genuine receipts: forged / genuine flagged |
|---|---|---|---|
| test | 0.597 (0.485-0.707) | 0.478 (0.387-0.571) | 8 / 35 (23%) / 23 / 183 (13%) |
| val | 0.539 (0.417-0.664) | 0.512 (0.416-0.600) | 9 / 34 (26%) / 16 / 159 (10%) |

The learned combination does a little better than SAKSHI's own flag, but both intervals include 0.5: there is no reliable signal. On thermal receipts the sensors' outputs carry too little information for any combiner to fix, so this model is **not** used in SAKSHI's decisions; it is published as a measured negative result. (The sensors were designed before this dataset was used and were not changed, but the test and val splits had been looked at with the rule-based system.)

## Public data: real genuine scans (FUNSD)

How often does SAKSHI flag an untouched real scan? [FUNSD](https://guillaumejaume.github.io/FUNSD/) (Jaume et al., ICDAR-OST 2019) contains 199 real scanned business forms from the RVL-CDIP collection. Its terms allow non-commercial research and educational use and forbid redistribution, so it is not bundled and only aggregate counts are published. SAKSHI ran unchanged and investigated each scan alone (`python tests/run_image_benchmark.py --images PATH/TO/funsd/images --name funsd --out OUTDIR`).

| Genuine real scans | Flagged at INCONSISTENCY or above | At POTENTIAL MANIPULATION | Sensors raising the flags |
|---|---|---|---|
| 199 | 50 (25%) | **0** | glyph outlier 46, JPEG ghost 4, stroke weight inside a number 1, signature missing 1 |

Together with the receipts, **none of 1,024 real genuine documents reached POTENTIAL MANIPULATION**. The middle rung is not quiet on real scans: one in four business forms gets an INCONSISTENCY, almost all from the glyph-outlier sensor, which compares how each number is printed with the others on the page and has no resolution gate. An analyst should read a lone glyph outlier on a scan as a prompt to look, not as evidence.

## Public data: real tampered documents (RTM)

[RTM](https://github.com/DrLuo/RTM) (Luo et al., *Pattern Recognition* 2024) contains document images tampered by people (copy-move, cover, inpaint, splice, insert, edit) with pixel masks, and genuine images. From its official test split (1,994 genuine, 1,203 tampered) a stratified random sample was drawn with seed 2026: 300 genuine and 300 tampered. SAKSHI ran unchanged on each image alone (`tests/run_image_benchmark.py`); `tests/score_localization.py` checks whether a flagged image's boxes actually overlap the tampered pixels. The dataset is not bundled.

| Sample | Flagged at INCONSISTENCY or above | At POTENTIAL MANIPULATION | A box on the tampered region |
|---|---|---|---|
| 300 genuine | 99 (33%) | **0** | n/a |
| 300 tampered | 94 (31%) | 0 | 17 (6%) |

**SAKSHI's pixel sensors do not detect real single-image tampering**: they flag tampered and genuine images at the same rate and rarely point at the edit. This is the same result as the receipts, now on a second, independent public dataset. What holds again is the top rung: none of the 300 genuine images reached POTENTIAL MANIPULATION, which makes **0 of 1,324 real genuine documents** across three public datasets. SAKSHI's detection power on loan files comes from arithmetic, cross-document rules, PDF structure, the bank's own record and signatures, which a single tampered image does not exercise; none of those has been measured on real Indian loan files, because no public set exists.

## Handwriting: a TrOCR trial, not adopted

Could a handwriting model read what Tesseract cannot? Microsoft TrOCR (`microsoft/trocr-base-handwritten`, MIT, trained on the IAM English handwriting set) was run on CPU against Tesseract on every single-line text entity of FUNSD's 50 test forms (real scanned forms, handwritten entries included), each engine reading the same crop, scored by character error rate (case and spacing ignored).

| Lines | Tesseract error rate | TrOCR error rate | Read exactly: Tesseract / TrOCR |
|---|---|---|---|
| all 2,025 single-line entities | **0.219** | 0.316 | 811 / 434 |
| the 497 that Tesseract read with confidence below 0.5 | 0.562 | 0.551 | 56 / 60 |

TrOCR was worse overall and no better on the lines it would have been used for (202 lines read better by TrOCR, 210 by Tesseract); using it only on those lines would have moved the overall error rate from 0.219 to 0.216, at about 80 minutes of CPU for these lines and roughly 2 GB of extra dependencies. It was therefore **not added**. Handwriting stays unsupported and is reported as not read.

## Runtime

A five-document case takes 25-80 s on the test laptop, depending on load: 25-28 s in the console when the machine is idle, clean command-line medians of 41 s (tampered case) and 35 s (genuine case), up to 76 s under load. Version 1.0.1 made copy-move scoring 3.9x faster on 44,390 real glyph pairs with identical scores; run back to back, the demo case went from about 69 s to about 55 s.

Throughput (`python tests/bench_throughput.py --workers 4`, 8 November 2026, the same laptop otherwise idle, 12 logical CPUs): 8 five-document applications (4 tampered and 4 genuine demo cases) took 231.9 s on one worker, **124 cases per hour**, and 68.0 s on four workers, **424 cases per hour** (3.4x), with identical counts in both runs. Each case runs in its own process; more workers need more memory and CPU cores.
