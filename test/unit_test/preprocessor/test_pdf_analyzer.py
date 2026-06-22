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


def test_visual_page_routes_standard():
    # test.pdf 1페이지는 이미지·표를 포함 → 순수 텍스트가 아니므로 MinerU(STANDARD).
    doc_meta, _ = analyze_pdf(str(PDF_PATH), 1)
    assert doc_meta.routing_tier == "STANDARD", f"이미지·표 포함 페이지는 STANDARD, 실제: {doc_meta.routing_tier}"


def test_pure_text_routes_zero():
    # 그림·표 없는 순수 텍스트 페이지만 ZERO(빠른 직접추출).
    import fitz
    d = fitz.open()
    d.new_page().insert_text((72, 72), "순수 텍스트만 있는 페이지입니다 그림도 표도 없습니다 abc 123")
    meta, text = analyze_pdf(d.tobytes(), 1)
    d.close()
    assert meta.routing_tier == "ZERO" and len(text) > 0


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
