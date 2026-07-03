"""Language ↔ OCR-engine code mappings, shared by analyzers and extractors.

Engine coverage for the supported Indic set:
  EasyOCR   — ta, te, kn, bn, hi, mr, en (best open-source accuracy for these)
  Tesseract — all of the above plus ml, gu (the only local engine for those two)
"""

from __future__ import annotations

from schemas.document_schema import Language

# Language → tesseract traineddata code.
TESSERACT_CODES: dict[Language, str] = {
    Language.ENGLISH: "eng",
    Language.TAMIL: "tam",
    Language.HINDI: "hin",
    Language.TELUGU: "tel",
    Language.KANNADA: "kan",
    Language.MALAYALAM: "mal",
    Language.GUJARATI: "guj",
    Language.BENGALI: "ben",
    Language.MARATHI: "mar",
}

# Language → EasyOCR reader code. Malayalam and Gujarati are NOT supported by
# EasyOCR — those route to Tesseract.
EASYOCR_CODES: dict[Language, str] = {
    Language.ENGLISH: "en",
    Language.TAMIL: "ta",
    Language.TELUGU: "te",
    Language.KANNADA: "kn",
    Language.BENGALI: "bn",
    Language.HINDI: "hi",
    Language.MARATHI: "mr",
}

# Tesseract OSD script name → language (script-level: Devanagari could be
# hi/mr — refined later by the unicode detector on the OCR'd text).
OSD_SCRIPTS: dict[str, Language] = {
    "Tamil": Language.TAMIL,
    "Devanagari": Language.HINDI,
    "Telugu": Language.TELUGU,
    "Kannada": Language.KANNADA,
    "Malayalam": Language.MALAYALAM,
    "Gujarati": Language.GUJARATI,
    "Bengali": Language.BENGALI,
    "Latin": Language.ENGLISH,
}


def easyocr_supported(lang: Language) -> bool:
    return lang in EASYOCR_CODES


def tesseract_lang_string(langs: list[Language]) -> str:
    """Build a "tam+eng"-style string; always includes eng, dedup, ordered."""
    codes: list[str] = []
    for lang in langs:
        code = TESSERACT_CODES.get(lang)
        if code and code not in codes:
            codes.append(code)
    if "eng" not in codes:
        codes.append("eng")
    return "+".join(codes)


def document_languages(analysis) -> list[Language]:
    """Primary + secondary languages from an analysis, unknowns dropped."""
    langs = [analysis.primary_language, *analysis.secondary_languages]
    return [l for l in langs if l is not Language.UNKNOWN]
