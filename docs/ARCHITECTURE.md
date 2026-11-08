# SAKSHI architecture

## Data flow

```mermaid
flowchart TB
  subgraph IN["1 Submission"]
    U["Uploads: PDF / JPG / PNG / TIFF<br/>(several documents, one application)"]
    H["SHA-256 per file<br/>audit: case_opened, document_ingested"]
  end
  subgraph PER["Per document"]
    M{"Modality?"}
    DP["Born-digital PDF<br/>text layer + fonts (PyMuPDF)<br/>+ rendered page"]
    SP["Scanned / searchable PDF<br/>embedded scan, native resolution<br/>+ rendered page if anything is drawn on top"]
    PEEL["Overlay peel<br/>rendered vs embedded scan<br/>objects + pixel diff"]
    IM["Image<br/>deskew copy if skew > 1 deg"]
    ARC["PDF layer archaeology<br/>occluded text, font mix,<br/>incremental updates, metadata"]
    OCR["OCR (Tesseract 5, eng/hin)<br/>word boxes + confidence<br/>dual read for digital PDFs"]
    CLS["2 Classification<br/>keyword evidence scorer<br/>+ witness level L0-L4"]
    EXT["3/4 Extraction + structure<br/>label-anchored fields, table by header alignment,<br/>amount-in-words parser, required/missing/duplicate"]
    VIS["5 Visual forensics<br/>pixel: noise, copy-move, erasure, JPEG ghosts<br/>optics: edge sharpness<br/>typography: digit outliers, intra-number strokes<br/>geometry: layout rhythm, signature placement"]
    CAN["Forgery canaries<br/>self-test each pixel sensor<br/>on this document's own pixels"]
  end
  subgraph CASE["Case level"]
    INV["6/7 Invariant library<br/>intra-doc arithmetic, balance chain, totals,<br/>recurring obligations, cross-doc links,<br/>equality groups, formats, expectations"]
    REP["Counterfactual repair solver<br/>minimal-cost field changes (k<=3)<br/>+ odd-one-out over witness weights"]
    SIG["Cross-document signature identity<br/>+ scan clones (paper-grain correlation)"]
    TRI["Income triangulation<br/>witness impeachment, confession witnesses"]
    REG[("Cross-case memory<br/>registry.json")]
    DA["Devil's advocate<br/>benign catalog, deterministic tests"]
    FUS["8 Fusion + epistemic ladder<br/>independent evidence families per field<br/>severity score, hypotheses (threads)"]
    COV["Coverage map<br/>mutation testing + coordinated attacks"]
  end
  subgraph OUT["9/10 Evidence + dossier"]
    EV["Evidence crops, heatmaps,<br/>bbox in original pixels"]
    DOS["dossier.json + interactive dossier.html<br/>sections 7.1-7.6, coverage, audit"]
    LLM["Optional LLM narrator<br/>(Gemini / Claude, off by default,<br/>rewrites summary only)"]
  end
  AUD[("Hash-chained audit trail<br/>audit.jsonl")]

  U --> H --> M
  M -->|digital| DP --> ARC --> OCR
  M -->|scanned pdf| SP --> OCR
  SP --> PEEL --> FUS
  M -->|image| IM --> OCR
  OCR --> CLS --> EXT --> VIS --> CAN
  EXT --> INV
  VIS --> FUS
  ARC --> FUS
  INV --> REP --> FUS
  INV --> TRI --> FUS
  EXT --> REG --> FUS
  VIS --> SIG --> FUS
  FUS --> DA --> FUS
  FUS --> COV
  FUS --> EV --> DOS
  COV --> DOS
  DOS -.-> LLM
  H -.-> AUD
  CLS -.-> AUD
  EXT -.-> AUD
  VIS -.-> AUD
  FUS -.-> AUD
  DOS -.-> AUD
```

## Modules

