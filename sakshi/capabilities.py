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
    ("Partial", "Signatures", "Blue ink anywhere on the page; black ink only above a readable signature caption"),
    ("Partial", "Long statements", "Up to 40 pages read for arithmetic and structure; pixel forensics on the first 6 pages"),
    ("Partial", "Phone photos", "Read and checked logically; ink sensors limited; rotation is corrected, perspective is not"),
    ("Partial", "Hindi", "Tesseract eng+hin selectable; not evaluated on a Hindi dataset"),
    ("Partial", "LLM narrator", "Optional, off by default; rewrites the summary from findings, every sentence must cite a real finding or it is discarded"),
    ("Planned", "Resolution gate", "Pixel sensors stand down on low-resolution images (to be judged once on 577 unread receipts)"),
    ("Planned", "Large-region copy-move", "Logos, stamps, whole rows"),
    ("Planned", "Issuer verification", "Account Aggregator and UIDAI as witnesses that outrank any upload"),
    ("Unsupported", "Handwriting", "Handwritten fields are reported as not read, never as clean"),
    ("Unsupported", "Office files", "DOCX, XLSX and similar are rejected with a reason"),
    ("Unsupported", "Stamps and seals", "Not analysed"),
]
