"""Lightweight OCR sampling for classification (language + handwriting).

Renders a few pages and runs Tesseract in two passes:
  1. OSD (orientation & script detection) — identifies the script so the
     right traineddata is used without OCRing in every language.
  2. `image_to_data` with the script's language pack — yields text plus a
     mean word confidence, which the classifier uses both for language
     detection and as a handwriting signal (printed text OCRs with high
     confidence; handwriting collapses it).

Never used for full extraction — sampling only.
"""

from __future__ import annotations

import tempfile
from dataclasses import dataclass

from core.config import settings
from core.languages import OSD_SCRIPTS, TESSERACT_CODES
from schemas.document_schema import Language


@dataclass
class PageSample:
    text: str
    confidence: float  # mean word confidence 0..1 (0 when nothing recognized)


def available() -> bool:
    try:
        import pytesseract  # noqa: F401

        return True
    except Exception:  # noqa: BLE001
        return False


def _detect_script(image_path: str) -> Language:
    import pytesseract

    try:
        osd = pytesseract.image_to_osd(image_path)
        for line in osd.splitlines():
            if line.startswith("Script:"):
                script = line.split(":", 1)[1].strip()
                return OSD_SCRIPTS.get(script, Language.ENGLISH)
    except Exception:  # noqa: BLE001 - OSD fails on sparse/noisy pages
        pass
    return Language.ENGLISH


def _ocr_with_confidence(image_path: str, lang: Language) -> PageSample:
    import pytesseract

    code = TESSERACT_CODES.get(lang, "eng")
    tess_lang = code if code == "eng" else f"{code}+eng"
    try:
        data = pytesseract.image_to_data(
            image_path, lang=tess_lang, output_type=pytesseract.Output.DICT
        )
    except Exception:  # noqa: BLE001 - missing traineddata → plain english pass
        data = pytesseract.image_to_data(
            image_path, lang="eng", output_type=pytesseract.Output.DICT
        )

    words: list[str] = []
    confs: list[float] = []
    for word, conf in zip(data.get("text", []), data.get("conf", [])):
        try:
            c = float(conf)
        except (TypeError, ValueError):
            continue
        if c < 0 or not str(word).strip():
            continue  # -1 = non-word boxes
        words.append(str(word))
        confs.append(c)

    mean = (sum(confs) / len(confs) / 100.0) if confs else 0.0
    return PageSample(text=" ".join(words), confidence=round(mean, 3))


def sample(path: str, indices: list[int]) -> dict[int, PageSample]:
    """OCR a few pages; best-effort, returns {} when tesseract is missing.

    OSD (script detection) runs once on the first sampled page — a document
    doesn't change script mid-file — and the pages then OCR in parallel.
    Serial OSD+OCR per page made classification of multi-page Indic scans take
    a minute on CPU.
    """
    if not available():
        return {}
    import os
    from concurrent.futures import ThreadPoolExecutor

    import fitz

    valid: list[int] = []
    paths: list[str] = []
    doc = fitz.open(path)
    try:
        for i in indices:
            if not (0 <= i < doc.page_count):
                continue
            pix = doc.load_page(i).get_pixmap(dpi=settings.lang_sample_dpi)
            img = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
            img.close()
            pix.save(img.name)
            valid.append(i)
            paths.append(img.name)
    finally:
        doc.close()

    out: dict[int, PageSample] = {}
    try:
        if not valid:
            return out
        script_lang = _detect_script(paths[0])
        workers = max(1, min(len(valid), settings.ocr_page_workers))
        with ThreadPoolExecutor(max_workers=workers) as pool:
            results = list(pool.map(lambda p: _ocr_with_confidence(p, script_lang), paths))
        out = dict(zip(valid, results))
    finally:
        for p in paths:
            try:
                os.unlink(p)
            except OSError:
                pass
    return out
