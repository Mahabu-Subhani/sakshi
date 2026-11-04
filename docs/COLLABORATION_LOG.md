# Claude x Gemini design log

How SAKSHI was designed: three rounds of back-and-forth between Claude (Anthropic, Opus 5.5) and Gemini (Google, gemini-2.5-pro, called through Composio). Each side proposed ideas, attacked the other's, and asked questions. Gemini's replies are condensed for length; the benign-explanation catalog it wrote is reproduced in full in `sakshi/reasoning/benign_catalog.json` (lightly extended by Claude while wiring it into code).

---

## Round 1: independent ideas (no anchoring)

Claude briefed Gemini on the full problem statement and judging weights, deliberately without sharing its own ideas, and asked for 5 original ideas, the biggest trap, and questions.

**Gemini proposed**
1. **Glyph-level clustering.** Crop every character, embed it, cluster per character class with DBSCAN. One class splitting into two clusters means some glyphs were inserted.
2. **Layout structure hashing.** Perceptual hash of the block layout, compared against known-good templates for that issuer.
3. **Relational claim graph.** Entities and attributes as nodes; every attribute edge carries its source document and bbox. Inconsistency = explicit graph query, so every finding points at two exact source locations.
4. **Generative counterfactual verification.** From fact A (net pay on the slip) the LLM predicts the expected fact B' (what the salary credit row should look like), then we search the statement for B'.
5. **Block noise statistics beyond ELA.** Per-block noise variance and histogram shape, Isolation Forest to find blocks whose noise profile disagrees with neighbours.

**Biggest trap (Gemini):** one end-to-end model that outputs a single "forgery score". Unexplainable, overfits to known forgeries. Build independent sensors, fuse them into an evidence report.

**Gemini's questions for Claude**
1. Labeled forgery data, or unsupervised against assumed-good baselines?
2. Real-time API or analyst workflow?
3. Born-digital PDFs, flatbed scans or phone photos?
4. What does a flag trigger, auto-block or a human queue?

## Round 2: Claude answers, critiques, pitches

**Claude's answers:** no labeled data and judges upload unseen docs, so invariant-based and unsupervised; our synthetic set is only for validation. Analyst workflow, under 60s per case on CPU. All three modalities: digital PDFs get an extra object-layer branch, scans get pixel forensics, phone photos get deskew and an honest reduced-capability note. Flags always route to a human; never auto-block; precision-biased.

**Claude's critique of Gemini's ideas**
- Glyph clustering: right target, wrong features. Raw pixels + DBSCAN over-splits on scan noise and Tesseract char boxes jitter. Restrict to digits (amounts and dates are what forgers touch) and use cheap features: stroke width, ink darkness, height vs line-mates, baseline offset, edge sharpness.
- Template hashing: dead on arrival live, since there is no reference library for whatever bank the judges bring. Flip it to intra-document self-consistency: a forged row breaks the document's own rhythm (column alignment, row pitch).
- Claim graph: agreed, it becomes the spine.
- LLM counterfactuals: non-determinism is a liability in a traceability-judged contest. The LLM may only propose; deterministic code verifies; every proposal is logged.

**Claude's ideas**
- **A. Document as a program + minimal counterfactual repair.** Every document type carries arithmetic and logical invariants (gross = sum of earnings, net = gross - deductions, running-balance chain, payslip net == salary credit, etc). When invariants break, solve a model-based diagnosis problem (Reiter-style hitting sets): the minimum-cost set of fields whose change restores every invariant. Cost is weighted by OCR confidence so OCR errors get blamed first. This localizes the tampered field even when it looks visually perfect, and reconstructs the likely original value.
- **B. Corroboration fusion.** Escalate when independent evidence lines (visual, logical, file-structure) agree on the same field.
- **C. Forgery canaries.** Plant synthetic tampers into each uploaded document's own clean regions in memory and check the sensor catches them, giving per-document calibrated sensitivity and an honest "this sensor is blind on this document".
- **D. Devil's advocate pass.** Every finding must face benign explanations (OCR misread, rounding, transliteration, timing). Epistemic ladder: OBSERVATION -> INCONSISTENCY -> POTENTIAL MANIPULATION. Never "fraud".
- **E. PDF layer archaeology.** The classic edit is a white rectangle over the old value with new text on top; the text layer then holds both values, so the pre-edit value can be recovered from the file itself.

