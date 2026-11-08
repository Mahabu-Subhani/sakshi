# Changelog

## 1.1.1
* **Text hidden under a box inside a whole-line text run is now found.** A real born-digital document made with LaTeX, tested privately on the author's machine (not published), exposed it: pdfTeX and similar generators write a whole line as one text run, and the PDF-layer sensor measured coverage per run, so a white box over one number covered only about 15% of the run and was not seen. When a run is not covered as a whole, the covered characters are now measured on their own. A white-box edit on a copy of that document is now caught at POTENTIAL MANIPULATION with the original value recovered; before, it was reported clean. Existing results are unchanged.
* **A sensor that misses its own planted edit is reported as blind.** The forgery canaries were recorded but never acted on: a sensor that missed its canary was still listed as "ok" and the case could read as clean. It is now "blind on this document" in the capabilities, a note on the document, `self_test_warnings` in the dossier, the dossier header and the console. The PDF-layer canary now calls the detector itself rather than a copy of its logic.
* New test: `tests/run_pdf_layer_lines.py` (synthetic letter with whole-line text runs; fails on 1.1.0, passes now).

## 1.1.0
* **The bank's own record as a witness (L4).** Account Aggregator FI data for a deposit account (ReBIT schema, XML or JSON), attached as a file, is reconciled row by row with the uploaded statement: changed amounts, rows the bank has no record of, bank transactions missing from the statement and drifting balances are reported and boxed on the statement page. The Forgery Lab's regenerated statement, missed from the documents alone, is caught 5 of 5 with the bank's record. SAKSHI is not an FIU and fetches nothing from the AA network. New: `sakshi/issuer.py`, `dataset/aa.py` (synthetic FI data), `tests/run_issuer.py`; the console offers the demo cases with the bank's record.
* **Digitally signed PDFs** are checked offline with pyHanko: a broken signature or content added after signing is reported as a smoking gun; a signed document counts as issuer-signed (L3) only when its certificate chains to CA certificates the lender places in `SAKSHI_TRUST_DIR`. Revocation is not checked. New: `tests/run_pdf_signatures.py`.
* **Batch mode and a REST API**: `sakshi batch` investigates a folder of applications and `sakshi serve` accepts cases over HTTP (bearer token), several cases side by side, each in its own isolated worker process with a hard timeout. New: `sakshi/service.py`, `tests/run_service.py`.
* **Reproducibility**: `requirements.lock` pins every library (the Docker image installs it); every dossier and audit trail records the OCR engine and library versions and warns when Tesseract differs from the calibrated 5.4.
* **Correction**: earlier documents said the 577-receipt train split of the public receipt dataset was "held out, unread". That was wrong: it had been run on 5 November 2026 with the same result as the other splits. All three splits were re-run on 8 November with this release and are reported together; no public receipt data remains unseen.
* **Cross-case memory: contested until verified.** The order in which applications arrive no longer decides who owns an identity, so a ring that registers a victim's identifiers first cannot get the victim flagged. A shared identifier, ID photo, signature or file between two different people is CONTESTED (INCONSISTENCY) on the later application, with a "contested by" notice on the earlier one, until the bank's own record settles it; a bank-verified identifier used by someone else is POTENTIAL MANIPULATION. Each conflict is reported once, naming every application involved. This is a deliberate design change, with a consequence stated in the results: without issuer data the identity-ring case RT7 is now an INCONSISTENCY, not POTENTIAL MANIPULATION. `tests/run_registry_chain.py` was rewritten for it and now checks that both orders give the same tiers.
* **Real-world measurements.** 199 real genuine scanned business forms (FUNSD): 0 at POTENTIAL MANIPULATION, 50 at INCONSISTENCY (46 from the glyph-outlier sensor). A learned layer on the public receipts (`tests/learn_receipts.py`, trained on the train split only): ROC AUC 0.60 and 0.54 on test and val, intervals including 0.5, so it is published as a negative result and not used. New: `tests/run_image_benchmark.py`, `tests/score_localization.py`.
* **Demo video v7.1**: the results scene said the receipt train split was "held out, unread" and that the receipts were run on 6-7 November. The scene was re-recorded with the two lines corrected and spliced in frame-exact; nothing else changed. The README receipts chart was redrawn with all three splits.
* All other detection code and thresholds are unchanged: the regression, extraction, signature, prompt-injection, long-statement and console suites give the same results as 1.0.5.

