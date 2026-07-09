"""Language-aware routing: turns analysis + mode into an extraction plan."""

from __future__ import annotations

from dataclasses import dataclass

from schemas.document_schema import DocumentAnalysis, ExtractionMode, Language
from . import strategy_selector


@dataclass
class ExtractionPlan:
    cascade: list[str]
    rationale: str


def decide(
    analysis: DocumentAnalysis,
    mode: ExtractionMode,
    force_engine: str | None = None,
) -> ExtractionPlan:
    cascade = strategy_selector.select(analysis, mode, force_engine)
    reasons: list[str] = [f"class={analysis.document_class.value}", f"mode={mode.value}"]

    if force_engine:
        reasons.append(f"forced={force_engine}")
    if analysis.primary_language is not Language.UNKNOWN:
        reasons.append(f"lang={analysis.primary_language.value}")
    if analysis.handwritten:
        reasons.append("handwritten")

    # Mixed-language bundles where layout matters extract better with Docling —
    # make sure it's in the cascade for LEGAL/AUTO.
    if analysis.mixed_language and mode in (ExtractionMode.LEGAL, ExtractionMode.AUTO):
        if "docling" not in cascade:
            cascade = cascade + ["docling"]
        reasons.append("mixed_language→docling_fallback")

    # Scanned non-English must lead with the language-appropriate OCR engine.
    # Handwritten documents keep their VLM lead — reordering an OCR engine in
    # front of it would put an engine that can't read handwriting first.
    if (
        analysis.is_scanned
        and not analysis.handwritten
        and analysis.primary_language not in (Language.ENGLISH, Language.UNKNOWN)
    ):
        lead = strategy_selector.ocr_engines(analysis)[0]
        if cascade and cascade[0] != lead and not force_engine:
            cascade = [lead] + [c for c in cascade if c != lead]
        reasons.append(f"scanned_{analysis.primary_language.value}→ocr_first")

    return ExtractionPlan(cascade=cascade, rationale="; ".join(reasons))
