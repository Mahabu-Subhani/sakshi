"""What SAKSHI can and cannot do, shown in the review console (the brief asks for implemented / partial / planned /
unsupported to be stated). Keep in step with docs/LIMITATIONS.md."""

CAPABILITIES = [
    ("Implemented", "Ingestion", "PDF (born-digital, scanned, searchable scans), JPG, PNG, TIFF, WEBP, BMP; several documents per case; password-locked PDFs with an analyst password kept in memory only"),
    ("Implemented", "Classification", "Salary slip, bank statement, application form, identity card, employment letter (keyword evidence); anything else is 'unknown' and gets extraction only, no conclusions"),
    ("Implemented", "OCR and extraction", "Printed English text with word confidence; fields with raw and normalised value, method and location; statement tables in four layouts across pages"),
    ("Implemented", "PDF structure", "Text hidden under shapes, overlay peel on scanned PDFs, earlier saved versions recovered and compared, font mix, hidden text and hidden instructions, metadata"),
    ("Implemented", "Pixel forensics", "Nine sensors on scans and photos: paper noise, copy-move, optics, glyphs, strokes, erasure, JPEG ghosts, scan clones, signatures; forgery canaries"),
    ("Implemented", "Contextual reasoning", "Arithmetic and balance rules, payroll rules, PAN and IFSC structure, cross-document values, counterfactual repair, income triangulation, deleted rows, cross-case memory"),
    ("Implemented", "Evidence", "Three rungs with verbal strength, devil's advocate, coverage map, interactive dossier 7.1-7.6, hash-chained audit trail"),
    ("Implemented", "Bank's own record (L4)", "Account Aggregator FI data for a deposit account (ReBIT schema, XML or JSON) supplied as a file: every statement row reconciled against it, so a regenerated statement is caught. SAKSHI is not an FIU and does not fetch from the AA network"),
    ("Implemented", "Digital signatures", "Signed PDFs checked offline: a broken signature or content added after signing is reported; issuer-signed (L3) only when the certificate chains to a trust store the lender configures. Revocation not checked"),
    ("Implemented", "Integration", "Batch mode over a folder of applications and a REST API (POST /v1/cases, bearer token), several isolated worker processes side by side"),
    ("Implemented", "Reproducibility", "Exact library versions locked; every dossier records the OCR engine and library versions and warns when the OCR engine differs from the calibrated one"),
    ("Partial", "Signatures", "Blue ink anywhere except inside printed words (coloured letterheads); pasted signature images in born-digital PDFs, flagged when added in a later save; black ink only above a readable signature caption; no comparison with a reference specimen"),
    ("Partial", "Long statements", "Up to 40 pages read for arithmetic and structure; pixel forensics on the first 6 pages"),
    ("Partial", "Single real images", "Measured on 988 public receipts, 199 real business forms and 600 real document images: pixel sensors flag forged and genuine alike; none of 1,324 genuine documents reached potential manipulation"),
    ("Partial", "Phone photos", "Read and checked logically; ink sensors limited; rotation is corrected, perspective is not"),
    ("Partial", "Hindi", "Tesseract eng+hin selectable; not evaluated on a Hindi dataset"),
    ("Partial", "LLM narrator", "Optional, off by default; rewrites the summary from findings, every sentence must cite a real finding or it is discarded"),
    ("Planned", "Trained pixel model", "A tamper-detection model trained on licensed data and judged once on unseen images; the current pixel sensors do not separate forged from genuine on real receipts or real document images"),
    ("Planned", "Large-region copy-move", "Logos, stamps, whole rows"),
    ("Planned", "Live issuer connections", "Fetching AA data as a registered FIU, UIDAI and PAN verification, revocation checks for signatures"),
    ("Unsupported", "Handwriting", "Handwritten fields are reported as not read, never as clean"),
    ("Unsupported", "Office files", "DOCX, XLSX and similar are rejected with a reason"),
    ("Unsupported", "Stamps and seals", "Not analysed"),
]
