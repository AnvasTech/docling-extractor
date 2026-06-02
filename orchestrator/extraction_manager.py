"""Runs the cascade with confidence-based escalation; builds the unified result."""

from __future__ import annotations

import time

from analyzers import pdf_classifier, quality_analyzer
from core.logging_setup import get_logger, log
import logging
from extractors.base import Extractor, ExtractorOutput
from extractors.docling_extractor import DoclingExtractor
from extractors.opendataloader_extractor import OpenDataLoaderExtractor
from extractors.pymupdf_extractor import PyMuPDFExtractor
from extractors.rapidocr_extractor import RapidOCRExtractor, sample as ocr_sample
from schemas.document_schema import DocumentAnalysis, ExtractionMode
from schemas.extraction_result import ExtractionResult
from . import routing_engine

logger = get_logger("orchestrator")

# Registry — single instances, engines lazy-load their models on first use.
_REGISTRY: dict[str, Extractor] = {
    "pymupdf": PyMuPDFExtractor(),
    "rapidocr": RapidOCRExtractor(),
    "docling": DoclingExtractor(),
    "opendataloader": OpenDataLoaderExtractor(),
}


def analyze(path: str) -> DocumentAnalysis:
    sampler = ocr_sample if _REGISTRY["rapidocr"].available() else None
    return pdf_classifier.classify(path, ocr_sampler=sampler)


def extract(
    path: str,
    *,
    mode: ExtractionMode = ExtractionMode.AUTO,
    file_name: str = "",
    document_id: str = "",
    document_type: str = "",
    force_engine: str | None = None,
) -> ExtractionResult:
    started = time.perf_counter()
    try:
        analysis = analyze(path)
    except Exception as exc:  # noqa: BLE001 - never let analysis failure block extraction
        log(logger, logging.WARNING, "analysis_failed", file=file_name, error=str(exc))
        analysis = DocumentAnalysis()  # defaults → DIGITAL_TEXT → PyMuPDF first
    plan = routing_engine.decide(analysis, mode, force_engine)
    log(logger, logging.INFO, "plan", file=file_name, cascade=plan.cascade, rationale=plan.rationale)

    rag = mode is ExtractionMode.RAG

    chain: list[str] = []
    best: ExtractorOutput | None = None
    best_conf = -1.0

    for name in plan.cascade:
        engine = _REGISTRY.get(name)
        if engine is None or not engine.available():
            continue
        chain.append(name)
        try:
            out = engine.extract(path, analysis)
        except Exception as exc:  # noqa: BLE001 - escalate on engine failure
            log(logger, logging.WARNING, "engine_failed", engine=name, error=str(exc))
            continue

        conf = quality_analyzer.text_confidence(out.text, analysis)
        if conf > best_conf:
            best, best_conf = out, conf

        # RAG: first engine that yields content wins (don't escalate for cost).
        if rag and out.text.strip():
            best, best_conf = out, conf
            break

        # Accept as soon as the text is good enough. Title-verification analysis
        # runs on the text — escalating a perfectly-extracted digital PDF to a
        # 100x-slower OCR/layout engine just for structure is not worth it. We
        # only escalate when the text itself is thin (genuine scans). Explicit
        # engine=docling (e.g. FMB/A-register routing) still forces layout.
        if not quality_analyzer.should_escalate_extraction(conf):
            break

    if best is None:
        return ExtractionResult(
            document_id=document_id,
            file_name=file_name,
            document_type=document_type,
            page_count=analysis.page_count,
            ok=False,
            extraction_chain=chain,
            metadata={"error": "all extractors failed", "rationale": plan.rationale},
            processing_time_ms=int((time.perf_counter() - started) * 1000),
        ).finalize()

    elapsed_ms = int((time.perf_counter() - started) * 1000)
    result = ExtractionResult(
        document_id=document_id,
        file_name=file_name,
        document_type=document_type,
        page_count=best.page_count or analysis.page_count,
        primary_language=analysis.primary_language.value,
        secondary_languages=[l.value for l in analysis.secondary_languages],
        mixed_language=analysis.mixed_language,
        page_languages={i: lang.value for i, lang in analysis.page_languages.items()},
        ocr_required=analysis.ocr_required,
        extraction_method=best.method,
        extraction_chain=chain,
        confidence_score=round(best_conf, 3),
        ocr_confidence=best.ocr_confidence,
        layout_confidence=best.layout_confidence,
        language_confidence=analysis.language_confidence,
        processing_time_ms=elapsed_ms,
        text=best.text,
        pages=best.pages,
        tables=best.tables,
        metadata={
            "document_class": analysis.document_class.value,
            "digital_text_ratio": analysis.digital_text_ratio,
            "rationale": plan.rationale,
            **best.metadata,
        },
    )
    log(
        logger,
        logging.INFO,
        "extracted",
        file=file_name,
        method=best.method,
        chain=chain,
        chars=len(best.text),
        confidence=round(best_conf, 3),
        ms=elapsed_ms,
    )
    return result.finalize()
