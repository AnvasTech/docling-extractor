"""EasyOCR — primary OCR engine for scanned Indic + English documents.

Covers ta, te, kn, bn, hi, mr, en (Malayalam and Gujarati are not supported
by EasyOCR — the Tesseract extractor handles those). Readers are cached per
language pair: an EasyOCR reader can only combine languages that share a
recognition model, so each Indic language gets its own (lang, en) reader and
pages are routed by the classifier's per-page language.
"""

from __future__ import annotations

from core.config import settings
from core.languages import EASYOCR_CODES, document_languages
from schemas.document_schema import DocumentAnalysis, Language
from schemas.extraction_result import PageResult
from .base import Extractor, ExtractorOutput

_readers: dict[tuple[str, ...], object] = {}


def _reader(codes: tuple[str, ...]):
    if codes not in _readers:
        import easyocr

        _readers[codes] = easyocr.Reader(
            list(codes), gpu=settings.easyocr_gpu, verbose=False
        )
    return _readers[codes]


def _codes_for(lang: Language) -> tuple[str, ...]:
    code = EASYOCR_CODES.get(lang)
    if code is None or code == "en":
        return ("en",)
    return (code, "en")


def _ocr_page(pix, codes: tuple[str, ...]) -> tuple[str, float]:
    result = _reader(codes).readtext(pix.tobytes("png"))
    if not result:
        return "", 0.0
    lines = [entry[1] for entry in result if len(entry) >= 2 and entry[1]]
    scores = [float(entry[2]) for entry in result if len(entry) >= 3]
    conf = sum(scores) / len(scores) if scores else 0.0
    return "\n".join(lines), conf


class EasyOCRExtractor(Extractor):
    name = "easyocr"

    def available(self) -> bool:
        try:
            import easyocr  # noqa: F401

            return True
        except Exception:  # noqa: BLE001
            return False

    def supports(self, analysis: DocumentAnalysis) -> bool:
        langs = document_languages(analysis)
        return not langs or any(l in EASYOCR_CODES for l in langs)

    def extract(self, path: str, analysis: DocumentAnalysis) -> ExtractorOutput:
        import fitz

        primary = analysis.primary_language
        doc = fitz.open(path)
        pages: list[PageResult] = []
        parts: list[str] = []
        confs: list[float] = []
        try:
            for i in range(doc.page_count):
                page_lang = analysis.page_languages.get(i, primary)
                if page_lang not in EASYOCR_CODES:
                    page_lang = primary if primary in EASYOCR_CODES else Language.ENGLISH
                pix = doc.load_page(i).get_pixmap(dpi=settings.ocr_dpi)
                text, conf = _ocr_page(pix, _codes_for(page_lang))
                parts.append(text)
                confs.append(conf)
                pages.append(
                    PageResult(
                        index=i,
                        text=text,
                        chars=len(text),
                        language=page_lang,
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