**Gemini's response**
- Accepted the glyph, layout and LLM-as-proposer changes.
- On B: don't make it a binary gate. A single smoking gun (layer archaeology) must surface uncorroborated, but 2+ independent lines should scream louder. **Adopted** as severity scoring.
- On the repair solver: skip ILP/Z3, brute-force subsets of size 1 to 3 over linear invariants, use non-linear rules as binary checks only. **Adopted.**
- **Attacked C hard:** (1) "clean regions" may not match the field's background, (2) naive canaries are trivially detectable and give false confidence, (3) canaries only test pixel sensors, not the reasoning layer.
- Proposed the demo storyline (income inflation 68,500 -> 86,500) and endorsed the name SAKSHI (Hindi/Sanskrit for "witness").

## Round 3: Claude pushes back, Gemini red-teams

**Claude's fixes to C**
- Canaries become **same-source copy-move**: copy real glyphs from the same page into a nearby row, which is what real forgers do, so texture and compression match by construction.
- Add **logic canaries** = mutation testing of the reasoning layer: perturb each critical field in memory and check whether the invariant engine detects and localizes it. Output a **verification coverage map**: fields anchored by 2+ invariants (strong), 1 (weak), 0 (blind, disclosed to the analyst).

**Claude found a bug in Gemini's demo plan:** with declared income 86,500, slip net 86,500, bank credit 68,500, the minimal repair is a tie. Fix: the bank credit sits inside the running-balance chain, so changing it breaks more invariants (anchoring breaks the tie), and the application value is a self-declaration (a claim), not a witness.

**Gemini's counter-attacks (most adopted)**
- Coverage map could reveal blind spots to forgers. **Response:** it is shown only inside the analyst dossier, never to applicants.
- Single-field mutation misses coordinated forgeries (change basic + HRA + gross + net consistently). **Adopted:** SAKSHI also runs named coordinated-attack simulations (internally-consistent payslip inflation, regenerated balance chain) and reports which cross-document invariant still catches each.
- The running-balance anchor is not absolute: a forger can regenerate the whole column. **Adopted:** recurring-transaction consistency (the same EMI in other months) and cross-document anchors are what catch a regenerated chain.
- Claim vs witness is too binary. **Adopted** as a 5-level witness reliability scale: L0 self-declared claim, L1 weak witness (scanned letter), L2 standard witness (statement, payslip, ID), L3 digitally signed source, L4 direct API fetch (e.g. Account Aggregator). Diagnosis cost scales with level.
- **False-positive red team** (all guards implemented or disclosed):
  - glyph outliers on dot-matrix print -> compare each glyph only to its own document's population.
  - layout rhythm on skewed scans and multi-line rows -> robust line fit instead of fixed x positions, tolerance band.
  - noise sensor on creases, stains, stamps -> ignore saturated and coloured-ink blocks, require rectangular compact regions.
  - PDF archaeology on SAP/Oracle template overlays -> only flag when a *value-like* token is occluded by a filled shape and a *different* value is drawn on top.
  - identical signatures on born-digital docs from the same issuer are normal -> only flag identity when at least one copy is a scan (a "wet" signature).
- Wrote the **benign-explanation catalog** with a deterministic test for each explanation (11 check types). Wired into `sakshi/reasoning/devils_advocate.py`.

**One change Gemini's red team forced on the demo dataset:** the forged employer letter was originally a digital PDF reusing the payslip signature. Gemini pointed out that is normal for digital docs from one issuer. The letter is now a *scanned* letter whose "wet" signature is pixel-identical in shape to the slip's, which is the actual suspicious case.

## Round 4: independent review

After the build, Gemini was given SAKSHI's output for the tampered case (without the ground-truth manifest) and asked to audit it as an independent reviewer. From the findings alone it reconstructed both deceptions correctly (income inflation 68,500 -> 86,500, hidden EMI 24,500 -> 14,500). It then pushed on four points; Claude accepted three (document assessments out of the counts, weak sensors can only support, findings grouped by hypothesis) and rejected one (escalating the identical signature, because a printed stored signature image is a real innocent explanation). Details in `docs/INDEPENDENT_REVIEW.md`.

