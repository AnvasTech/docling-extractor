"""Confidence scoring for an extractor's output, used to drive escalation."""

from __future__ import annotations

from core.config import settings
from schemas.document_schema import DocumentAnalysis


def text_confidence(text: str, analysis: DocumentAnalysis) -> float:
    """How complete the text looks vs. how much the document should contain.

    For digital docs we expect a healthy chars/page ratio; sparse output means
    the extractor missed content and we should escalate.
    """
    pages = max(analysis.page_count, 1)
    per_page = len(text.strip()) / pages
    # ~400+ chars/page on a text document → full confidence; scale below that.
    score = min(per_page / 400.0, 1.0)
    if not text.strip():
        return 0.0
    return round(score, 3)


def needs_layout_engine(analysis: DocumentAnalysis) -> bool:
    """True when structure (tables / complex layout) likely needs Docling."""
    return analysis.has_tables or analysis.layout_complex


def should_escalate_extraction(confidence: float) -> bool:
    return confidence < settings.extraction_threshold


def should_escalate_layout(layout_confidence: float) -> bool:
    return layout_confidence < settings.layout_threshold
