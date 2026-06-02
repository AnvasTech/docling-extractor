from analyzers import language_detector as ld
from schemas.document_schema import Language


def test_english():
    lang, conf = ld.detect("This is an English sale deed registered at the SRO.")
    assert lang is Language.ENGLISH
    assert conf > 0.8


def test_tamil_script():
    lang, conf = ld.detect("இது ஒரு தமிழ் பத்திரம் ஆகும்")
    assert lang is Language.TAMIL
    assert conf > 0.5


def test_empty():
    lang, conf = ld.detect("   ")
    assert lang is Language.UNKNOWN
    assert conf == 0.0


def test_aggregate_mixed():
    agg = ld.aggregate({0: (Language.ENGLISH, 0.9), 1: (Language.TAMIL, 0.8)})
    assert agg["primary"] in (Language.ENGLISH, Language.TAMIL)
    assert agg["mixed"] is True
