"""Claude vision — transcription lane for scans and handwriting.

Local OCR engines (EasyOCR/Tesseract) top out well below acceptable accuracy
on degraded Indic scans and read no Indic handwriting at all. This extractor
renders each page and asks a Claude vision model for an exact transcription in
the original script. Pages run in a small thread pool; a page whose first pass
looks unreadable is retried once on the escalation model.

Enabled only when an Anthropic API key is configured — the routing layer can
always include "vlm" in a cascade and it is skipped when unavailable.
"""

from __future__ import annotations

import base64
from concurrent.futures import ThreadPoolExecutor

from core.config import settings
from core.logging_setup import get_logger, log
import logging
from schemas.document_schema import DocumentAnalysis, Language
from schemas.extraction_result import PageResult
from .base import Extractor, ExtractorOutput

logger = get_logger("vlm")

_LANGUAGE_NAMES: dict[Language, str] = {
    Language.ENGLISH: "English",
    Language.TAMIL: "Tamil",
    Language.HINDI: "Hindi",
    Language.TELUGU: "Telugu",
    Language.KANNADA: "Kannada",
    Language.MALAYALAM: "Malayalam",
    Language.MARATHI: "Marathi",
    Language.GUJARATI: "Gujarati",
    Language.BENGALI: "Bengali",
}

_SYSTEM_PROMPT = """You are a precise document transcription engine for Indian property records \
(sale deeds, pattas, encumbrance certificates, FMB sketches, revenue records).

Transcribe the page image exactly as written, in its original script and language.

Rules:
- Do not translate, summarize, correct spelling, or add commentary.
- Preserve the reading order of the page. Render tabular content as GitHub-flavored markdown tables.
- Keep survey numbers, document numbers, dates, names, extents, and boundary descriptions exactly as printed or written.
- Transcribe handwritten text as faithfully as printed text.
- Mark text you genuinely cannot read as [illegible]. Mark stamps and seals as [seal: brief text if readable].
- Output only the transcription — no preamble, no explanation."""

_MAX_TOKENS = 8192

_client = None


def _get_client():
    global _client
    if _client is None:
        import anthropic

        _client = anthropic.Anthropic(api_key=settings.anthropic_api_key or None)
    return _client


def _language_hint(analysis: DocumentAnalysis) -> str:
    langs = [analysis.primary_language, *analysis.secondary_languages]
    names = [_LANGUAGE_NAMES[l] for l in langs if l in _LANGUAGE_NAMES]
    return ", ".join(dict.fromkeys(names)) or "unknown (detect from the image)"


def _looks_unreadable(text: str) -> bool:
    stripped = text.strip()
    if len(stripped) < 30:
        return True
    return stripped.count("[illegible]") >= 5


def _confidence(text: str) -> float:
    """Rough per-page confidence from the [illegible] marker density."""
    if not text.strip():
        return 0.0
    illegible = text.count("[illegible]")
    return round(max(0.5, 0.95 - 0.05 * illegible), 3)


def _transcribe(png_bytes: bytes, model: str, hint: str, page_no: int, total: int) -> str:
    response = _get_client().messages.create(
        model=model,
        max_tokens=_MAX_TOKENS,
        system=_SYSTEM_PROMPT,
        messages=[
            {
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": "image/png",
                            "data": base64.standard_b64encode(png_bytes).decode("utf-8"),
                        },
                    },
                    {
                        "type": "text",
                        "text": (
                            f"Transcribe this scanned page. Expected language(s): {hint}. "
                            f"Page {page_no} of {total}."
                        ),
                    },
                ],
            }
        ],
    )
    if response.stop_reason == "refusal":
        return ""
    return "".join(b.text for b in response.content if b.type == "text").strip()


def _ocr_page(png_bytes: bytes, hint: str, page_no: int, total: int) -> tuple[str, str]:
    """Returns (text, model_used). Escalates one unreadable page to the stronger model."""
    text = _transcribe(png_bytes, settings.vlm_model, hint, page_no, total)
    model = settings.vlm_model
    if _looks_unreadable(text) and settings.vlm_escalation_model != settings.vlm_model:
        log(logger, logging.INFO, "vlm_escalate_page", page=page_no, model=settings.vlm_escalation_model)
        retry = _transcribe(png_bytes, settings.vlm_escalation_model, hint, page_no, total)
        if len(retry.strip()) > len(text.strip()):
            return retry, settings.vlm_escalation_model
    return text, model


class VLMExtractor(Extractor):
    name = "vlm"

    def available(self) -> bool:
        if not settings.anthropic_api_key:
            return False
        try:
            import anthropic  # noqa: F401

            return True
        except Exception:  # noqa: BLE001
            return False

    def extract(self, path: str, analysis: DocumentAnalysis) -> ExtractorOutput:
        import fitz

        hint = _language_hint(analysis)
        doc = fitz.open(path)
        try:
            page_count = doc.page_count
            images = [
                doc.load_page(i).get_pixmap(dpi=settings.vlm_dpi).tobytes("png")
                for i in range(page_count)
            ]
        finally:
            doc.close()

        workers = max(1, settings.vlm_page_workers)
        with ThreadPoolExecutor(max_workers=workers) as pool:
            results = list(
                pool.map(
                    lambda item: _ocr_page(item[1], hint, item[0] + 1, page_count),
                    enumerate(images),
                )
            )

        pages: list[PageResult] = []
        parts: list[str] = []
        confs: list[float] = []
        models_used: set[str] = set()
        for i, (text, model) in enumerate(results):
            conf = _confidence(text)
            parts.append(text)
            confs.append(conf)
            models_used.add(model)
            pages.append(
                PageResult(
                    index=i,
                    text=text,
                    chars=len(text),
                    language=analysis.page_languages.get(i, analysis.primary_language),
                    extraction_method=self.name,
                    ocr_confidence=conf,
                )
            )

        avg_conf = sum(confs) / len(confs) if confs else 0.0
        return ExtractorOutput(
            text="\n\n".join(p for p in parts if p).strip(),
            method=self.name,
            page_count=page_count,
            pages=pages,
            ocr_confidence=round(avg_conf, 3),
            layout_confidence=0.7,  # markdown tables preserved, no structural model
            metadata={"vlm_models": sorted(models_used)},
        )
