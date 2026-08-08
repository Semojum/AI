"""text_opt.json / formula_opt.json 형식 검증 — ZERO tier (GPU 불필요)."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from unittest.mock import patch

import pytest

from app.schemas.content import ExtractedContent, LLMOutput

_DATA = Path(__file__).parent.parent.parent / "test_data" / "page_001"

_ALLOWED_RENDER_MODES = {
    "text_only", "table_grid", "transposed", "linear",
    "narrative", "formula_block", "formula_inline",
}


def _load_text() -> list[ExtractedContent]:
    raw = json.loads((_DATA / "type" / "text" / "text_ocr.json").read_text(encoding="utf-8"))
    return [ExtractedContent.model_validate(d) for d in raw]


def _load_formula() -> list[ExtractedContent]:
    raw = json.loads((_DATA / "type" / "formula" / "formula_ocr.json").read_text(encoding="utf-8"))
    return [ExtractedContent.model_validate(d) for d in raw]


class TestTextOptZeroTier:

    @pytest.fixture(scope="class")
    def outputs(self):
        from app.ai.llm.text_opt import TextOpt
        extracted = _load_text()
        with patch("app.ai.llm.text_opt.model_manager"):
            return asyncio.run(TextOpt().optimize(extracted, routing_tier="ZERO"))

    def test_count_matches_input(self, outputs):
        assert len(outputs) == len(_load_text())

    def test_routing_tier_zero(self, outputs):
        assert all(o.routing_tier == "ZERO" for o in outputs)

    def test_processing_time_ms_zero(self, outputs):
        assert all(o.processing_time_ms == 0 for o in outputs)

    def test_corrected_text_unchanged(self, outputs):
        for src, out in zip(_load_text(), outputs):
            assert out.corrected_text == src.corrected_text

    def test_rule_trail_empty_for_plain_elements(self, outputs):
        """★ Step17(2026-08-08 대표 지시) — 불변 규칙 2 "rule_trail 필수"의 범위 축소.

        평문 텍스트·수식에 붙던 포괄 규정(KBR-0.1 "점형은 6점"·수학 제1항 "수표")을 뺐다.
        점역사가 이미 아는 것을 매 요소에 달면 정작 봐야 할 판단이 묻힌다는 판정.
        LLM 단계는 이제 근거를 만들지 않는다 — 근거는 점역 단계가 실제 변환 지점에서 낸다.
        (필드는 그대로 있고 빈 목록일 뿐이라 proto·FE 계약은 안 깨진다.)
        """
        assert all(o.rule_trail == [] for o in outputs)

    def test_render_mode_valid(self, outputs):
        assert all(o.render_mode in _ALLOWED_RENDER_MODES for o in outputs)

    def test_round_trip(self, outputs):
        for o in outputs:
            restored = LLMOutput.model_validate_json(o.model_dump_json())
            assert restored.element_id == o.element_id
            assert restored.corrected_text == o.corrected_text


class TestFormulaOptZeroTier:

    @pytest.fixture(scope="class")
    def outputs(self):
        from app.ai.llm.formula_opt import FormulaOpt
        extracted = _load_formula()
        with patch("app.ai.llm.formula_opt.model_manager"):
            return asyncio.run(FormulaOpt().optimize(extracted, routing_tier="ZERO"))

    def test_count_matches_input(self, outputs):
        assert len(outputs) == len(_load_formula())

    def test_routing_tier_zero(self, outputs):
        assert all(o.routing_tier == "ZERO" for o in outputs)

    def test_processing_time_ms_zero(self, outputs):
        assert all(o.processing_time_ms == 0 for o in outputs)

    def test_corrected_text_not_empty(self, outputs):
        # _normalize() 적용 후 값이므로 원문과 다를 수 있으나 비어있으면 안 됨
        assert all(o.corrected_text for o in outputs)

    def test_rule_trail_empty_for_plain_elements(self, outputs):
        """★ Step17(2026-08-08 대표 지시) — 불변 규칙 2 "rule_trail 필수"의 범위 축소.

        평문 텍스트·수식에 붙던 포괄 규정(KBR-0.1 "점형은 6점"·수학 제1항 "수표")을 뺐다.
        점역사가 이미 아는 것을 매 요소에 달면 정작 봐야 할 판단이 묻힌다는 판정.
        LLM 단계는 이제 근거를 만들지 않는다 — 근거는 점역 단계가 실제 변환 지점에서 낸다.
        (필드는 그대로 있고 빈 목록일 뿐이라 proto·FE 계약은 안 깨진다.)
        """
        assert all(o.rule_trail == [] for o in outputs)

    def test_render_mode_valid(self, outputs):
        assert all(o.render_mode in _ALLOWED_RENDER_MODES for o in outputs)

    def test_round_trip(self, outputs):
        for o in outputs:
            restored = LLMOutput.model_validate_json(o.model_dump_json())
            assert restored.element_id == o.element_id
            assert restored.corrected_text == o.corrected_text