---

## What came out of it

| Idea | Origin | Final form in SAKSHI |
|---|---|---|
| Claim graph with bbox provenance | Gemini | `reasoning/claims.py` |
| Minimal counterfactual repair | Claude | `reasoning/repair.py` |
| Witness reliability levels L0-L4 | Gemini | diagnosis cost weights |
| Digit-glyph typography outliers | Gemini, reworked by Claude | `forensics/glyphs.py` |
| Layout self-consistency | Gemini, flipped by Claude | `forensics/layout.py` |
| Block noise inconsistency | Gemini | `forensics/noise.py` |
| PDF layer archaeology | Claude | `forensics/pdf_layers.py` |
| Same-source copy-move canaries | Claude, hardened after Gemini's attack | `reasoning/selftest.py` |
| Verification coverage map + coordinated attacks | Claude + Gemini | `reasoning/coverage.py` |
| Severity scoring instead of binary gate | Gemini | `reasoning/fusion.py` |
| Benign-explanation catalog | Gemini | `reasoning/benign_catalog.json` |
| LLM as proposer only | Claude | `reasoning/narrator.py` (optional, off by default) |

---

# v1.0: second build with Gemini 4 Argon

v0.9 above was designed with gemini-2.5-pro. For v1.0 Claude worked with **Gemini 4 Argon** (`gemini-4-argon`, through Composio) in four more rounds. Rule agreed at the start: Argon designs attacks blind (without seeing SAKSHI's thresholds), both sides write code, every module written by one side is reviewed by the other, and nothing ships unless the original regression still passes.

## Round 1 (Argon): blind red team
Argon wrote five attack briefs aimed at v0.9's weak spots without seeing the code, plus a genuine trap: RT1 coordinated inflation (payslip math kept consistent, statement regenerated, declaration matched), RT2 a deleted EMI row in a Dr/Cr statement, RT3 a paint patch on a scanned letter saved at JPEG 70, RT4 a payslip cloned from another month's scan, RT5 a font-matched DOB edit on an ID card, RT6 a genuine two-page statement with C/F and B/F rows. Claude built them as `dataset/redteam/` without tuning and scored v0.9 honestly: **3 of 5 detected (1 at potential manipulation), 0 of 2 genuine controls clean.**

## Round 2 (Argon writes code, Claude reviews)
* `forensics/table_parser.py` (Argon): constraint-guided statement parser. Column-layout hypotheses (debit/credit/balance, credit/debit/balance, amount + Dr/Cr, signed amount) are chosen by how many balance transitions they make true. Claude's review found a bug that dropped every single-token credit (every salary row lost its credit), an "Opening Balance" line in a closing summary restarting the chain, and page footers glued to narrations. Fixed, marked `REVIEW FIX` in the file.
* `forensics/compression.py` (Argon): JPEG ghosts per value box and zero-variance patches (erased paper has no scanner grain). Argon's own self-test failed: the inner region was box + padding, so a small flat patch mixed with grainy paper. Claude redesigned the measurement (inner = box only, ring outside the pad, robust MAD of the median-filter residual).
* Argon's guards adopted: pixel statistics (noise, copy-move, zero variance, JPEG ghosts, scan clones) count as **one** witness because one paste moves them all; OCR self-healing may **re-read, never rewrite**, and the second reader sees only the crop, never the expected value; signatures in the registry are stored as stroke-density grids, not DCT hashes; reconstruction images must be labelled "not evidence".
* Claude added: income triangulation with witness impeachment, statutory payroll rules (PF, Karnataka PT), deleted-row structural repair, intra-token stroke consistency, scanner-optics edge sharpness, scan-clone detection by paper-grain correlation, cross-case registry, expected-value reconstruction images.

## Round 3 (Argon reviews v1.0)
Scores at that point: red team 5 of 5 detected (3 at potential manipulation), genuine 3 of 3 clean. Argon attacked:
| Argon's point | Response |
|---|---|
| PF is capped at 1,800; a genuine capped PF would impeach an honest payslip | Already handled (1,800 accepted). Rule made one-directional: only PF **below** 12% of basic contradicts; VPF passes; LOP/arrears wording makes it plausible. |
| One forged 3-month statement can outvote an honest letter (Sybil) | Agreed. One document adds at most 2.0 to one value, and a value carried by a self-contradicting document can never win outright. |
| Taint every document that agrees with an impeached one | **Rejected**: it punishes honest documents for agreeing with a document that has an unrelated fault. Replaced by *confession witnesses*: the part of a self-contradicting document that exposes the contradiction (PF actually deducted) keeps full weight. |
| Mixed-raster PDFs and scanner-app enhancement fire optics + pixel together | Agreed. Optics vetoed on a page when > 8% of words or > 5 values are "sharper than the page". |
| WhatsApp-forwarded photos alias thin strokes | Agreed. Ink sensors go blind below 16 px digit height; unread fields become "could not be read", never "missing". New genuine case G10. |
| Re-running a case with memory on looks like an identity ring | Agreed. Same applicant + same files = duplicate-submission observation; Reset button in the UI. New genuine case G11. |
| Verdict | Conditional go after the patches. |

While testing Argon's MRC warning, Claude found a larger hole: a scanned PDF with under 15 words of text was analysed through its embedded image, and a searchable scan (invisible OCR layer) was treated as born-digital. So the commonest real edit, a white box and a new number typed over a scanned payslip in a PDF editor, was invisible: SAKSHI analysed the untouched scan and reported the original value. Fix: **overlay peel** (`forensics/scan_overlay.py`). New case RT8.

## Round 4 (Argon attacks the overlay peel)
| Argon's point | Response |
|---|---|
| Edits hidden in Form XObjects or annotations escape an object list | Agreed. Rendered page vs embedded scan are now compared pixel by pixel; anything that changes pixels is an overlay. New case RT9 (FreeText comment over a salary credit). |
| A redaction ("XXXXXX821Q" over a PAN) would read as a replaced number | Agreed. Masking characters or a dark box with nothing on top = redaction observation; masked identifiers never enter format or cross-document checks; a smoking gun needs both sides to be numbers. Pixel sensors on a documented redaction or stamp are explained by it. New genuine case G12. |
| Hidden "ink" may be logo shading or a rule line | Agreed. Hidden ink must form character-sized blobs. |
| Flattened white patch, Acrobat inpainting | Already covered by the zero-variance and noise sensors and by `overlay_on_value`. |
| Verdict | **GO.** |

## Final check (Argon attacks two changes made after its GO)
| Change | Argon | Outcome |
|---|---|---|
| Cross-case memory: whoever held an identifier first owns it (found by running every demo into one memory: after the ring case, the genuine applicant's own re-run was flagged for photo reuse) | Fine for the demo; in production "first seen = genuine" can be gamed by a ring that registers stolen material first | Kept; the production caveat is in `LIMITATIONS.md`, and the dossier always names the earlier case |
| Unseen statement layouts: statement arithmetic cannot escalate below 80% balance fit | "Massive hole": smudge a few small rows to drag the fit down and blind the math on the one fake credit; and never let the gate touch pixel or file-structure evidence | Scope was already row-math only. The attack was built as **RT10** and **it partly worked**: with smudged balance cells the parser took the row's amount as its balance, so the rows looked confidently read but broken. Fixed: fit counts only confidently read rows; a balance cell outside the balance column is moved to its real column or dropped; rows without a printed balance are bridged into the next check instead of restarting the chain; a low fit is never silent (`statement_unverified` tells the analyst to fetch the statement from the bank). RT10 is now detected and localized. |

## Who wrote what in v1.0
| Module | Author | Reviewed by |
|---|---|---|
| `forensics/table_parser.py` | Argon | Claude (3 bugs fixed) |
| `forensics/compression.py` | Argon | Claude (measurement redesigned) |
| `forensics/raster.py` (stroke, optics, scan clones), `forensics/scan_overlay.py`, `registry.py`, triangulation, statutory rules, deleted-row repair | Claude | Argon (rounds 3 and 4) |
| Red-team briefs RT1-RT6, G10-G12, RT9, RT10 | Argon | built by Claude |
| RT7, RT8, G7-G9 | Claude | |
