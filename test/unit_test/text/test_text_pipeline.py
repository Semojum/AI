"""PART 4-1~4-3 — 텍스트 파이프라인 단위 테스트 (T3-3).

GPU 모델 불필요한 항목은 활성화.
QwenOCR·HyperCLOVA X 호출이 필요한 항목은 skip 유지.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest

from app.ai.braille.text_braille import TextBraille
from app.ai.braille.translator import translate_tagged_text
from app.ai.braille.symbol_rules import substitute_symbols
from app.schemas.content import BrailleOutput, LLMOutput, RuleApplication

_RULE = RuleApplication(
    rule_id="KBR-1.1",
    source="한국 점자 규정",
    section="1.1",
    title="점자의 기본 원칙",
    excerpt="점자는 한국어 점자 규정에 따라 변환한다.",
    priority="primary",
)


def _make_llm_output(text: str, tier: str = "ZERO") -> LLMOutput:
    return LLMOutput(
        element_id=uuid4(),
        corrected_text=text,
        render_mode="text_only",
        routing_tier=tier,
        processing_time_ms=0,
        rule_trail=[_RULE],
    )


# ── TextOpt ZERO 티어 (GPU 불필요) ─────────────────────────────────────────

class TestTextOptZeroTier:

    @pytest.mark.asyncio
    async def test_zero_tier_returns_text_unchanged(self) -> None:
        """ZERO 티어는 LLM 호출 없이 원문 그대로 반환."""
        from app.ai.llm.text_opt import TextOpt
        with patch("app.ai.llm.text_opt.model_manager") as mock_mm:
            mock_mm.get_status.return_value = {}
            opt = TextOpt()
            extracted = [MagicMock(
                element_id=uuid4(),
                corrected_text="테스트 문장",
                ocr_confidence=1.0,
            )]
            results = await opt.optimize(extracted, routing_tier="ZERO")
        assert len(results) == 1
        assert results[0].corrected_text == "테스트 문장"
        assert results[0].routing_tier == "ZERO"

    @pytest.mark.asyncio
    async def test_zero_tier_rule_trail_not_empty(self) -> None:
        from app.ai.llm.text_opt import TextOpt
        with patch("app.ai.llm.text_opt.model_manager"):
            opt = TextOpt()
            extracted = [MagicMock(
                element_id=uuid4(),
                corrected_text="가나다",
                ocr_confidence=1.0,
            )]
            results = await opt.optimize(extracted, routing_tier="ZERO")
        assert len(results[0].rule_trail) >= 1

    @pytest.mark.asyncio
    async def test_zero_tier_processing_time_zero(self) -> None:
        from app.ai.llm.text_opt import TextOpt
        with patch("app.ai.llm.text_opt.model_manager"):
            opt = TextOpt()
            extracted = [MagicMock(
                element_id=uuid4(),
                corrected_text="텍스트",
                ocr_confidence=1.0,
            )]
            results = await opt.optimize(extracted, routing_tier="ZERO")
        assert results[0].processing_time_ms == 0


# ── TextBraille (GPU 불필요) ────────────────────────────────────────────────

class TestTextBraille:

    def test_translate_returns_braille_output(self) -> None:
        outputs = TextBraille().translate([_make_llm_output("가나다")])
        assert len(outputs) == 1
        assert isinstance(outputs[0], BrailleOutput)

    def test_braille_lines_not_empty(self) -> None:
        outputs = TextBraille().translate([_make_llm_output("안녕하세요")])
        assert outputs[0].braille_lines
        assert all(isinstance(l, str) for l in outputs[0].braille_lines)

    def test_rule_trail_includes_line_wrap_rule(self) -> None:
        outputs = TextBraille().translate([_make_llm_output("테스트")])
        rule_ids = [r.rule_id for r in outputs[0].rule_trail]
        assert "KBR-2.1.1" in rule_ids

    def test_each_line_within_32_cols(self) -> None:
        long_text = "가" * 100
        outputs = TextBraille().translate([_make_llm_output(long_text)])
        for line in outputs[0].braille_lines:
            assert len(line) <= 32

    def test_multiple_elements_isolated(self) -> None:
        """요소 하나 실패해도 다른 요소 결과에 영향 없음."""
        inputs = [_make_llm_output("첫째"), _make_llm_output("둘째")]
        outputs = TextBraille().translate(inputs)
        assert len(outputs) == 2


# ── 특수기호 치환 (T3-5, GPU 불필요) ──────────────────────────────────────

class TestSymbolSubstitution:

    def test_greek_alpha_substituted(self) -> None:
        result = substitute_symbols("α")
        assert result == "⠨⠁"

    def test_arrow_substituted(self) -> None:
        result = substitute_symbols("→")
        assert result == "⠒⠕"

    def test_celsius_substituted(self) -> None:
        result = substitute_symbols("℃")
        assert result == "⠘⠉"

    def test_circled_number_substituted(self) -> None:
        result = substitute_symbols("①")
        assert result == "⠼⠁⠲"

    def test_symbols_integrated_in_translation(self) -> None:
        """translate_tagged_text가 substitute_symbols를 호출하는지 확인."""
        result = translate_tagged_text("α + β")
        assert "⠨⠁" in result
        assert "⠨⠃" in result

    def test_mixed_text_with_symbol(self) -> None:
        result = translate_tagged_text("온도는 25℃이다")
        assert "⠘⠉" in result


# ── GPU 필요 테스트 (skip 유지) ────────────────────────────────────────────

@pytest.mark.skip(reason="QwenOCR GPU 모델 필요 — GPU 환경에서 활성화")
class TestQwenOCR:

    def test_zero_tier_no_qwen_call(self) -> None: ...

    def test_vertical_text_flag(self) -> None: ...


@pytest.mark.skip(reason="HyperCLOVA X GPU 모델 필요 — GPU 환경에서 활성화")
class TestTextOptGPU:

    def test_standard_tier_corrects_text(self) -> None: ...

    def test_fallback_after_3_failures(self) -> None: ...
