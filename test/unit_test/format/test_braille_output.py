"""text_braille.json / formula_braille.json 형식 검증."""

from __future__ import annotations

from uuid import uuid4

import pytest

from app.ai.braille.formula_braille import FormulaBraille
from app.ai.braille.symbol_rules import substitute_symbols
from app.ai.braille.text_braille import TextBraille
from app.ai.braille.translator import translate_tagged_text
from app.schemas.content import BrailleOutput, LLMOutput, RuleApplication

_RULE = RuleApplication(
    rule_id="KBR-0.1",
    source="한국 점자 규정",
    section="기본 원칙 1",
    title="기본 원칙",
    excerpt="점자는 한국어 점자 규정에 따라 변환한다.",
    priority="primary",
)


def _text_out(text: str) -> LLMOutput:
    return LLMOutput(
        element_id=uuid4(),
        corrected_text=text,
        render_mode="text_only",
        routing_tier="ZERO",
        processing_time_ms=0,
        rule_trail=[_RULE],
    )


def _formula_out(latex: str, render_mode: str = "formula_block") -> LLMOutput:
    return LLMOutput(
        element_id=uuid4(),
        corrected_text=latex,
        render_mode=render_mode,
        routing_tier="ZERO",
        processing_time_ms=0,
        rule_trail=[_RULE],
    )


# ── TextBraille ─────────────────────────────────────────────────────────────

class TestTextBrailleOutput:

    def test_returns_braille_output_type(self):
        results = TextBraille().translate([_text_out("가나다")])
        assert isinstance(results[0], BrailleOutput)

    def test_braille_lines_not_empty(self):
        results = TextBraille().translate([_text_out("안녕하세요")])
        assert len(results[0].braille_lines) >= 1

    def test_each_line_within_32_cols(self):
        # 모듈은 논리 줄, 32칸 줄바꿈은 layout(BBPG-1.2.1) → break_points wrap 후 검증
        from app.ai.braille.layout_braille import _wrap_line
        r = TextBraille().translate([_text_out("가" * 100)])[0]
        for line, br in zip(r.braille_lines, r.break_points):
            assert all(len(seg) <= 32 for seg in _wrap_line(line, br, 32)[0])

    def test_rule_trail_excludes_generic(self):
        # 정책(태민 2026-06-01): 포괄/조판 규칙(KBR-0.1·BBPG-1.2.1)은 rule_trail 미기록
        rids = [r.rule_id for r in TextBraille().translate([_text_out("테스트")])[0].rule_trail]
        assert "BBPG-1.2.1" not in rids and "KBR-0.1" not in rids

    def test_rule_trail_tn_marker_when_present(self):
        results = TextBraille().translate([_text_out("<!점역자주>주석<!/점역자주>")])
        tags = [r.tag for r in results[0].rule_trail]
        assert "tn_open" in tags and "tn_close" in tags

    def test_formula_tag_removed_from_output(self):
        inp = _text_out("다음 수식: <formula>\\frac{1}{2}</formula> 참조")
        results = TextBraille().translate([inp])
        combined = "".join(results[0].braille_lines)
        assert "<formula>" not in combined
        assert len(combined) > 0

    def test_c5_number_produces_number_indicator(self):
        results = TextBraille().translate([_text_out("20일")])
        combined = "".join(results[0].braille_lines)
        assert "⠼" in combined

    def test_multiple_elements_isolated(self):
        results = TextBraille().translate([_text_out("첫째"), _text_out("둘째")])
        assert len(results) == 2

    def test_round_trip(self):
        results = TextBraille().translate([_text_out("라마바")])
        o = results[0]
        restored = BrailleOutput.model_validate_json(o.model_dump_json())
        assert restored.element_id == o.element_id
        assert restored.braille_lines == o.braille_lines


# ── FormulaBraille ───────────────────────────────────────────────────────────

