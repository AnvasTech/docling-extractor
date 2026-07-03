from analyzers import quality_analyzer as qa
from schemas.document_schema import DocumentAnalysis, Language


def _analysis(**kw) -> DocumentAnalysis:
    base = dict(page_count=1)
    base.update(kw)
    return DocumentAnalysis(**base)


TAMIL_TEXT = "இது ஒரு தமிழ் பத்திரம் ஆகும் " * 20
ENGLISH_TEXT = "This deed of sale is registered at the sub registrar office " * 10


def test_correct_script_scores_high():
    a = _analysis(primary_language=Language.TAMIL)
    assert qa.text_confidence(TAMIL_TEXT, a) > 0.8


def test_wrong_script_is_penalized():
    # Tamil expected, but the OCR produced only latin text → garbage signal.
    a = _analysis(primary_language=Language.TAMIL)
    wrong = qa.text_confidence(ENGLISH_TEXT, a)
    right = qa.text_confidence(TAMIL_TEXT, a)
    assert wrong < right
    assert wrong <= 0.3


def test_unknown_language_no_penalty():
    a = _analysis()
    assert qa.text_confidence(ENGLISH_TEXT, a) > 0.8


def test_mixed_expected_scripts_accepted():
    a = _analysis(
        primary_language=Language.TAMIL,
        secondary_languages=[Language.ENGLISH],
    )
    mixed = TAMIL_TEXT + ENGLISH_TEXT
    assert qa.text_confidence(mixed, a) > 0.8


def test_script_match_ratio_bengali():
    ratio = qa.script_match_ratio("বাংলা দলিল", {Language.BENGALI})
    assert ratio == 1.0
