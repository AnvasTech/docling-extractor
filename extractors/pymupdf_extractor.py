"""PyMuPDF — embedded text-layer extraction. Fast, cheapest, no OCR."""

from __future__ import annotations

from schemas.document_schema import DocumentAnalysis, Language
from schemas.extraction_result import PageResult
from .base import Extractor, ExtractorOutput


class PyMuPDFExtractor(Extractor):
    name = "pymupdf"

    def extract(self, path: str, analysis: DocumentAnalysis) -> ExtractorOutput:
        import fitz

        doc = fitz.open(path)
        pages: list[PageResult] = []
        parts: list[str] = []
        try:
            for i in range(doc.page_count):
                text = (doc.load_page(i).get_text() or "").strip()
                parts.append(text)
                lang = analysis.page_languages.get(i, Language.UNKNOWN)
                pages.append(
                    PageResult(
                        index=i,
                        text=text,
                        chars=len(text),
                        language=lang,
                        extraction_method=self.name,
                        ocr_confidence=0.0,
                    )
                )
            page_count = doc.page_count
        finally:
            doc.close()

        return ExtractorOutput(
            text="\n\n".join(p for p in parts if p).strip(),
            method=self.name,
            page_count=page_count,
            pages=pages,
            ocr_confidence=0.0,
            layout_confidence=0.4,  # no structural model
        )
