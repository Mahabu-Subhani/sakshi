# Changelog

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
