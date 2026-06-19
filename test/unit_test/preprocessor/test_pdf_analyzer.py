import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[3]))

from app.ai.preprocessor.pdf_analyzer import analyze_pdf

PDF_PATH = Path(__file__).parents[2] / "samples" / "test.pdf"


def test_file_exists():
    assert PDF_PATH.exists(), f"테스트 PDF 없음: {PDF_PATH}"


def test_extraction_method_text_native():
    result = analyze_pdf(str(PDF_PATH), 1)
    assert result == "TEXT_NATIVE", f"예상: TEXT_NATIVE, 실제: {result}"


def test_returns_string():
    result = analyze_pdf(str(PDF_PATH), 1)
    assert isinstance(result, str)
    assert result in ("TEXT_NATIVE", "OCR")
