"""Unified, extractor-agnostic output schema returned to the Title app."""

from __future__ import annotations

from pydantic import BaseModel, Field

from .document_schema import Language


class TableResult(BaseModel):
    page: int
    rows: int = 0
    cols: int = 0
    markdown: str = ""


class PageResult(BaseModel):
    index: int
    text: str = ""
    chars: int = 0
    language: Language = Language.UNKNOWN
    extraction_method: str = ""
    ocr_confidence: float = 0.0


class ExtractionResult(BaseModel):
    document_id: str = ""
    file_name: str = ""
    document_type: str = ""
    page_count: int = 0

    primary_language: str = Language.UNKNOWN.value
    secondary_languages: list[str] = Field(default_factory=list)
    mixed_language: bool = False
    page_languages: dict[int, str] = Field(default_factory=dict)

    ocr_required: bool = False
    extraction_method: str = ""  # e.g. "pymupdf" | "rapidocr" | "docling" | "opendataloader"
    extraction_chain: list[str] = Field(default_factory=list)

    confidence_score: float = 0.0
    ocr_confidence: float = 0.0
    layout_confidence: float = 0.0
    language_confidence: float = 0.0

    processing_time_ms: int = 0

    text: str = ""
    pages: list[PageResult] = Field(default_factory=list)
    tables: list[TableResult] = Field(default_factory=list)
    metadata: dict = Field(default_factory=dict)

    # --- backward-compatibility fields (the existing Title app reads these) ---
    ok: bool = True
    markdown: str = ""
    method: str = ""
    chars: int = 0

    def finalize(self) -> "ExtractionResult":
        """Mirror text into the legacy compat fields before returning."""
        self.markdown = self.text
        self.method = self.extraction_method
        self.chars = len(self.text)
        return self
