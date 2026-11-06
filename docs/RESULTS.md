# Results in full

All numbers were measured on a Windows 11 laptop on 6-7 November 2026. Detection code and thresholds were the same for every run reported here, and nothing was tuned on the public receipts. Every suite can be rerun with the command shown.

## Synthetic suites

| Suite | Command | Data | Result |
|---|---|---|---|
| Regression | `python tests/run_eval.py` | demo case: 9 planted manipulations + 1 benign decoy; genuine control | all 9 found, through 14 of 14 expected detections; original net pay 68,500.00 recovered; the MOHD/Mohammed decoy stays an observation; genuine control: 0 potential manipulation, 0 inconsistencies, 1 explained observation |
| Red team | `python tests/run_redteam.py` | 16 cases: 9 attacks, 7 genuine look-alikes | 9 of 9 attacks detected (6 at POTENTIAL MANIPULATION); 7 of 7 genuine cases clean |
| Forgery Lab | `python tests/forgery_lab.py --seeds 2` | 6 forgery recipes x 2 seeds on fresh documents, a planned miss, 2 genuine re-scans | 12 of 12 detected (10 at POTENTIAL MANIPULATION); planned miss 0 of 2; genuine re-scans clean 1 of 2 |
| Long and locked statements | `python tests/run_long_statement.py` | 13-page statement edited on page 8; password-locked copy | all pass: the page-8 edit is caught; passwords are never written to the dossier or audit trail and are forgotten even after a crash |
| Cross-case memory | `python tests/run_registry_chain.py` | every case back to back into one memory | all pass (20 runs): only the identity ring is flagged |
| Console isolation | `python tests/run_console_worker.py` | demo case through the console's worker process | all pass: same counts as the pipeline, a stalled case is stopped with nothing left running, a second run during a run is refused |

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

At the INCONSISTENCY rung SAKSHI flags forged and genuine receipts at about the same rate. A receipt is a single low-resolution image, so the arithmetic, cross-document and PDF checks that carry loan files cannot run; this tests the pixel sensors alone, mostly the glyph, stroke and noise sensors on thermal prints, which have no resolution gate yet. No genuine receipt reached POTENTIAL MANIPULATION. The 577-receipt train split is held out, unread, for one future evaluation of a resolution gate.

## Runtime

A five-document case takes 25-80 s on the test laptop, depending on load: 25-28 s in the console when the machine is idle, clean command-line medians of 41 s (tampered case) and 35 s (genuine case), up to 76 s under load. Version 1.0.1 made copy-move scoring 3.9x faster on 44,390 real glyph pairs with identical scores; run back to back, the demo case went from about 69 s to about 55 s.
