"""Map (analysis, mode) → an ordered extractor cascade (cheapest-first)."""

from __future__ import annotations

from schemas.document_schema import DocumentAnalysis, DocumentClass, ExtractionMode

# Legacy /jobs `engine` values → forced single-engine cascades.
_FORCED = {
    "pymupdf": ["pymupdf"],
    "ocr": ["rapidocr"],
    "paddle": ["rapidocr"],
    "docling": ["docling"],
}


def select(
    analysis: DocumentAnalysis,
    mode: ExtractionMode,
    force_engine: str | None = None,
) -> list[str]:
    if force_engine and force_engine in _FORCED:
        return list(_FORCED[force_engine])

    if mode is ExtractionMode.RAG:
        # OpenDataLoader primary; Docling/PyMuPDF as graceful fallbacks.
        return ["opendataloader", "docling", "pymupdf"]

    if mode is ExtractionMode.FAST:
        return ["pymupdf", "rapidocr"]

    if mode is ExtractionMode.LEGAL:
        return ["pymupdf", "rapidocr", "docling"]

    # AUTO — choose by document class.
    cls = analysis.document_class
    if cls in (DocumentClass.TABLE_HEAVY, DocumentClass.LAYOUT_HEAVY):
        return ["pymupdf", "docling"]
    if cls is DocumentClass.SCANNED:
        return ["rapidocr", "docling"]
    if cls is DocumentClass.MIXED:
        return ["pymupdf", "rapidocr", "docling"]
    # DIGITAL_TEXT / LEGAL_DOCUMENT
    return ["pymupdf", "rapidocr"]
