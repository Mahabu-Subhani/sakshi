"""Document classification with an explanation of why.

A transparent keyword-evidence scorer: every type has weighted cues, the score
and the matched cues are kept so the dossier can say *why* a document was
classified the way it was. Below a margin it says 'unknown' rather than guess.
"""
from __future__ import annotations

import re

from .models import Document, Witness

CUES = {
    "salary_slip": [("payslip", 3), ("pay slip", 3), ("salary slip", 3), ("net pay", 3), ("gross earnings", 2),
                    ("total deductions", 2), ("provident fund", 1), ("employee id", 1), ("earnings", 1)],
    "bank_statement": [("statement of account", 3), ("account statement", 3), ("opening balance", 2),
                       ("closing balance", 2), ("withdrawal", 1), ("deposit", 1), ("debit", 1), ("credit", 1),
                       ("balance", 1), ("ifsc", 1)],
    "application_form": [("application form", 3), ("loan amount requested", 2), ("applicant", 2),
                         ("signature of applicant", 2), ("declaration", 1), ("loan tenure", 1)],
    "identity_card": [("identity card", 3), ("id no", 2), ("valid till", 2), ("date of birth", 1), ("issued", 1),
                      ("dob", 1)],
    "employment_letter": [("to whom it may concern", 3), ("certify that", 2), ("working with", 1),
                          ("employee id", 1), ("monthly salary", 1), ("authorised signatory", 1)],
}

WITNESS_BY_TYPE = {
    "application_form": Witness.L0_CLAIM,
    "employment_letter": Witness.L1_WEAK,
    "salary_slip": Witness.L2_STANDARD,
    "bank_statement": Witness.L2_STANDARD,
    "identity_card": Witness.L2_STANDARD,
    "unknown": Witness.L1_WEAK,
}

LABELS = {
    "salary_slip": "Salary slip",
    "bank_statement": "Bank statement",
    "application_form": "Loan application form",
    "identity_card": "Identity card",
    "employment_letter": "Employment letter",
    "unknown": "Unclassified document",
}


def classify(doc: Document) -> None:
    text = " ".join(w.text for p in doc.pages for w in p.words if w.conf >= 0.3).lower()
    text = re.sub(r"\s+", " ", text)
    scores = {}
    hits = {}
    for t, cues in CUES.items():
        s, h = 0, []
        for cue, wt in cues:
            if cue in text:
                s += wt
                h.append(cue)
        scores[t], hits[t] = s, h
    ranked = sorted(scores.items(), key=lambda kv: -kv[1])
    (best, s1), (_, s2) = ranked[0], ranked[1]
    if s1 < 3 or s1 - s2 < 2:
        doc.doc_type = "unknown"
        doc.type_confidence = 0.0 if s1 == 0 else round(min(0.5, s1 / (s1 + s2 + 1e-9) * 0.6), 2)
        doc.type_evidence = [f"top candidate {best} scored {s1} vs {ranked[1][0]} {s2}: margin too small"]
    else:
        doc.doc_type = best
        doc.type_confidence = round(min(0.99, 0.5 + 0.5 * (s1 - s2) / (s1 + 1e-9)), 2)
        doc.type_evidence = hits[best]
    w = WITNESS_BY_TYPE[doc.doc_type]
    if doc.doc_type == "employment_letter" and doc.modality == "digital_pdf":
        w = Witness.L2_STANDARD
    doc.witness = int(w)
