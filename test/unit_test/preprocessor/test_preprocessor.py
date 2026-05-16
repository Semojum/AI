"""PART 2 — pdf_analyzer 단위 테스트.

라우팅 티어 분기 3종 (ZERO/STANDARD/QUALITY) 검증.
"""

from unittest.mock import MagicMock, patch

import pytest

from app.ai.preprocessor.pdf_analyzer import _calc_confidence


class TestCalcConfidence:

    def test_perfect_score(self) -> None:
        assert _calc_confidence(0.0, 1.0, 1.0) == pytest.approx(1.0)

    def test_zero_score(self) -> None:
        assert _calc_confidence(1.0, 0.0, 0.0) == pytest.approx(0.0)

    def test_formula_weights(self) -> None:
        # broken=0, density=0.5, korean=0 → 0.50 + 0.15 + 0 = 0.65
        assert _calc_confidence(0.0, 0.5, 0.0) == pytest.approx(0.65)


def _mock_fitz(text: str = "한국어 텍스트 " * 20):
    page = MagicMock()
    page.get_text.return_value = text
    page.rect.width = 595.0
    page.rect.height = 842.0
    page.rect.height = 842.0
    page.get_text.return_value = text
    page.get_text.side_effect = None

    def get_text(mode="text", *a, **kw):
        if mode == "blocks":
            return []
        return text

    page.get_text = get_text

    doc = MagicMock()
    doc.__getitem__ = MagicMock(return_value=page)
    doc.close = MagicMock()
    return doc


class TestAnalyzePdf:

    @patch("app.ai.preprocessor.pdf_analyzer._calc_confidence", return_value=0.95)
    @patch("app.ai.preprocessor.pdf_analyzer.fitz")
    def test_zero_tier(self, mock_fitz, mock_conf) -> None:
        mock_fitz.open.return_value = _mock_fitz()
        from app.ai.preprocessor.pdf_analyzer import analyze_pdf
        meta, pdf_text = analyze_pdf(b"pdf", 0, "job1")
        assert meta.routing_tier == "ZERO"
        assert meta.pdf_confidence >= 0.92
        assert pdf_text is not None

    @patch("app.ai.preprocessor.pdf_analyzer._calc_confidence", return_value=0.60)
    @patch("app.ai.preprocessor.pdf_analyzer.fitz")
    def test_standard_tier(self, mock_fitz, mock_conf) -> None:
        mock_fitz.open.return_value = _mock_fitz()
        from app.ai.preprocessor.pdf_analyzer import analyze_pdf
        meta, pdf_text = analyze_pdf(b"pdf", 0, "job2")
        assert meta.routing_tier == "STANDARD"
        assert pdf_text is None

    @patch("app.ai.preprocessor.pdf_analyzer._calc_confidence", return_value=0.15)
    @patch("app.ai.preprocessor.pdf_analyzer.fitz")
    def test_quality_tier(self, mock_fitz, mock_conf) -> None:
        mock_fitz.open.return_value = _mock_fitz()
        from app.ai.preprocessor.pdf_analyzer import analyze_pdf
        meta, pdf_text = analyze_pdf(b"pdf", 0, "job3")
        assert meta.routing_tier == "QUALITY"
        assert meta.scan_only is True
        assert pdf_text is None
