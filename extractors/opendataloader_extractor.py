"""OpenDataLoader-PDF — RAG-ready output (markdown + chunks + tables).

Used ONLY for mode=rag. The exact Python entry point of opendataloader-pdf can
vary by release, so this wrapper probes a few known shapes and degrades
gracefully (available() returns False) when the package isn't installed — the
orchestrator then falls back to Docling for the RAG path.
"""

from __future__ import annotations

from schemas.document_schema import DocumentAnalysis
from schemas.extraction_result import PageResult
from .base import Extractor, ExtractorOutput


class OpenDataLoaderExtractor(Extractor):
    name = "opendataloader"

    def available(self) -> bool:
        try:
            import importlib

            return importlib.util.find_spec("opendataloader_pdf") is not None
        except Exception:  # noqa: BLE001
            return False

    def _run(self, path: str) -> dict:
        import opendataloader_pdf as odl  # type: ignore

        # Probe common entry points across releases.
        for attr in ("extract", "load", "parse", "process"):
            fn = getattr(odl, attr, None)
            if callable(fn):
                return _as_dict(fn(path))
        client_cls = getattr(odl, "OpenDataLoader", None) or getattr(odl, "Loader", None)
        if client_cls is not None:
            client = client_cls()
            for attr in ("extract", "load", "parse", "process"):
                fn = getattr(client, attr, None)
                if callable(fn):
                    return _as_dict(fn(path))
        raise RuntimeError("opendataloader-pdf: no known extract entry point")

    def extract(self, path: str, analysis: DocumentAnalysis) -> ExtractorOutput:
        data = self._run(path)
        markdown = data.get("markdown") or data.get("text") or ""
        chunks = data.get("chunks") or []
        pages = [
            PageResult(index=0, text=markdown, chars=len(markdown), extraction_method=self.name)
        ]
        return ExtractorOutput(
            text=markdown,
            method=self.name,
            page_count=analysis.page_count,
            pages=pages,
            ocr_confidence=0.85,
            layout_confidence=0.9,
            metadata={"chunks": chunks, "rag_ready": True, "raw_keys": list(data.keys())},
        )


def _as_dict(result) -> dict:
    if isinstance(result, dict):
        return result
    if isinstance(result, str):
        return {"markdown": result}
    # object with attributes
    out = {}
    for key in ("markdown", "text", "chunks", "tables", "metadata"):
        val = getattr(result, key, None)
        if val is not None:
            out[key] = val
    return out or {"text": str(result)}