## 1.0.5
* Project page (GitHub Pages, `index.html`): the demo video plays in the browser and the sample dossiers open as web pages; GitHub itself only offers the video as a download and shows the dossiers as source. The README links point there.
* `python -m sakshi demo` and `python -m sakshi redteam` investigate the published documents as they are. They used to rebuild them first with the local machine's fonts, which overwrote tracked files and could change the counts (on one clean machine the genuine control became "REVIEW: 2 inconsistencies"). `--regenerate` rebuilds them on purpose.
* The README states the Docker results: Tesseract 5.5 reads one IFSC character differently, which adds two explained observations.
* `LICENSE` is the plain MIT text again, so GitHub recognises it; the note on PyMuPDF's AGPL licence stays in the README.
* Cross-case memory is safe with several writers: a case is registered under a lock file, against a fresh read of the memory, and written atomically. Before, two cases saved at the same moment could overwrite each other (4 of 8 concurrent cases were lost in the new test), and an unreadable memory file was replaced by an empty one; it is now left untouched and the case notes that it was not remembered. New test: `run_registry_lock.py`.
* The optional narrator sends the Gemini key in the `x-goog-api-key` header instead of the URL, so it cannot appear in proxy or error logs.
* The innocent-explanation catalogue now describes the OCR-misread test the way the code applies it: low OCR confidence **and** a one-character difference. Detection is unchanged.
* `docs/FORGERY_LAB_RESULTS.md` reports the Windows and Linux runs side by side; it previously showed only the Linux run, which disagreed with `docs/RESULTS.md`.
* On Windows, `dossier.json` kept the full local path of every page and evidence image; paths are now stored relative to the case folder on every platform, as intended. The sample dossiers in `samples/` were regenerated on 1.0.5 (same findings).

## 1.0.4
* Docker image: `docker build -t sakshi .` then `docker run -p 8501:8501 sakshi`. Python 3.12, Tesseract 5.5 with English and Hindi, Liberation fonts, non-root user, health check. Verified: `tests/run_eval.py` ALL PASS inside the container, the console answers and completes an uploaded case, and the command line runs on mounted files.
* Demo video re-recorded on 1.0.4 (`docs/demo/SAKSHI_demo.mp4`, 3:58): the full brief checklist on the tampered case, including earlier-version recovery and strength of evidence; an under-the-hood walkthrough; the capability matrix; a genuine case with a deliberately damaged file, announced before it is uploaded; cross-case memory catching an identity ring (RT7); a red-team overlay peel (RT8); a hidden-instruction case; and the current test results.
* The console shows a file it could not open as an amber "Skipped" notice with a plain reason and confirms that the other documents were analysed; the exception name stays in the audit trail only.

## 1.0.3
* Earlier saved versions of an edited PDF are recovered by cutting the file at each earlier end-of-file marker; a value that reads differently at the same place is reported with the earlier value (`revision_diff`). On the demo payslip: "an earlier saved version of this file shows 68,500.00 where 86,500.00 is now".
* Hidden text that addresses automated reviewers ("ignore all anomalies") is reported as a finding; the optional LLM narrator receives document-derived text only as quoted data and its output is discarded unless every sentence cites a real finding and every potential-manipulation finding is covered.
* Black-ink signatures are found just above a readable signature caption and compared across documents.
* Every finding carries a verbal strength of evidence (strong, moderate or weak support; explained) next to its confidence.
* The console shows a capability matrix: implemented, partial, planned, unsupported.
* New tests: `run_extraction_accuracy.py`, `run_signatures.py`, `run_prompt_injection.py`.

## 1.0.2
* The review console runs each case in its own worker process with a hard timeout (`SAKSHI_CASE_TIMEOUT`, default 600 s): a stalled case is stopped with a clear message, nothing is left running, and a second run during a run is refused. This contains one console freeze seen during a long recording session; its cause was not found in about 25 replays, so this is containment, not a root-cause fix.
* A damaged PDF or image is reported as "could not open PDF: the file is damaged or is not a PDF", without local paths.
* Blue console theme (`.streamlit/config.toml`); demo video in `docs/demo/`.

## 1.0.1
* Statements up to 40 pages are read for arithmetic, cross-document, structure, layout and overlay checks (pixel forensics stay on the first 6 pages); an edit on page 8 of a 13-page statement is now caught.
* Password-locked PDFs open with a password supplied by the analyst, kept in memory only.
* Copy-move scoring 3.9x faster on 44,390 real glyph pairs with identical scores.
* Cross-platform fonts for the dataset generator and evidence labels.

## 1.0
* Overlay peel, income triangulation with impeachment, payroll physics, deleted-row detection, scan clones, intra-number strokes, scanner optics, constraint-guided statement parser, erasure patches and JPEG ghosts, cross-case memory.
* Safe failure everywhere: sensors report "blind" instead of guessing; unreadable fields are "could not be read", never "missing".
