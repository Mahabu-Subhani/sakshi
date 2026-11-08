# Limitations, assumptions and unsupported scenarios

## Capability status

| Capability | Status |
|---|---|
| Ingestion of PDF (digital and scanned), JPG, PNG, TIFF, WEBP, BMP; multiple documents per case | Implemented |
| Classification (salary slip, bank statement, application form, identity card, employment letter, unknown) | Implemented (keyword evidence) |
| Printed text OCR with word confidence; Hindi via `--lang eng+hin` | Implemented (Hindi not evaluated on our dataset) |
| Handwritten text recognition | **Unsupported** |
| Structured extraction with bbox traceability | Implemented for the five document types; generic label:value harvesting for others |
| PDF layer archaeology, font mix, invisible text, incremental updates | Implemented |
| Overlay peel on scanned PDFs (rendered page vs embedded scan; objects, annotations, nested XObjects) | Implemented (v1.0) |
| Searchable scans (invisible OCR layer) analysed as scans | Implemented (v1.0) |
| Statement parsing: debit/credit, credit/debit, amount + Dr/Cr, signed amount; multi-page with C/F and B/F | Implemented (v1.0, constraint-guided parser) |
| Erasure patches, JPEG ghosts, intra-number stroke consistency, scanner-optics edge sharpness | Implemented for scans and photos (v1.0); blind below 16 px digit height |
| Scan-clone detection between documents (paper-grain correlation after alignment) | Implemented (v1.0) |
| Statutory payroll rules (employee PF, Karnataka professional tax) | Implemented (v1.0); other states' PT not encoded |
| Income triangulation with witness impeachment | Implemented (v1.0) |
| Cross-case memory (photo pHash, identifiers, file hashes, signature grids) | Implemented (v1.0), local JSON on one machine; safe with several writers on that machine (v1.0.5); conflicts contested until the bank's record settles them, whatever the order (v1.1); not shared between machines |
| Noise consistency, copy-move on digits, digit typography, layout rhythm | Implemented for scans; declared not applicable on born-digital renders |
| Copy-move of large regions (logos, stamps, whole rows) | Planned |
| Signature detection and identity | Implemented for blue ink anywhere on the page; black ink **partial**: found only just above a readable signature caption (a signature drawn over its own caption is not found) |
| Earlier saved versions of an edited PDF (incremental saves) recovered and compared | Implemented (v1.0.3) |
| Hidden text addressed to automated reviewers (prompt injection); narrator output must cite real findings | Implemented (v1.0.3) |
| Signature verification against a reference specimen | **Unsupported** |
| Intra- and cross-document rules, counterfactual repair, odd-one-out | Implemented |
| Coverage map, coordinated attacks, forgery canaries | Implemented |
| Bank's own record: Account Aggregator FI data for a deposit account (ReBIT schema, XML or JSON) reconciled row by row with the statement | Implemented (v1.1) as a file the lender supplies; fetching it live as a registered FIU is **unsupported** |
| Digitally signed PDFs: broken signature, content added after signing, issuer-signed (L3) through a lender-configured trust store | Implemented (v1.1), offline; revocation **not checked**; no trust anchors ship with SAKSHI |
| Employer, UIDAI and PAN verification | **Unsupported** |
| Batch processing and REST API (several isolated worker processes) | Implemented (v1.1); single machine, in-memory job list (jobs are lost on restart; results stay on disk) |
| Multi-page documents | Up to 40 pages read per document; pixel forensics on the first 6 (v1.0.1) |
| Password-protected PDFs | Implemented with an analyst-supplied password, kept in memory only (v1.0.1) |
| Tampering inside a single real image (receipts, photographed or scanned documents) | **Poor, measured**: on 988 public receipts and 600 public document images (RTM) the pixel sensors flag forged and genuine at the same rate and box the edit rarely (17 of 300 on RTM); a learned layer on their outputs did not fix it; no genuine image in either set reached POTENTIAL MANIPULATION |
| Perspective correction for phone photos | Planned (only rotation deskew today); forwarded phone photos are read and checked logically, ink sensors report blind |

## Assumptions
* All documents in one upload belong to the same application and the same applicant.
* Amounts are in INR with Indian or Western digit grouping; dates are DD-MM-YYYY (day-month swaps are tested as an innocent explanation).
* Statements print a running balance column; payslips print gross, total deductions and net.
* The applicant is an individual (PAN 4th character P).

