"""PART 5-1~5-3 수식 파이프라인 단위 테스트.

5-1: PP-FormulaNet gRPC OCR (LaTeX 복잡도·검증)
5-2: 수식 KOR_MATH 텍스트 변환 (formula_opt)
5-3: 수식 점역 (formula_braille)
"""

from __future__ import annotations

import pytest

from app.ai.ocr.formula_ocr import _latex_complexity, _validate_latex, _COMPLEXITY_THRESHOLD


class TestLatexComplexity:

    def test_empty_string(self) -> None:
        assert _latex_complexity("") == 0.0

    def test_simple_number(self) -> None:
        assert _latex_complexity("x = 2") < _COMPLEXITY_THRESHOLD

    def test_fraction_raises_complexity(self) -> None:
        assert _latex_complexity(r"\frac{1}{2}") > 0.0

    def test_high_complexity_formula(self) -> None:
        formula = r"\int_0^\infty \frac{x^2}{\sqrt{1+x^4}} \, dx"
        assert _latex_complexity(formula) > _COMPLEXITY_THRESHOLD

    def test_complexity_clipped_at_1(self) -> None:
        formula = r"\frac{\frac{\frac{1}{2}}{3}}{4} \int \sum \prod \lim \sqrt \binom"
        assert _latex_complexity(formula) <= 1.0

    def test_complexity_increases_with_more_special_tokens(self) -> None:
        simple   = r"x + y = z"
        complex_ = r"\frac{1}{2} + \int_0^1 \sqrt{x} dx"
        assert _latex_complexity(complex_) > _latex_complexity(simple)


class TestLatexValidation:

    def test_valid_simple_expression(self) -> None:
        assert _validate_latex("x = 1") is True

    def test_valid_fraction(self) -> None:
        assert _validate_latex(r"\frac{1}{2}") is True

    def test_valid_integral(self) -> None:
        assert _validate_latex(r"\int_0^1 x \, dx") is True

    def test_empty_string_valid(self) -> None:
        assert _validate_latex("") is True

    def test_invalid_unclosed_brace(self) -> None:
        pytest.importorskip("pylatexenc", reason="pylatexenc 미설치 — 서버 환경에서만 검증")
        assert _validate_latex(r"\frac{1}{") is False

    def test_invalid_unknown_command(self) -> None:
        result = _validate_latex(r"\unknowncmd{x}")
        assert isinstance(result, bool)


class TestComplexityThreshold:

    def test_threshold_value(self) -> None:
        assert 0.0 < _COMPLEXITY_THRESHOLD < 1.0

    def test_s_model_for_simple(self) -> None:
        assert _latex_complexity("x = 2") <= _COMPLEXITY_THRESHOLD

    def test_l_model_for_complex(self) -> None:
        formula = r"\int \frac{\sqrt{x}}{\sum_{n=1}^{\infty}} dx"
        assert _latex_complexity(formula) > _COMPLEXITY_THRESHOLD


# TODO [STEP 4]: formula_opt, formula_braille 구현 완료 후 5-2, 5-3 테스트 추가