| Stage of the brief | Module | Technology | Role |
|---|---|---|---|
| Document submission | `ingest.py`, `audit.py` | PyMuPDF, Pillow, hashlib | hashing, modality detection, native-resolution rasters, deskew, chain of custody |
| Classification | `classify.py` | keyword evidence scorer | type + confidence + cues, witness level |
| OCR & extraction | `ingest.py`, `extract.py` | Tesseract 5 (LSTM), PDF text layer | word boxes + confidence, label-anchored fields, table parsing, number-words parser |
| Structural understanding | `extract.py` | layout geometry | sections, required/missing/duplicate fields, label-value relations, row/column structure |
| Visual forensics | `forensics/*.py` | OpenCV, scikit-image, NumPy | noise consistency, copy-move, typography, layout rhythm, signatures, PDF archaeology; v1.0: `compression.py`, `raster.py` (stroke, optics, scan clones), `scan_overlay.py` (overlay peel), `table_parser.py` |
| Cross-case memory | `registry.py` | pHash, SHA-256, stroke grids | identity rings across applications; a shared identity is contested on both sides until the bank's record settles it (v1.1) |
| Bank's own record (v1.1) | `issuer.py` | ReBIT deposit schema (XML/JSON) | Account Aggregator FI data supplied by the lender, an L4 witness reconciled row by row with the statement |
| Signed PDFs (v1.1) | `forensics/pdf_signature.py` | pyHanko | integrity, content added after signing, issuer-signed (L3) only through `SAKSHI_TRUST_DIR` |
| Batch and REST API (v1.1) | `service.py`, `cli.py` | Starlette, Uvicorn, multiprocessing | isolated worker per case with a hard timeout, bearer token, `sakshi batch` / `sakshi serve` |
| Contextual verification | `reasoning/invariants.py`, `engine.py` | rule library | arithmetic, balance chain, totals, formats (PAN/IFSC), dates, expectations |
| Cross-document correlation | `invariants.py`, `repair.py` | linear algebra, entity matching | cross-doc numeric links, equality groups with transliteration and OCR-confusion handling |
| Anomaly investigation | `repair.py`, `devils_advocate.py`, `fusion.py` | model-based diagnosis, deterministic tests | minimal repairs, innocent explanations, tiering, hypotheses |
| Evidence generation | `pipeline.py` | OpenCV | crops with boxes, heatmaps, page references |
| Investigation dossier | `dossier/render.py` | self-contained HTML + JSON | interactive traceability, coverage, audit |
| Self-assessment | `reasoning/coverage.py`, `selftest.py` | mutation testing, canaries | what the system can and cannot verify on this case |
| (optional) LLM | `reasoning/narrator.py` | Gemini / Claude API | plain-language restatement of the deterministic summary |

## Evidence model

```
Field   { name, raw, value, kind, doc_id, page, bbox(px), conf, method, ref }
Finding { id, check, family, tier, confidence, severity, evidence[], fields[], benign[], repair{}, corroborated_by[] }
Evidence{ doc_id, page, bbox(px), note, value, crop }
```

Evidence families used for corroboration (v1.0): `file_structure`, `pixel`, `optics`, `typography`, `geometry`, `signature`, `logical` (internal arithmetic), `cross_document` (external records), `identity`, `pattern`, `statutory`, `cross_case`. Pixel statistics count as one family because one paste moves them all. A field reaches POTENTIAL MANIPULATION only when two or more families converge on it (or a smoking gun such as recovered occluded text) **and** no innocent explanation remains plausible. Weak sensors (alignment, typography) can corroborate but never lead.

## Where the AI is, and where it deliberately is not

* Learned models: Tesseract's LSTM OCR. Statistical learning: robust z-scores, Theil-Sen fits, noise estimation, all per document (unsupervised, no training data needed, because judges bring unseen documents).
* Reasoning: deterministic model-based diagnosis, so every conclusion can be replayed and audited.
* LLMs: optional, and only to *rephrase* the final summary. Never to decide a tier, never on raw documents: the LLM proposes wording, deterministic code decides.
