import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[3]))

from app.ai.preprocessor.pdf_analyzer import analyze_pdf
from app.schemas.layout import DocumentMeta

PDF_PATH = Path(__file__).parents[2] / "samples" / "test.pdf"


def test_file_exists():
    assert PDF_PATH.exists(), f"테스트 PDF 없음: {PDF_PATH}"


def test_returns_tuple():
    result = analyze_pdf(str(PDF_PATH), 1)
    assert isinstance(result, tuple) and len(result) == 2
    doc_meta, page_text = result
    assert isinstance(doc_meta, DocumentMeta)
    assert isinstance(page_text, str)


def test_extraction_method_text_native():
    doc_meta, page_text = analyze_pdf(str(PDF_PATH), 1)
    assert doc_meta.routing_tier == "ZERO", f"예상: ZERO, 실제: {doc_meta.routing_tier}"
    assert len(page_text) > 0


def test_accepts_bytes():
    pdf_bytes = PDF_PATH.read_bytes()
    doc_meta, page_text = analyze_pdf(pdf_bytes, 1)
    assert isinstance(doc_meta, DocumentMeta)
    assert doc_meta.routing_tier in ("ZERO", "STANDARD")


def test_zero_indexed_page_correction():
    doc_meta_1indexed, text_1 = analyze_pdf(str(PDF_PATH), 1)
    doc_meta_0indexed, text_0 = analyze_pdf(str(PDF_PATH), 0)
    assert doc_meta_1indexed.routing_tier == doc_meta_0indexed.routing_tier
    assert text_1 == text_0