class TestFormulaBrailleOutput:

    def test_returns_braille_output_type(self):
        results = FormulaBraille().translate([_formula_out("\\frac{1}{2}")])
        assert isinstance(results[0], BrailleOutput)

    def test_braille_lines_not_empty(self):
        results = FormulaBraille().translate([_formula_out("a^2 + b^2 = c^2")])
        assert len(results[0].braille_lines) >= 1

    def test_each_line_within_32_cols(self):
        results = FormulaBraille().translate([_formula_out("\\frac{1}{2}")])
        assert all(len(line) <= 32 for line in results[0].braille_lines)

    def test_rule_trail_math_no_line_wrap(self):
        # 수식 규칙(KBR-수학)은 유지, 조판 규칙(BBPG-1.2.1)은 제거(태민 정책)
        rids = [r.rule_id for r in FormulaBraille().translate([_formula_out("x^2")])[0].rule_trail]
        assert "KBR-수학-1.1" in rids
        assert "BBPG-1.2.1" not in rids

    def test_placeholder_preserved_as_is(self):
        placeholder = "[처리 불가: 수식 OCR 실패]"
        results = FormulaBraille().translate([_formula_out(placeholder)])
        assert results[0].braille_lines == [placeholder]

    def test_round_trip(self):
        results = FormulaBraille().translate([_formula_out("\\sqrt{x}")])
        o = results[0]
        restored = BrailleOutput.model_validate_json(o.model_dump_json())
        assert restored.element_id == o.element_id
        assert restored.braille_lines == o.braille_lines


# ── 특수기호 치환 (symbol_rules) ─────────────────────────────────────────────

class TestSymbolSubstitution:

    def test_greek_alpha_substituted(self):
        assert substitute_symbols("α") == "⠨⠁"

    def test_arrow_substituted(self):
        assert substitute_symbols("→") == "⠒⠕"

    def test_celsius_substituted(self):
        assert substitute_symbols("℃") == "⠴⠙⠠⠉"

    def test_circled_number_substituted(self):
        # 제64항: 동그라미 숫자 = 수표 + 한 단 내림 숫자 (① = ⠼⠂)
        assert substitute_symbols("①") == "⠼⠂"

    def test_symbols_in_translation(self):
        result = translate_tagged_text("α + β")
        assert "⠨⠁" in result
        assert "⠨⠃" in result

    def test_mixed_text_with_symbol(self):
        result = translate_tagged_text("온도는 25℃이다")
        assert "⠴⠙⠠⠉" in result

    def test_symbol_at_start_of_text(self):
        result = substitute_symbols("α는 각도이다")
        assert result.startswith("⠨⠁"), f"문자열 시작 기호 치환 실패: {result!r}"

    def test_symbol_at_end_of_text(self):
        result = substitute_symbols("각도는 α")
        assert result.endswith("⠨⠁"), f"문자열 끝 기호 치환 실패: {result!r}"

    def test_consecutive_symbols_both_present(self):
        """연속 기호 α, β 모두 치환."""
        result = translate_tagged_text("α + β")
        assert "⠨⠁" in result, f"α(⠨⠁) 없음: {result!r}"
        assert "⠨⠃" in result, f"β(⠨⠃) 없음: {result!r}"

    def test_no_double_conversion_of_braille_unicode(self):
        """이미 점자 Unicode로 변환된 문자열을 재입력해도 추가 변환 없음 (_emit_mixed 보호)."""
        pre_converted = substitute_symbols("α")  # "⠨⠁"
        result = translate_tagged_text(pre_converted)
        assert result == pre_converted, (
            f"이미 변환된 점자가 재변환됨: {pre_converted!r} → {result!r}"
        )


class TestRuleTrailCompleteness:

    def test_text_braille_rule_trail_all_fields(self):
        """TextBraille가 추가하는 모든 rule_trail 항목이 필수 6개 필드를 가짐."""
        from app.ai.braille.text_braille import TextBraille
        results = TextBraille().translate([_text_out("테스트")])
        for r in results[0].rule_trail:
            assert r.rule_id,  f"rule_id 없음: {r}"
            assert r.source,   f"source 없음: {r}"
            assert r.section,  f"section 없음: {r}"
            assert r.title,    f"title 없음: {r}"
            assert r.excerpt,  f"excerpt 없음: {r}"
            assert r.priority, f"priority 없음: {r}"

    def test_formula_braille_rule_trail_all_fields(self):
        """FormulaBraille가 추가하는 모든 rule_trail 항목이 필수 6개 필드를 가짐."""
        results = FormulaBraille().translate([_formula_out("\\frac{1}{2}")])
        for r in results[0].rule_trail:
            assert r.rule_id,  f"rule_id 없음: {r}"
            assert r.source,   f"source 없음: {r}"
            assert r.section,  f"section 없음: {r}"
            assert r.title,    f"title 없음: {r}"
            assert r.excerpt,  f"excerpt 없음: {r}"
            assert r.priority, f"priority 없음: {r}"
