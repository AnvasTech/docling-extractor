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

    # Mixed-language bundles where layout matters extract better with Docling —
    # make sure it's in the cascade for LEGAL/AUTO.
    if analysis.mixed_language and mode in (ExtractionMode.LEGAL, ExtractionMode.AUTO):
        if "docling" not in cascade:
            cascade = cascade + ["docling"]
        reasons.append("mixed_language→docling_fallback")

    # Scanned non-English needs the OCR engine up front.
    if analysis.is_scanned and analysis.primary_language not in (
        Language.ENGLISH,
        Language.UNKNOWN,
    ):
        if cascade and cascade[0] != "rapidocr":
            cascade = ["rapidocr"] + [c for c in cascade if c != "rapidocr"]
        reasons.append(f"scanned_{analysis.primary_language.value}→ocr_first")

    return ExtractionPlan(cascade=cascade, rationale="; ".join(reasons))
