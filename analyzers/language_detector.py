"""Script-aware language detection. Works on digital text or OCR samples.

Indic languages are detected by Unicode script block (reliable, dependency-free).
Latin text defaults to English; `langdetect` refines it when installed.
"""

from __future__ import annotations

from schemas.document_schema import Language

# Unicode blocks → language.
_SCRIPT_RANGES: list[tuple[int, int, Language]] = [
    (0x0B80, 0x0BFF, Language.TAMIL),
    (0x0900, 0x097F, Language.HINDI),  # Devanagari (Hindi / Marathi)
    (0x0C00, 0x0C7F, Language.TELUGU),
    (0x0C80, 0x0CFF, Language.KANNADA),
    (0x0D00, 0x0D7F, Language.MALAYALAM),
    (0x0A80, 0x0AFF, Language.GUJARATI),
]


def _script_of(ch: str) -> Language | None:
    cp = ord(ch)
    for lo, hi, lang in _SCRIPT_RANGES:
        if lo <= cp <= hi:
            return lang
    if "a" <= ch.lower() <= "z":
        return Language.ENGLISH
    return None


def detect(text: str) -> tuple[Language, float]:
    """Return (language, confidence 0..1) for a block of text."""
    if not text or not text.strip():
        return Language.UNKNOWN, 0.0

    counts: dict[Language, int] = {}
    total = 0
    for ch in text:
        lang = _script_of(ch)
        if lang is None:
            continue
        counts[lang] = counts.get(lang, 0) + 1
        total += 1

    if total == 0:
        return Language.UNKNOWN, 0.0

    primary = max(counts, key=lambda k: counts[k])
    confidence = counts[primary] / total

    # Refine English with langdetect when available (distinguishes en from other
    # latin-script languages); never override a detected Indic script.
    if primary is Language.ENGLISH:
        try:
            from langdetect import detect as _ld  # type: ignore

            code = _ld(text)
            mapped = {
                "en": Language.ENGLISH,
                "ta": Language.TAMIL,
                "hi": Language.HINDI,
            }.get(code)
            if mapped is not None:
                primary = mapped
        except Exception:  # noqa: BLE001 - langdetect optional / may throw on short text
            pass

    return primary, round(confidence, 3)


def aggregate(page_langs: dict[int, tuple[Language, float]]) -> dict:
    """Combine per-page detections into document-level language facts."""
    weight: dict[Language, float] = {}
    for lang, conf in page_langs.values():
        if lang is Language.UNKNOWN:
            continue
        weight[lang] = weight.get(lang, 0.0) + max(conf, 0.01)

    if not weight:
        return {
            "primary": Language.UNKNOWN,
            "secondary": [],
            "mixed": False,
            "confidence": 0.0,
        }

    ordered = sorted(weight, key=lambda k: weight[k], reverse=True)
    primary = ordered[0]
    secondary = ordered[1:]
    total = sum(weight.values())
    return {
        "primary": primary,
        "secondary": secondary,
        "mixed": len(ordered) > 1 and weight[primary] / total < 0.85,
        "confidence": round(weight[primary] / total, 3),
    }
