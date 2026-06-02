"""Extractor abstraction. Every engine returns the same ExtractorOutput."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field

from schemas.document_schema import DocumentAnalysis
from schemas.extraction_result import PageResult, TableResult


@dataclass
class ExtractorOutput:
    text: str
    method: str
    page_count: int = 0
    pages: list[PageResult] = field(default_factory=list)
    tables: list[TableResult] = field(default_factory=list)
    ocr_confidence: float = 1.0
    layout_confidence: float = 0.5
    metadata: dict = field(default_factory=dict)


class Extractor(ABC):
    name: str = "base"

    def available(self) -> bool:  # noqa: D401 - simple availability check
        """Whether this engine's dependencies are importable."""
        return True

    @abstractmethod
    def extract(self, path: str, analysis: DocumentAnalysis) -> ExtractorOutput:
        """Extract text/structure from the file at `path`."""
        raise NotImplementedError
