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
    assert cascade[0] in ("easyocr", "tesseract")
    # Docling's OCR is Tesseract again — scans escalate to the VLM instead.
    assert cascade[-1] == "vlm"
    assert "docling" not in cascade


def test_scanned_tamil_leads_with_easyocr():
    a = _analysis(
        document_class=DocumentClass.SCANNED,
        is_digital=False,
        is_scanned=True,
        primary_language=Language.TAMIL,
    )
    cascade = strategy_selector.select(a, ExtractionMode.AUTO)
    assert cascade[0] == "easyocr"
    assert "tesseract" in cascade


def test_scanned_malayalam_leads_with_tesseract():
    # EasyOCR has no Malayalam model — Tesseract must lead.
    a = _analysis(
        document_class=DocumentClass.SCANNED,
        is_digital=False,
        is_scanned=True,
        primary_language=Language.MALAYALAM,
    )
    cascade = strategy_selector.select(a, ExtractionMode.AUTO)
    assert cascade[0] == "tesseract"


def test_scanned_gujarati_leads_with_tesseract():
    a = _analysis(
        document_class=DocumentClass.SCANNED,
        is_digital=False,
        is_scanned=True,
        primary_language=Language.GUJARATI,
    )
    cascade = strategy_selector.select(a, ExtractionMode.AUTO)
    assert cascade[0] == "tesseract"


def test_handwritten_leads_with_vlm():
    a = _analysis(
        document_class=DocumentClass.HANDWRITTEN,
        is_digital=False,
        is_scanned=True,
        handwritten=True,
        primary_language=Language.TAMIL,
    )
    cascade = strategy_selector.select(a, ExtractionMode.AUTO)
    assert cascade[0] == "vlm"
    assert set(cascade) == {"vlm", "easyocr", "tesseract"}


def test_handwritten_routing_keeps_vlm_lead():
    # The scanned-non-English reorder must not push an OCR engine in front of
    # the VLM for handwritten documents.
    a = _analysis(
        document_class=DocumentClass.HANDWRITTEN,
        is_digital=False,
        is_scanned=True,
        handwritten=True,
        primary_language=Language.TAMIL,
    )
    plan = routing_engine.decide(a, ExtractionMode.AUTO)
    assert plan.cascade[0] == "vlm"


def test_rag_uses_opendataloader():
    cascade = strategy_selector.select(_analysis(), ExtractionMode.RAG)
    assert cascade[0] == "opendataloader"


def test_legal_full_cascade():
    cascade = strategy_selector.select(_analysis(), ExtractionMode.LEGAL)
    assert cascade == ["pymupdf", "easyocr", "tesseract", "vlm", "docling"]


def test_forced_vlm():
    assert strategy_selector.select(_analysis(), ExtractionMode.AUTO, "vlm") == ["vlm"]


def test_forced_engine_overrides():
    assert strategy_selector.select(_analysis(), ExtractionMode.AUTO, "docling") == ["docling"]


def test_legacy_forced_ocr_maps_to_language_engines():
    a = _analysis(primary_language=Language.MALAYALAM)
    assert strategy_selector.select(a, ExtractionMode.AUTO, "rapidocr")[0] == "tesseract"
    b = _analysis(primary_language=Language.TAMIL)
    assert strategy_selector.select(b, ExtractionMode.AUTO, "ocr")[0] == "easyocr"


def test_routing_scanned_tamil_puts_ocr_first():
    a = _analysis(
        document_class=DocumentClass.SCANNED,
        is_digital=False,
        is_scanned=True,
        primary_language=Language.TAMIL,
    )
    plan = routing_engine.decide(a, ExtractionMode.AUTO)
    assert plan.cascade[0] == "easyocr"
    assert "ocr_first" in plan.rationale
    assert "lang=ta" in plan.rationale
