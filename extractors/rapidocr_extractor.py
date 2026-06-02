"""RapidOCR — PP-OCR models via ONNX Runtime. Scanned-page fallback.

Also exposes a lightweight `sample(path, indices)` for language detection so the
classifier can OCR a few pages without a full-document pass.
"""

from __future__ import annotations

import tempfile

from core.config import settings
from schemas.document_schema import DocumentAnalysis, Language
from schemas.extraction_result import PageResult
from .base import Extractor, ExtractorOutput

_engine = None


def _ocr():
    global _engine
    if _engine is None:
        from rapidocr_onnxruntime import RapidOCR

        _engine = RapidOCR()
    return _engine


def _ocr_image(path: str) -> tuple[str, float]:
    result, _elapse = _ocr()(path)
    if not result:
        return "", 0.0
    lines = [row[1] for row in result if len(row) >= 2 and row[1]]
    scores = [float(row[2]) for row in result if len(row) >= 3]
    conf = sum(scores) / len(scores) if scores else 0.0
    return "\n".join(lines), conf


def _render(doc, index: int, dpi: int, fn):
    pix = doc.load_page(index).get_pixmap(dpi=dpi)
    with tempfile.NamedTemporaryFile(suffix=".png", delete=True) as img:
        pix.save(img.name)
        return fn(img.name)


class RapidOCRExtractor(Extractor):
    name = "rapidocr"

    def available(self) -> bool:
        try:
            import rapidocr_onnxruntime  # noqa: F401

            return True
        except Exception:  # noqa: BLE001
            return False

    def extract(self, path: str, analysis: DocumentAnalysis) -> ExtractorOutput:
        import fitz

        doc = fitz.open(path)
        pages: list[PageResult] = []
        parts: list[str] = []
        confs: list[float] = []
        try:
            for i in range(doc.page_count):
                text, conf = _render(doc, i, settings.ocr_dpi, _ocr_image)
                parts.append(text)
                confs.append(conf)
                lang = analysis.page_languages.get(i, Language.UNKNOWN)
                pages.append(
                    PageResult(
                        index=i,
                        text=text,
                        chars=len(text),
                        language=lang,
                        extraction_method=self.name,
                        ocr_confidence=round(conf, 3),
                    )
                )
            page_count = doc.page_count
        finally:
            doc.close()

        avg_conf = sum(confs) / len(confs) if confs else 0.0
        return ExtractorOutput(
            text="\n\n".join(p for p in parts if p).strip(),
            method=self.name,
            page_count=page_count,
            pages=pages,
            ocr_confidence=round(avg_conf, 3),
            layout_confidence=0.4,
        )


def sample(path: str, indices: list[int]) -> dict[int, str]:
    """OCR a few pages (for language detection). Best-effort."""
    import fitz

    doc = fitz.open(path)
    out: dict[int, str] = {}
    try:
        for i in indices:
            if 0 <= i < doc.page_count:
                text, _conf = _render(doc, i, settings.lang_sample_dpi, _ocr_image)
                out[i] = text
    finally:
        doc.close()
    return out
