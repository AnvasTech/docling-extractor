"""Document analysis: classify type, detect language, decide OCR need.

Pure analysis — no extraction, no persistence. Language detection follows the
spec: digital text comes from PyMuPDF; scanned PDFs are sampled with a
lightweight OCR callback on first/middle/last pages only (never full-document
OCR just to detect language).
"""

from __future__ import annotations

from typing import Callable

from core.config import settings
from schemas.document_schema import (
    DocumentAnalysis,
    DocumentClass,
    Language,
    PageProfile,
)
from . import language_detector as langdet
from .layout_detector import page_layout_metrics

# (pdf_path, page_indices) -> {page_index: ocr_text}
OcrSampler = Callable[[str, list[int]], dict[int, str]]


def _sample_indices(scanned_pages: list[int]) -> list[int]:
    if not scanned_pages:
        return []
    if len(scanned_pages) <= 3:
        return scanned_pages
    return [scanned_pages[0], scanned_pages[len(scanned_pages) // 2], scanned_pages[-1]]


def classify(path: str, ocr_sampler: OcrSampler | None = None) -> DocumentAnalysis:
    import fitz  # PyMuPDF

    doc = fitz.open(path)
    profiles: list[PageProfile] = []
    page_lang: dict[int, tuple[Language, float]] = {}
    scanned_pages: list[int] = []
    table_score = 0.0
    image_ratio_sum = 0.0

    try:
        n = doc.page_count or 0
        for i in range(n):
            page = doc.load_page(i)
            text = page.get_text() or ""
            chars = len(text.strip())
            has_text = chars >= settings.text_min_per_page
            layout = page_layout_metrics(page)
            table_score += layout["table_likelihood"]
            image_ratio_sum += layout["image_area_ratio"]

            prof = PageProfile(
                index=i,
                chars=chars,
                has_text_layer=has_text,
                image_area_ratio=layout["image_area_ratio"],
                line_count=layout["line_count"],
                rect_count=layout["rect_count"],
            )

            if has_text:
                lang, conf = langdet.detect(text)
                prof.language, prof.language_confidence = lang, conf
                page_lang[i] = (lang, conf)
            else:
                scanned_pages.append(i)
            profiles.append(prof)
    finally:
        doc.close()

    n = len(profiles) or 1

    # Language sampling for scanned pages (lightweight OCR on a few pages).
    if scanned_pages and ocr_sampler is not None:
        try:
            samples = ocr_sampler(path, _sample_indices(scanned_pages))
            for idx, sample_text in samples.items():
                lang, conf = langdet.detect(sample_text)
                page_lang[idx] = (lang, conf)
                if 0 <= idx < len(profiles):
                    profiles[idx].language = lang
                    profiles[idx].language_confidence = conf
        except Exception:  # noqa: BLE001 - sampling is best-effort
            pass

    digital_ratio = sum(1 for p in profiles if p.has_text_layer) / n
    avg_table = table_score / n
    avg_image = image_ratio_sum / n

    if digital_ratio >= 0.8:
        doc_class = DocumentClass.DIGITAL_TEXT
    elif digital_ratio <= 0.2:
        doc_class = DocumentClass.SCANNED
    else:
        doc_class = DocumentClass.MIXED

    has_tables = avg_table >= 0.15
    layout_complex = avg_image >= 0.25 or avg_table >= 0.3
    if has_tables:
        doc_class = DocumentClass.TABLE_HEAVY
    elif layout_complex and doc_class is DocumentClass.DIGITAL_TEXT:
        doc_class = DocumentClass.LAYOUT_HEAVY

    agg = langdet.aggregate(page_lang)

    return DocumentAnalysis(
        page_count=len(profiles),
        document_class=doc_class,
        is_digital=digital_ratio >= 0.8,
        is_scanned=digital_ratio <= 0.2,
        is_mixed=0.2 < digital_ratio < 0.8,
        has_tables=has_tables,
        layout_complex=layout_complex,
        ocr_required=digital_ratio < 0.8,
        primary_language=agg["primary"],
        secondary_languages=agg["secondary"],
        mixed_language=agg["mixed"],
        page_languages={i: lang for i, (lang, _c) in page_lang.items()},
        language_confidence=agg["confidence"],
        digital_text_ratio=round(digital_ratio, 3),
        pages=profiles,
    )
