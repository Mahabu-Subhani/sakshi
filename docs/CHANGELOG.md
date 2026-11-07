# Changelog

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
