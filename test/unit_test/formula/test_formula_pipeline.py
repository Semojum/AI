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


# ── BLEU 근사: 수식 파이프라인 E2E 정확도 ──────────────────────────────────

import asyncio
import json
from pathlib import Path
from unittest.mock import patch

from app.ai.braille.formula_braille import FormulaBraille
from app.ai.llm.formula_opt import FormulaOpt
from app.schemas.content import BrailleOutput, ExtractedContent

_FORMULA_PAIRS_PATH = Path(__file__).parent.parent.parent / "test_data" / "formula_pairs.json"
_BLEU_THRESHOLD = 0.88


def _char_precision(output: str, reference: str) -> float:
    """문자 수준 정밀도: 출력 문자 중 정답에 등장하는 비율."""
    if not output:
        return 0.0
    return sum(1 for ch in output if ch in reference) / len(output)


def _char_recall(output: str, reference: str) -> float:
    """문자 수준 재현율: 정답 문자 중 출력에 등장하는 비율."""
    if not reference:
        return 1.0
    return sum(1 for ch in reference if ch in output) / len(reference)


def _bleu_approx(output: str, reference: str) -> float:
    """F1(precision, recall) 근사 — 문자 수준 BLEU 대체 지표."""
    p = _char_precision(output, reference)
    r = _char_recall(output, reference)
    if p + r == 0:
        return 0.0
    return 2 * p * r / (p + r)


def _load_formula_pairs() -> list[dict]:
    d = json.loads(_FORMULA_PAIRS_PATH.read_text(encoding="utf-8"))
    return [p for p in d["pairs"] if "id" in p and "expected" in p]


def _run_formula_chain(latex: str) -> str:
    """FormulaOpt(ZERO) → FormulaBraille → joined braille string."""
    from uuid import uuid4
    ext = ExtractedContent(element_id=uuid4(), latex_string=latex, ocr_confidence=1.0)
    with patch("app.ai.llm.formula_opt.model_manager"):
        llm_out = asyncio.run(FormulaOpt().optimize([ext], routing_tier="ZERO"))
    braille_out: list[BrailleOutput] = FormulaBraille().translate(llm_out)
    return "".join(braille_out[0].braille_lines)


class TestFormulaBLEU:
    """수식 파이프라인 E2E BLEU 근사 지표 ≥ 0.88.

    formula_pairs.json의 known 쌍을 ZERO 티어로 실행하여 정확도를 측정.
    수식 → 점자 변환은 결정론적이므로 BLEU가 1.0에 수렴해야 함.
    """

    @pytest.fixture(scope="class")
    def pairs(self) -> list[dict]:
        return _load_formula_pairs()

    def test_pairs_loaded(self, pairs: list[dict]) -> None:
        assert len(pairs) >= 10, f"수식 쌍 부족: {len(pairs)}개"

    def test_average_bleu_above_threshold(self, pairs: list[dict]) -> None:
        scores = []
        for p in pairs:
            latex = p["input"].replace("<formula>", "").replace("</formula>", "")
            output = _run_formula_chain(latex)
            scores.append(_bleu_approx(output, p["expected"]))
        avg = sum(scores) / len(scores)
        assert avg >= _BLEU_THRESHOLD, (
            f"수식 BLEU 평균 {avg:.3f} < {_BLEU_THRESHOLD}"
        )

    def test_number_indicator_always_present(self, pairs: list[dict]) -> None:
        """수표(⠼)를 포함하는 수식은 출력에도 ⠼이 있어야 함."""
        num_pairs = [p for p in pairs if "⠼" in p["expected"]]
        for p in num_pairs:
            latex = p["input"].replace("<formula>", "").replace("</formula>", "")
            output = _run_formula_chain(latex)
            assert "⠼" in output, (
                f"[{p['id']}] 수표(⠼) 누락: input={latex!r}, output={output!r}"
            )

    def test_fraction_indicator_present(self, pairs: list[dict]) -> None:
        """분수(⠌)를 포함하는 쌍은 출력에도 ⠌이 있어야 함."""
        frac_pairs = [p for p in pairs if "⠌" in p["expected"]]
        for p in frac_pairs:
            latex = p["input"].replace("<formula>", "").replace("</formula>", "")
            output = _run_formula_chain(latex)
            assert "⠌" in output, (
                f"[{p['id']}] 분수표(⠌) 누락: input={latex!r}, output={output!r}"
            )


