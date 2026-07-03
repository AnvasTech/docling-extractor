from schemas.extraction_result import ExtractionResult


def test_finalize_mirrors_compat_fields():
    r = ExtractionResult(text="hello world", extraction_method="pymupdf").finalize()
    assert r.markdown == "hello world"
    assert r.method == "pymupdf"
    assert r.chars == len("hello world")
    assert r.ok is True


def test_dump_has_backward_compat_keys():
    r = ExtractionResult(text="x", extraction_method="easyocr").finalize()
    d = r.model_dump()
    for key in ("ok", "markdown", "method", "chars", "text", "extraction_method"):
        assert key in d
