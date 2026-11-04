# Live demo script (about 6 minutes)

Follows the judges' live demonstration checklist (brief section 10) in order. Run `streamlit run app.py` beforehand and `python -m sakshi demo` once so the dataset exists.

| # | Checklist item | What to do | What judges see |
|---|---|---|---|
| 1 | Upload multiple documents | Drag the 5 files of `dataset/cases/case_tampered/` into the uploader, click **Investigate**. | Progress bar walking the 10 stages of the brief, one case in about 20 s. |
| 2 | Classification and OCR | Dossier tab **7.1**: type, confidence and cues for each file; modality; witness level; SHA-256. | "Salary slip 92%, cues: payslip, net pay, gross earnings..." |
| 3 | Structured representation | Tab **7.2**: every field with raw value, normalized value, confidence, method and location. Click a location. | The original page opens with that value boxed. Hidden text found in the payslip file is listed. |
| 4 | Suspicious regions highlighted | Tab **Investigation**, hypothesis 1, finding *Value '68,500.00' is hidden under a filled shape*. | The payslip with the box drawn around 86,500.00, the recovered original 68,500.00. |
| 5 | Inconsistencies within one document | Same hypothesis, *Net Pay reads 86,500.00; consistent only if 68,500.00*. | Broken rules: gross - deductions = net, net in figures = net in words ("Sixty Eight Thousand Five Hundred"). |
| 6 | Cross-document comparison | Same finding and tab **7.3**: claim graph, diagnoses. | Bank salary credit 68,500.00 on 31-10-2026 contradicts the slip; solver says change 3 values: slip, application, letter. |
| 7 | Relationships between findings | Hypothesis 2: statement EMI debit + copy-move glyph + application white-out + typography + alignment. | Five findings from four sensors converging on one hidden loan of 24,500. |
| 8 | Inspect evidence | Click **Show in source document** on the copy-move evidence. | Two numbered boxes: the pasted '1' in 14,500.00 and its donor in 1,180.00. |
| 9 | Final dossier | Tab **7.6** and the download buttons. | Summary, hypotheses, areas to verify, limitations; HTML, JSON and audit downloads. |
| 10 | Trace findings back | Tab **7.5**: every evidence item with page and pixel box; click any. | Click-through to the exact region. |
| 11 | Potential vs confirmed | Point at the tier tags and the devil's advocate table. DOB mismatch stays INCONSISTENCY (one-character typo is plausible). MOHD vs Mohammed is an OBSERVATION explained by transliteration. | The system argues against itself before escalating. |
| 12 | Safe failure, honest gaps | Upload a `.docx` or a corrupt PDF together with the genuine case; open **Coverage map**. | Rejected file with a reason, the rest analysed. Blind fields listed (ID number, validity dates, mobile, loan amount). Canary results per document. |

Then the closing contrast: run `dataset/cases/case_genuine/`. Same applicant, same layouts: **no rule-breaking anomaly found**, 3 observations, each explained by an innocent cause.

## v1.0 add-on (about 4 minutes): attacks we did not plant ourselves

All from the **Demo case** drop-down in the console (red-team cases), cross-case memory on.

| # | Case | What to say | What judges see |
|---|---|---|---|
| 13 | `RT8_scanned_pdf_editor` | "The commonest real edit: a scanned payslip opened in a PDF editor, white box over net pay, new number typed on top." | Evidence image, left: what a reader sees (88,500.00); right: the scan stored inside the same file, underneath (68,500.00). Income triangulation: the scan underneath and the bank credit agree on 68,500 (4.0 vs 1.6). |
| 14 | `RT9_annotation_overlay` | "Same trick hidden in a comment annotation. Object parsers miss it; we compare pixels." | Overlay peel on the October salary credit, plus the balance chain breaking at that row. |
| 15 | `RT2_drcr_deleted_emi` | "A whole EMI row deleted from a Dr/Cr statement, and the applicant declares no EMIs." | "Consistent only if a removed row is restored: 24,500 debit in 2026-10". |
| 16 | `RT4_cloned_payslip_scans` | "October payslip made from September's scan. Two real scans never share paper grain." | Scan-clone finding, the difference map pinpoints the edited month and date. |
| 17 | `RT1_coordinated_inflation` | "Everything inflated together, math kept consistent. Watch SAKSHI refuse to blame the honest letter." | PF 4,800 implies basic 40,000, not 60,000. Triangulation: neither side decisive, the solver's repair marked *contested*. Honest uncertainty instead of a wrong accusation. |
| 18 | `case_genuine`, then `RT7_identity_ring` | "Cross-case memory. A different applicant, internally clean documents." | Identity ring: same ID photo image and same salary account as an earlier applicant. Then **Reset memory**. |
| 19 | `G10_genuine_whatsapp_photos`, `G12_genuine_redacted_pan` | "Genuine documents in bad shape: WhatsApp-forwarded photos, a self-redacted PAN." | No rule-breaking anomaly. Capabilities say which sensors were blind and why; the redaction is recorded, not flagged. |

## One-line pitch
"SAKSHI does not ask whether a document looks fake. It asks what the documents would have to say for every rule to hold, and when the answer is a different number, it shows you which number, where, and why no innocent explanation fits."
