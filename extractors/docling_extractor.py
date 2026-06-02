"""Docling — complex layouts, tables, reading order. Heaviest path."""

from __future__ import annotations

from schemas.document_schema import DocumentAnalysis
from schemas.extraction_result import PageResult, TableResult
from .base import Extractor, ExtractorOutput

_converter = None


def _docling():
    global _converter
    if _converter is None:
        from docling.datamodel.base_models import InputFormat
        from docling.datamodel.pipeline_options import (
            PdfPipelineOptions,
            TesseractCliOcrOptions,
        )
        from docling.document_converter import DocumentConverter, PdfFormatOption

        pipeline = PdfPipelineOptions(
            do_ocr=True,
            do_table_structure=True,
            ocr_options=TesseractCliOcrOptions(lang=["eng"]),
        )
        _converter = DocumentConverter(
            format_options={InputFormat.PDF: PdfFormatOption(pipeline_options=pipeline)}
        )
    return _converter


class DoclingExtractor(Extractor):
    name = "docling"

    def available(self) -> bool:
        try:
            import docling  # noqa: F401

            return True
        except Exception:  # noqa: BLE001
            return False

    def extract(self, path: str, analysis: DocumentAnalysis) -> ExtractorOutput:
        result = _docling().convert(path)
        doc = result.document
        markdown = doc.export_to_markdown()
        try:
            page_count = len(doc.pages)
        except Exception:  # noqa: BLE001
            page_count = analysis.page_count

        tables: list[TableResult] = []
        try:
            for t in getattr(doc, "tables", []) or []:
                tables.append(TableResult(page=0, markdown=t.export_to_markdown()))
        except Exception:  # noqa: BLE001
            pass

        pages = [
            PageResult(index=0, text=markdown, chars=len(markdown), extraction_method=self.name)
        ]
        return ExtractorOutput(
            text=markdown,
            method=self.name,
            page_count=page_count,
            pages=pages,
            tables=tables,
            ocr_confidence=0.8,
            layout_confidence=0.9,  # structural model present
        )
