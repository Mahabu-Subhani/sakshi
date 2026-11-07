"""Core data structures. Every value SAKSHI reasons about keeps a pointer back to
its source: document id, page number and pixel bounding box."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any, Optional

BBox = tuple  # (x0, y0, x1, y1) in page pixels at the analysis DPI


class Tier(str, Enum):
    """Epistemic ladder. SAKSHI never outputs 'fraud'."""
    OBSERVATION = "OBSERVATION"                    # a sensor reading, no rule broken
    INCONSISTENCY = "INCONSISTENCY"                # a rule broke or an anomaly is localized
    POTENTIAL_MANIPULATION = "POTENTIAL_MANIPULATION"  # corroborated + benign explanations ruled out


class Witness(int, Enum):
    """Witness reliability level of a source document."""
    L0_CLAIM = 0          # self-declared by the applicant (application form)
    L1_WEAK = 1           # scanned, unverifiable issuer document (letter)
    L2_STANDARD = 2       # statement, payslip, identity card
    L3_SIGNED = 3         # digitally signed by a trusted issuer (not verified in prototype)
    L4_API = 4            # fetched directly from source (e.g. Account Aggregator), out of scope


WITNESS_COST = {0: 0.6, 1: 1.0, 2: 2.0, 3: 4.0, 4: 8.0}


@dataclass
class Word:
    text: str
    bbox: BBox
    conf: float            # 0..1
    line_id: int = -1
    font: str = ""         # only for born-digital text
    size: float = 0.0
    source: str = "ocr"    # "ocr" | "pdf_text"


@dataclass
class Line:
    id: int
    words: list
    bbox: BBox

    @property
    def text(self) -> str:
        return " ".join(w.text for w in self.words)


@dataclass
class Page:
    index: int
    image_path: str
    width: int
    height: int
    words: list = field(default_factory=list)
    lines: list = field(default_factory=list)
    skew_deg: float = 0.0
    noise_sigma: float = 0.0


@dataclass
class Document:
    doc_id: str
    filename: str
    path: str
    sha256: str
    modality: str                  # "digital_pdf" | "scanned_pdf" | "image"
    pages: list = field(default_factory=list)
    doc_type: str = "unknown"
    type_confidence: float = 0.0
    type_evidence: list = field(default_factory=list)
    witness: int = 2
    fields: dict = field(default_factory=dict)       # name -> Field
    tables: dict = field(default_factory=dict)       # name -> list[dict[col -> Field]]
    pdf_meta: dict = field(default_factory=dict)
    structure: dict = field(default_factory=dict)
    capabilities: dict = field(default_factory=dict)  # sensor -> "ok"/"n/a"/"blind"/reason
    notes: list = field(default_factory=list)


@dataclass
class Field:
    name: str
    raw: str
    value: Any                     # normalized (float, ISO date string, uppercase name...)
    kind: str                      # "amount" | "date" | "text" | "id" | "name" | "int"
    doc_id: str
    page: int
    bbox: BBox
    conf: float
    method: str                    # how it was extracted
    label_bbox: Optional[BBox] = None
    ref: str = ""                  # stable id e.g. D2.row7.debit

    def key(self) -> str:
        return self.ref or f"{self.doc_id}.{self.name}"


@dataclass
class Evidence:
    doc_id: str
    page: int
    bbox: BBox
    note: str
    kind: str = "region"           # "region" | "field" | "file" | "crop"
    crop: str = ""                 # path to an evidence image (optional)
    value: str = ""


@dataclass
class BenignTest:
    explanation: str
    test: str
    result: str                    # "ruled_out" | "plausible" | "not_testable"
    detail: str = ""


@dataclass
class Finding:
    id: str
    check: str                     # check type, e.g. "arithmetic_break"
    family: str                    # "visual" | "logical" | "file_structure" | "cross_document" | "identity"
    title: str
    detail: str
    tier: Tier = Tier.OBSERVATION
    confidence: float = 0.5
    severity: int = 0
    evidence: list = field(default_factory=list)
    fields: list = field(default_factory=list)   # field keys involved
    docs: list = field(default_factory=list)
    benign: list = field(default_factory=list)
    repair: dict = field(default_factory=dict)
    corroborated_by: list = field(default_factory=list)
    sensor: str = ""
    localized: bool = False
    smoking_gun: bool = False
    verify_next: str = ""

    def strength(self) -> str:
        """Verbal strength of evidence for manipulation, the way forensic reports state it (not a fraud percentage)."""
        if self.tier == Tier.POTENTIAL_MANIPULATION:
            return "strong support"
        if self.tier == Tier.INCONSISTENCY:
            return "moderate support" if self.confidence >= 0.75 else "weak support"
        return "explained, no support"

    def to_dict(self) -> dict:
        d = asdict(self)
        d["tier"] = self.tier.value
        d["strength"] = self.strength()
        return d
