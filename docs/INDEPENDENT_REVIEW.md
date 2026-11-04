# Independent review by Gemini (round 4)

After the build, Gemini (gemini-2.5-pro) received SAKSHI's machine summary of the tampered demo case, without the ground-truth manifest, and was asked to audit it as a skeptical reviewer. Condensed below, with what changed as a result.

## What Gemini concluded from the output alone
> Two deceptions: income inflated from 68,500 to 86,500 by digitally altering the payslip, with an employer letter made to match; and an existing EMI hidden by reducing it from 24,500 to 14,500 on the scanned bank statement with pixel-level editing.

This matches the ground truth, reached only from SAKSHI's findings.

## Critiques and responses

| Gemini's critique | Response | Change |
|---|---|---|
| Document assessments (F021-F023) are summaries of findings; counting them as POTENTIAL MANIPULATION inflates the count and is circular. | Agreed. | Moved to a separate `document_assessments` section; tier counts exclude them. |
| A 7 px alignment shift (F008) is weak and should not be a potential-manipulation finding by itself. | Agreed in principle. | Weak sensors (layout, typography) can now only *support*; the lead finding on a field must be strong (repair solver, smoking gun, or confidence >= 0.8). Counts went from 11 to 6 potential-manipulation findings on the demo case. |
| The identical signature (F010, similarity 0.87) is a smoking gun and should be escalated. | **Disagreed.** An issuer can legitimately print a letter carrying a stored signature image; the scan then matches the digital copy. That cannot be ruled out from pixels. | Added "printed stored signature image" as an innocent explanation (not testable). Finding stays INCONSISTENCY; the letter as a whole is flagged through its document assessment (3 independent anomalies). |
| A flat finding list forces the analyst to connect the dots; group findings under hypotheses. | Agreed. | The investigation rail is now grouped by hypothesis (diagnosis threads), then document assessments, then other observations. |

## Judge questions Gemini anticipated, with answers

**"Isn't this two edits counted many times?"** Counts are per finding, but escalation is per evidence family: the payslip net pay is supported by file structure (hidden original value), typography (font) and arithmetic plus bank records. Each family can fail independently; together they converge.

**"Is the solver just copying the PDF result?"** No. The repair solver sees only extracted numbers and rules; it never reads PDF objects. The archaeology module reads the content stream of one file. They agree on 68,500.00 independently.

**"How do you separate manipulation from a messy scan?"** By specificity against the document's own baseline: the paper around one value is cleaner than around every other value; its digits deviate from every other number on the page. Messiness is global; these are local.

---

# v1.0: reviews by Gemini 4 Argon (rounds 3 and 4)

Argon reviewed v1.0 twice after writing the blind red team and two of the modules. It was shown the honest scores (including the v0.9 baseline of 3 of 5 detected and 0 of 2 genuine controls clean) and the key logic, and asked to find failure modes.

**Round 3 verdict: conditional go.** Accepted: per-document weight cap in income triangulation, optics veto on bimodal pages, ink sensors blind on small images, duplicate-submission handling and a memory reset. Already handled: the PF 1,800 cap. Rejected: tainting every document that agrees with a self-contradicting one (replaced by confession witnesses). Full table in `docs/COLLABORATION_LOG.md`.

**Round 4 verdict: GO,** after two patches that were then built and tested: pixel-level overlay comparison (catches annotations and nested objects; case RT9) and a redaction guard (case G12).

What Argon praised, in its words: "The overlay peel is a massive catch. Reading the raw embedded image while ignoring the rendered canvas is the #1 bug in PDF forensics." and "your confession witness + impeached group cannot win logic is cleaner and immune to collateral damage."

One attack Argon raised that we judged already covered (flattened white patches): Argon assumed the optics sensor only flags high values; the separate erasure-patch sensor (Argon's own `compression.py`) and the noise sensor flag paper that is too clean.
