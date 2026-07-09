"""Enums and analysis types shared across the orchestrator."""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field


class ExtractionMode(str, Enum):
    AUTO = "auto"
    FAST = "fast"
    LEGAL = "legal"
    RAG = "rag"


class DocumentClass(str, Enum):
    DIGITAL_TEXT = "DIGITAL_TEXT"
    SCANNED = "SCANNED"
    MIXED = "MIXED"
    TABLE_HEAVY = "TABLE_HEAVY"
    LAYOUT_HEAVY = "LAYOUT_HEAVY"
    HANDWRITTEN = "HANDWRITTEN"
    LEGAL_DOCUMENT = "LEGAL_DOCUMENT"
    RAG_REQUIRED = "RAG_REQUIRED"


class Language(str, Enum):
    ENGLISH = "en"
    TAMIL = "ta"
    HINDI = "hi"
    TELUGU = "te"
    KANNADA = "kn"
    MALAYALAM = "ml"
    MARATHI = "mr"
    GUJARATI = "gu"
    BENGALI = "bn"
    UNKNOWN = "unknown"


class PageProfile(BaseModel):
    """Per-page characteristics gathered by the classifier."""

    index: int
    chars: int = 0
    has_text_layer: bool = False
    image_area_ratio: float = 0.0
    line_count: int = 0
    rect_count: int = 0
    language: Language = Language.UNKNOWN
    language_confidence: float = 0.0
    ocr_sample_confidence: float | None = None  # mean word confidence from the sampling pass


class DocumentAnalysis(BaseModel):
    """Output of the analysis layer — drives routing."""

    page_count: int = 0
    document_class: DocumentClass = DocumentClass.DIGITAL_TEXT
    is_digital: bool = True
    is_scanned: bool = False
    is_mixed: bool = False
    has_tables: bool = False
    layout_complex: bool = False
    handwritten: bool = False
    ocr_required: bool = False
    primary_language: Language = Language.UNKNOWN
    secondary_languages: list[Language] = Field(default_factory=list)
    mixed_language: bool = False
    page_languages: dict[int, Language] = Field(default_factory=dict)
    language_confidence: float = 0.0
    digital_text_ratio: float = 0.0  # fraction of pages with a usable text layer
    pages: list[PageProfile] = Field(default_factory=list)
    # First sampled page's OCR text (scanned docs only) — reused by /analyze for
    # content-based type detection so the endpoint never OCRs a second time.
    sample_text: str = ""
