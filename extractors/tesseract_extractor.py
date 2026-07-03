"""Tesseract — OCR for languages EasyOCR lacks (Malayalam, Gujarati) and the
cross-check fallback for every other script.

Pages render in-memory and OCR in a small thread pool: tesseract runs as a
subprocess per page, so parallel pages give near-linear speedup on multi-core
hosts.
"""

from __future__ import annotations

import tempfile
from concurrent.futures import ThreadPoolExecutor

from core.config import settings
from core.languages import TESSERACT_CODES, document_languages, tesseract_lang_string
from schemas.document_schema import DocumentAnalysis, Language
from schemas.extraction_result import PageResult
from .base import Extractor, ExtractorOutput


def _ocr_page(pix, lang_string: str) -> tuple[str, float]:
    import pytesseract

    with tempfile.NamedTemporaryFile(suffix=".png", delete=True) as img:
        pix.save(img.name)
        try:
            data = pytesseract.image_to_data(
                img.name, lang=lang_string, output_type=pytesseract.Output.DICT
            )
        except Exception:  # noqa: BLE001 - missing traineddata → english pass
            data = pytesseract.image_to_data(
                img.name, lang="eng", output_type=pytesseract.Output.DICT
            )

    lines: dict[tuple, list[str]] = {}
    confs: list[float] = []
    n = len(data.get("text", []))
    for j in range(n):
        word = str(data["text"][j]).strip()
        try:
            conf = float(data["conf"][j])
        except (TypeError, ValueError):
            continue
        if conf < 0 or not word:
            continue
        key = (data["block_num"][j], data["par_num"][j], data["line_num"][j])
        lines.setdefault(key, []).append(word)
        confs.append(conf)

    text = "\n".join(" ".join(words) for _key, words in sorted(lines.items()))
    mean = (sum(confs) / len(confs) / 100.0) if confs else 0.0
    return text, mean


class TesseractExtractor(Extractor):
    name = "tesseract"

    def available(self) -> bool:
        try:
            import pytesseract

            pytesseract.get_tesseract_version()
            return True
        except Exception:  # noqa: BLE001
            return False

    def extract(self, path: str, analysis: DocumentAnalysis) -> ExtractorOutput:
        import fitz

        langs = document_languages(analysis) or [Language.ENGLISH]
        lang_string = tesseract_lang_string(langs)

        doc = fitz.open(path)
        try:
            pixmaps = [
                doc.load_page(i).get_pixmap(dpi=settings.ocr_dpi)
                for i in range(doc.page_count)
            ]
            page_count = doc.page_count
        finally:
            doc.close()

        workers = max(1, settings.ocr_page_workers)
        with ThreadPoolExecutor(max_workers=workers) as pool:
            results = list(pool.map(lambda pix: _ocr_page(pix, lang_string), pixmaps))

        pages: list[PageResult] = []
        parts: list[str] = []
        confs: list[float] = []
        for i, (text, conf) in enumerate(results):
            parts.append(text)
            confs.append(conf)
            pages.append(
                PageResult(
                    index=i,
                    text=text,
                    chars=len(text),
                    language=analysis.page_languages.get(i, analysis.primary_language),
                    extraction_method=self.name,
                    ocr_confidence=round(conf, 3),
                )
            )

        avg_conf = sum(confs) / len(confs) if confs else 0.0
        return ExtractorOutput(
            text="\n\n".join(p for p in parts if p).strip(),
            method=self.name,
            page_count=page_count,
            pages=pages,
            ocr_confidence=round(avg_conf, 3),
            layout_confidence=0.4,
            metadata={"tesseract_langs": lang_string},
        )