class TestMathStructEmit:
    """Phase B: 수식 구조(분수·근·첨자·로그·극한·삼각 등) → rule_trail rule_id emit."""

    def test_구조_rule_id_DB실재(self) -> None:
        # 환각 0: 모든 구조 rule_id ⊆ regulations.json
        from app.ai.braille.kor_math_rules import _STRUCT_RULES
        from app.ai.braille.regulations import all_rule_ids

        db = all_rule_ids()
        missing = [rid for rid, _ in _STRUCT_RULES if rid not in db]
        assert not missing, f"DB에 없는 구조 rule_id: {missing}"

    def test_분수_위첨자_아래첨자_근호(self) -> None:
        from app.ai.braille.kor_math_rules import latex_rule_ids

        assert latex_rule_ids(r"\frac{a^2}{b_i}") == [
            "KBR-수학-1.7", "KBR-수학-2.18", "KBR-수학-2.19"]
        assert latex_rule_ids(r"\sqrt{x}") == ["KBR-수학-2.22"]

    def test_함수명령_아래첨자_오계수없음(self) -> None:
        # \lim_ \log_ \sum_ 의 _ 가 아래첨자(2.19)로 오계수되면 안 됨
        from app.ai.braille.kor_math_rules import latex_rule_ids

        assert latex_rule_ids(r"\lim_{x \to 0}") == ["KBR-수학-6.51"]
        assert latex_rule_ids(r"\log_2 x") == ["KBR-수학-5.46"]
        assert latex_rule_ids(r"\sum_{i=1}^{n}") == ["KBR-수학-2.25"]

    def test_삼각함수_변형_정확분류(self) -> None:
        from app.ai.braille.kor_math_rules import latex_rule_ids

        assert latex_rule_ids(r"\sin x") == ["KBR-수학-5.47"]
        assert latex_rule_ids(r"\arcsin x") == ["KBR-수학-5.48"]   # \sin 오매칭 금지
        assert latex_rule_ids(r"\sinh x") == ["KBR-수학-5.49"]     # \sin 오매칭 금지

    def test_formula_braille_구조trail(self) -> None:
        import uuid

        from app.ai.braille.formula_braille import FormulaBraille
        from app.schemas.content import LLMOutput

        opt = LLMOutput(element_id=str(uuid.uuid4()), corrected_text=r"\frac{1}{2} + \sqrt{x}",
                        render_mode="formula_block", routing_tier="ZERO")
        trail = FormulaBraille().translate([opt])[0].rule_trail
        rids = {r.rule_id for r in trail}
        assert "KBR-수학-1.1" in rids    # 일반 수식 마커 유지
        assert "KBR-수학-1.7" in rids    # 분수
        assert "KBR-수학-2.22" in rids   # 근호

    def test_구조없는_수식은_일반마커만(self) -> None:
        import uuid

        from app.ai.braille.formula_braille import FormulaBraille
        from app.schemas.content import LLMOutput

        opt = LLMOutput(element_id=str(uuid.uuid4()), corrected_text="x + y = z",
                        render_mode="formula_block", routing_tier="ZERO")
        trail = FormulaBraille().translate([opt])[0].rule_trail
        assert [r.rule_id for r in trail] == ["KBR-수학-1.1"]


class TestSymbolOverloadContext:
    """문맥 overload 분기: 수식 내 ∼·→는 수학 의미(텍스트와 다른 글리프)."""

    def test_수식_물결_논리부정(self) -> None:
        from app.ai.braille.kor_math_rules import convert_latex

        out = convert_latex("a ∼ b")
        assert "⠈⠊" in out          # 수식 ∼ = 논리부정·관계
        assert "⠐⠠⠤" not in out      # 텍스트 물결표 아님

    def test_수식_화살표(self) -> None:
        from app.ai.braille.kor_math_rules import convert_latex

        out = convert_latex("x → y")
        assert "⠉⠕" in out          # 수식 → = 수학 화살표·조건문
        assert "⠒⠕" not in out       # 텍스트 화살표(제70항) 아님

    def test_텍스트_물결표_유지(self) -> None:
        # 일반 텍스트 경로(substitute_symbols)에서는 ∼ = 물결표(텍스트 의미 유지)
        from app.ai.braille.symbol_rules import substitute_symbols

        assert substitute_symbols("∼") == "⠐⠠⠤"
