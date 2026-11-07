# Forgery Lab results

`python tests/forgery_lab.py --seeds 2` makes fresh documents with the dataset generator, applies each forgery recipe and investigates the result. The generator draws the documents with the fonts installed on the machine, so Windows and Linux runs investigate slightly different documents; both runs are reported. Detection code and thresholds were the same in both.

| Recipe | Windows 11 (7 Nov 2026): detected | at potential manipulation | Linux, Liberation fonts: detected | at potential manipulation |
|---|---|---|---|---|
| PDF white-box overlay, different font | 2/2 | 2/2 | 2/2 | 2/2 |
| PDF white-box overlay, same font | 2/2 | 2/2 | 2/2 | 2/2 |
| Scan copy-move digit (statement) | 2/2 | 2/2 | 2/2 | 2/2 |
| Scan white-out and retype (application) | 2/2 | 2/2 | 2/2 | 1/2 |
| Paint patch + JPEG 70 (letter) | 2/2 | 2/2 | 2/2 | 2/2 |
| ID photo splice | 2/2 | 0/2 | 2/2 | 0/2 |
| Regenerated statement, non-recurring row (expected miss) | 0/2 | 0/2 | 0/2 | 0/2 |
| **Total, forgeries** | **12/12** | **10/12** | **12/12** | **9/12** |
| Genuine re-scans (false-alarm check) | clean 1/2 | | clean 2/2 | |

The genuine re-scan flagged on Windows (seed 0) raised one INCONSISTENCY: OCR did not read the "Valid till" label on the re-drawn ID card, so the field was reported missing. No genuine re-scan reached POTENTIAL MANIPULATION on either platform.
