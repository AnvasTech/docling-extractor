from orchestrator import routing_engine, strategy_selector
from schemas.document_schema import (
    DocumentAnalysis,
    DocumentClass,
    ExtractionMode,
    Language,
)


def _analysis(**kw) -> DocumentAnalysis:
    base = dict(page_count=3, document_class=DocumentClass.DIGITAL_TEXT, is_digital=True)
    base.update(kw)
    return DocumentAnalysis(**base)


def test_digital_auto_is_cheap():
    cascade = strategy_selector.select(_analysis(), ExtractionMode.AUTO)
    assert cascade[0] == "pymupdf"
    assert "docling" not in cascade


def test_scanned_auto_uses_ocr_first():
    a = _analysis(document_class=DocumentClass.SCANNED, is_digital=False, is_scanned=True)
    cascade = strategy_selector.select(a, ExtractionMode.AUTO)
    assert cascade[0] == "rapidocr"


def test_rag_uses_opendataloader():
    cascade = strategy_selector.select(_analysis(), ExtractionMode.RAG)
    assert cascade[0] == "opendataloader"


def test_legal_full_cascade():
    cascade = strategy_selector.select(_analysis(), ExtractionMode.LEGAL)
    assert cascade == ["pymupdf", "rapidocr", "docling"]


def test_forced_engine_overrides():
    assert strategy_selector.select(_analysis(), ExtractionMode.AUTO, "docling") == ["docling"]


def test_routing_scanned_tamil_puts_ocr_first():
    a = _analysis(
        document_class=DocumentClass.SCANNED,
        is_digital=False,
        is_scanned=True,
        primary_language=Language.TAMIL,
    )
    plan = routing_engine.decide(a, ExtractionMode.AUTO)
    assert plan.cascade[0] == "rapidocr"
    assert "ocr_first" in plan.rationale
