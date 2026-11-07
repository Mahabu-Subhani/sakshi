# Changelog

## 1.0.4
* Docker image: `docker build -t sakshi .` then `docker run -p 8501:8501 sakshi`. Python 3.12, Tesseract 5.5 with English and Hindi, Liberation fonts, non-root user, health check. Verified: `tests/run_eval.py` ALL PASS inside the container, the console answers and completes an uploaded case, and the command line runs on mounted files.

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
