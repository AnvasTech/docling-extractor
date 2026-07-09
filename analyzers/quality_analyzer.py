"""Confidence scoring for an extractor's output, used to drive escalation.

Two signals combine:
  - density: chars/page vs. what a text document should contain
  - script match: fraction of script-attributable characters that belong to
    the document's expected languages. OCRing Tamil with the wrong model
    produces plenty of characters (density passes) in the wrong script —
    this catches it and forces escalation to the next engine.
"""

from __future__ import annotations

from analyzers.language_detector import _script_of
from core.config import settings
from schemas.document_schema import DocumentAnalysis, Language


def script_match_ratio(text: str, expected: set[Language]) -> float:
    """Fraction of script-bearing chars that match the expected languages."""
    if not expected or Language.UNKNOWN in expected:
        return 1.0
    total = matched = 0
    for ch in text:
        lang = _script_of(ch)
        if lang is None:
            continue
        total += 1
        if lang in expected:
            matched += 1
    if total == 0:
        return 0.0
    return matched / total


# Chars/page that count as a "full" page, by script. Indic scripts encode more
# per character (conjuncts, matras) — a normal Tamil deed page carries far
# fewer characters than an English one. A single 400-char bar made good Indic
# OCR output look "thin" and forced pointless escalation to slower engines.
_DENSITY_NORMS: dict[Language, float] = {
    Language.ENGLISH: 400.0,
    Language.TAMIL: 250.0,
    Language.MALAYALAM: 250.0,
    Language.TELUGU: 280.0,
    Language.KANNADA: 280.0,
    Language.GUJARATI: 280.0,
    Language.HINDI: 300.0,
    Language.MARATHI: 300.0,
    Language.BENGALI: 300.0,
}


def text_confidence(
    text: str,
    analysis: DocumentAnalysis,
    ocr_confidence: float | None = None,
) -> float:
    """How complete and script-plausible the text looks for this document.

    `ocr_confidence` (the engine's own mean word confidence, 0..1) blends in
    when provided, so a dense-but-garbled OCR pass still escalates and a
    clean-but-short Indic page doesn't.
    """
    if not text.strip():
        return 0.0

    pages = max(analysis.page_count, 1)
    per_page = len(text.strip()) / pages
    norm = _DENSITY_NORMS.get(analysis.primary_language, 400.0)
    score = min(per_page / norm, 1.0)

    if ocr_confidence is not None and ocr_confidence > 0:
        score = 0.75 * score + 0.25 * min(ocr_confidence, 1.0)

    expected = {analysis.primary_language, *analysis.secondary_languages} - {
        Language.UNKNOWN
    }
    if expected:
        ratio = script_match_ratio(text, expected)
        if ratio < 0.2:
            score *= 0.25  # wrong script — almost certainly garbage OCR
        elif ratio < 0.5:
            score *= 0.6

    return round(score, 3)


def needs_layout_engine(analysis: DocumentAnalysis) -> bool:
    """True when structure (tables / complex layout) likely needs Docling."""
    return analysis.has_tables or analysis.layout_complex


def should_escalate_extraction(confidence: float) -> bool:
    return confidence < settings.extraction_threshold


def should_escalate_layout(layout_confidence: float) -> bool:
    return layout_confidence < settings.layout_threshold