## Known false-positive risks
* **Glyph, intra-number stroke and noise sensors on low-resolution prints** (measured): on real thermal receipts these sensors raise INCONSISTENCY flags on more than half of genuine documents. On 199 real scanned business forms (FUNSD) the glyph sensor alone raised an INCONSISTENCY on 46; no genuine document in either dataset reached POTENTIAL MANIPULATION. The glyph sensor has no glyph-height gate yet (the stroke and optics sensors go blind below 16 and 18 px). A fix is designed (resolution-dependent gating that keeps red-team case RT5) but not applied, because it changes detection logic and needs evaluation on data we have not inspected.
* **Noise sensor**: stickers or photos physically pasted onto a card before scanning, laminated areas, strong JPEG re-compression of the whole page, stamps with solid ink fills.
* **Copy-move**: scanners or PDF producers using JBIG2 symbol coding make repeated glyphs identical (tested and reported as an innocent explanation); de-noising filters in phone scanner apps.
* **Typography**: genuinely mixed fonts in a form (pre-printed vs typed); faint carbon copies.
* **Layout rhythm**: values typed by hand or with a typewriter; multi-line narrations.
* **Signature identity**: letters printed with a stored signature image (reported as *not testable*, kept at INCONSISTENCY).
* **Repair solver**: when several fields are wrong at once (more than 3) or a row was not parsed, it reports "no unique explanation" instead of guessing.
* **Cross-document rules**: legitimate mid-month joining, arrears, salary revisions, EMI changes after a rate reset; partially covered by the innocent-explanation tests. Salary credits that differ only in *other* months are recorded as an observation (increment, LOP, variable pay).
* **Overlay peel**: an issuer that stamps or e-signs over printed text produces "hidden scan ink" (inconsistency, never a smoking gun unless a different number is typed over a number). Redactions are recognised by masking characters or a dark box.
* **Cross-case memory** (v1.1, "contested until verified"): when two different people's applications share an identifier, an ID photo, a signature or a file, the order in which they arrived decides nothing: the conflict is raised on the later application as CONTESTED (INCONSISTENCY) and a "contested by" notice is recorded against the earlier one, so a ring that registers a victim's identity first cannot get the victim flagged as the impostor. Only an issuer settles it: an identifier the bank's own record (Account Aggregator data) confirms for one applicant belongs to that applicant; the other application's use of it is then POTENTIAL MANIPULATION. Photos, signatures and identical files cannot be verified by an issuer offline and stay contested. Consequences: without issuer data, the identity-ring case RT7 is an INCONSISTENCY, not POTENTIAL MANIPULATION (it was in 1.0.x), and once a ring case is in memory the genuine applicant's later applications are contested too until verified. Two siblings sharing a joint account or a family mobile number are also contested (innocent explanation stated). Photo reuse needs the identical image, not the same face.
* **Smudged balance cells**: a balance cell outside the balance column is moved to its real column or dropped, and rows without a readable balance are bridged into the next check. A row whose *amount* cannot be read restarts the chain, so an edit on that exact row is checked only by the statement totals.
* **Unfamiliar statement layouts** (a real bank's format SAKSHI has never seen): if the balance equation holds on fewer than 80% of confidently read rows, row-math findings cannot escalate; below 60% they are explained as SAKSHI's own misreading. Pixel and file-structure findings are never affected, and a `statement_unverified` note tells the analyst to fetch the statement from the bank. An attacker who cleanly breaks the arithmetic of more than 40% of rows makes the statement unverifiable; SAKSHI says so instead of trusting it. The parse quality is printed in the dossier (section 7.2).
* **Optics**: pages rendered in two layers (mixed-raster PDFs, scanner-app text enhancement) veto the sensor for that page rather than risk a false flag.

## Known misses (measured)
* **Regenerated statement with no pixel trace**: one non-recurring row changed and every later balance regenerated (Forgery Lab recipe). Nothing inside the documents contradicts it; only the bank can. From the documents alone SAKSHI misses it on purpose rather than guessing, and the coverage map lists the field as blind. With the bank's Account Aggregator data attached it is caught (5 of 5 in `tests/run_issuer.py`).
* **Perfectly coordinated forgery**: payslip, statement and declaration inflated together with PF and every statutory figure recomputed. Income triangulation then sees a consistent majority. SAKSHI flags the honest document's disagreement but may not be able to say which side is true; it says so.
* **Single-digit edits inside a number**: the intra-number stroke sensor needs a run of 2+ adjacent digits; one replaced digit is left to the noise, compression and optics sensors.
* **Flattened PDF edits** ("print to PDF" after editing): the overlay peel has nothing to peel; detection falls back to the pixel sensors (erasure patch, noise, optics).
* **Name replaced under an overlay**: reported as inconsistency (hidden scan ink), not a smoking gun, because a stamp could also cover text.

## Bank's record and signatures: limits
* **Account Aggregator data** is read from a file. SAKSHI does not check the FIP's signature on the FI data or fetch it itself; a lender must pass on only data it received through the AA framework. Rows are matched on direction, amount and date (one day either side); narrations are not compared; a statement credit equal to two or three bank credits on the same day counts as a split. Only transactions inside both the bank data's period and the statement's period are compared. If the account number on the statement differs from the bank data, nothing is compared.
* **Statement read wrongly**: an OCR misread or an unparsed row would look like a disagreement with the bank. A disagreement on an amount read with OCR confidence below 0.60 stays at INCONSISTENCY (for a changed amount, only when the two values are also one character apart); a bank transaction missing from the statement stays at INCONSISTENCY when the statement was read with a balance-equation fit below 0.95 or has unreadable rows.
* **Digital signatures**: a valid signature from an unknown certificate adds no weight. Encrypted signed PDFs are checked only when a working password is supplied. Annotations added after signing (a stamp, a comment) stay at INCONSISTENCY.
* **Batch mode and the API**: each case is checked against cross-case memory when it starts, so two applications running at the same moment cannot see each other (use one worker when order matters). The API has no TLS of its own; it refuses to listen beyond localhost without a bearer token, and belongs behind the lender's reverse proxy.

## Thresholds
All thresholds were set on synthetic data generated for this hackathon and are listed in `docs/TECHNICAL.md`. They must be recalibrated on authorised real samples before any production use.

## Safety and ethics commitments
* Synthetic or authorised documents only; the demo dataset uses invented institutions and carries visible SYNTHETIC SPECIMEN labels.
* No output says "fraud". POTENTIAL MANIPULATION means "independent evidence converges; a human must decide".
* OCR is a witness with a confidence, never ground truth; low-confidence reads are blamed first.
* The coverage map reveals verification blind spots and is meant for analysts only, never for applicants.
* Document images stay on the machine running SAKSHI. The optional LLM narrator receives only finding titles and tiers, never document images or raw text, and is off by default.
* Every processing step and finding is written to a tamper-evident audit log.
