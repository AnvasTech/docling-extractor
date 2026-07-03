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


def text_confidence(text: str, analysis: DocumentAnalysis) -> float:
    """How complete and script-plausible the text looks for this document."""
    if not text.strip():
        return 0.0

    pages = max(analysis.page_count, 1)
    per_page = len(text.strip()) / pages
    # ~400+ chars/page on a text document → full confidence; scale below that.
    score = min(per_page / 400.0, 1.0)

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
