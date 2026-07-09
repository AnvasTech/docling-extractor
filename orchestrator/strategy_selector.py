"""Map (analysis, mode) → an ordered extractor cascade (cheapest-first).

Engine selection is language-aware: EasyOCR leads for scripts it supports
(ta, te, kn, bn, hi, mr, en — measurably stronger than Tesseract on Indic
print); Tesseract leads for Malayalam and Gujarati (EasyOCR has no models)
and always trails as the cross-check fallback.
"""

from __future__ import annotations

from core.languages import easyocr_supported
from schemas.document_schema import DocumentAnalysis, DocumentClass, ExtractionMode, Language


def ocr_engines(analysis: DocumentAnalysis) -> list[str]:
    """Ordered OCR engines for this document's language."""
    primary = analysis.primary_language
    if primary is Language.UNKNOWN or easyocr_supported(primary):
        return ["easyocr", "tesseract"]
    return ["tesseract", "easyocr"]  # ml / gu — EasyOCR has no model


def _forced(engine: str, analysis: DocumentAnalysis) -> list[str] | None:
    # Legacy /jobs `engine` values map onto the new registry.
    if engine in ("pymupdf", "docling", "easyocr", "tesseract", "vlm"):
        return [engine]
    if engine in ("ocr", "paddle", "rapidocr"):
        return ocr_engines(analysis)
    return None


def select(
    analysis: DocumentAnalysis,
    mode: ExtractionMode,
    force_engine: str | None = None,
) -> list[str]:
    if force_engine:
        forced = _forced(force_engine, analysis)
        if forced:
            return forced

    ocr = ocr_engines(analysis)

    if mode is ExtractionMode.RAG:
        # OpenDataLoader primary; Docling/PyMuPDF as graceful fallbacks.
        return ["opendataloader", "docling", "pymupdf"]

    if mode is ExtractionMode.FAST:
        return ["pymupdf", ocr[0]]

    if mode is ExtractionMode.LEGAL:
        return ["pymupdf", *ocr, "vlm", "docling"]

    # AUTO — choose by document class.
    cls = analysis.document_class
    if cls is DocumentClass.HANDWRITTEN:
        # No local engine reads Indic handwriting — the VLM leads when
        # configured; both OCR engines remain as offline fallbacks.
        return ["vlm", *ocr]
    if cls in (DocumentClass.TABLE_HEAVY, DocumentClass.LAYOUT_HEAVY):
        return ["pymupdf", "docling"]
    if cls is DocumentClass.SCANNED:
        # Docling dropped here: its internal OCR is Tesseract again, so it
        # adds minutes for zero accuracy after both OCR engines have run.
        # Low-confidence scans escalate to the VLM instead.
        return [*ocr, "vlm"]
    if cls is DocumentClass.MIXED:
        return ["pymupdf", *ocr, "vlm"]
    # DIGITAL_TEXT / LEGAL_DOCUMENT
    return ["pymupdf", ocr[0]]
