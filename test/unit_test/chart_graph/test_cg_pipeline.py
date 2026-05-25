"""PART 9-1~9-3 차트/그래프 파이프라인 단위 테스트 (ChartGraphCap 목 → ChartGraphOpt → ChartGraphBraille).

현주 파트(chart_graph_cap.py) 대신 test_data/page_001/type/chart_graph/chart_graph_cap.json 목 데이터 사용.
"""

from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from app.ai.braille.chart_graph_braille import ChartGraphBraille
from app.ai.llm.chart_graph_opt import ChartGraphOpt
from app.schemas.content import BrailleOutput, ExtractedContent

_DATA_PATH = Path(__file__).parent.parent.parent / "test_data" / "page_001" / "type" / "chart_graph" / "chart_graph_cap.json"
_TIME_LIMIT_S = 7.0


def _load_mock() -> list[ExtractedContent]:
    raw: list[dict[str, Any]] = json.loads(_DATA_PATH.read_text(encoding="utf-8"))
    return [ExtractedContent.model_validate(d) for d in raw]


@pytest.fixture(scope="module")
def mock_extracted() -> list[ExtractedContent]:
    return _load_mock()


@pytest.fixture(scope="module")
def opt_outputs(mock_extracted: list[ExtractedContent]) -> list[Any]:
    with patch("app.ai.llm.chart_graph_opt.model_manager"):
        return asyncio.run(ChartGraphOpt().optimize(mock_extracted, routing_tier="ZERO"))


@pytest.fixture(scope="module")
def braille_outputs(opt_outputs: list[Any]) -> list[BrailleOutput]:
    return ChartGraphBraille().translate(opt_outputs)


class TestChartGraphPipelineBasic:

    def test_mock_data_exists(self) -> None:
        assert _DATA_PATH.exists(), f"목 데이터 없음: {_DATA_PATH}"

    def test_output_count_matches_input(
        self,
        mock_extracted: list[ExtractedContent],
        braille_outputs: list[BrailleOutput],
    ) -> None:
        assert len(braille_outputs) == len(mock_extracted)

    def test_all_braille_lines_nonempty(self, braille_outputs: list[BrailleOutput]) -> None:
        for o in braille_outputs:
            assert len(o.braille_lines) >= 1

    def test_all_lines_within_32_cols(self, braille_outputs: list[BrailleOutput]) -> None:
        for o in braille_outputs:
            for line in o.braille_lines:
                assert len(line) <= 32, f"32칸 초과: {len(line)}칸 — {line!r}"

    def test_rule_trail_present(self, braille_outputs: list[BrailleOutput]) -> None:
        for o in braille_outputs:
            assert len(o.rule_trail) >= 1

    def test_element_ids_preserved(
        self,
        mock_extracted: list[ExtractedContent],
        braille_outputs: list[BrailleOutput],
    ) -> None:
        assert [str(e.element_id) for e in mock_extracted] == [str(o.element_id) for o in braille_outputs]


class TestChartGraphTiming:

    def test_pipeline_completes_within_time_limit(self, mock_extracted: list[ExtractedContent]) -> None:
        start = time.monotonic()
        with patch("app.ai.llm.chart_graph_opt.model_manager"):
            outputs = asyncio.run(ChartGraphOpt().optimize(mock_extracted, routing_tier="ZERO"))
        ChartGraphBraille().translate(outputs)
        elapsed = time.monotonic() - start
        assert elapsed < _TIME_LIMIT_S, f"차트 파이프라인 {elapsed:.2f}s > {_TIME_LIMIT_S}s"


class TestChartGraphTNContent:

    def test_tn_text_set(self, opt_outputs: list[Any]) -> None:
        for o in opt_outputs:
            assert o.tn_text is not None, f"tn_text 없음: {o.element_id}"

    def test_empty_caption_produces_placeholder(self) -> None:
        from uuid import uuid4
        empty = ExtractedContent(element_id=uuid4(), corrected_text="", ocr_confidence=0.9)
        with patch("app.ai.llm.chart_graph_opt.model_manager"):
            result = asyncio.run(ChartGraphOpt().optimize([empty], routing_tier="ZERO"))
        assert "[처리 불가" in result[0].corrected_text

    def test_round_trip_serialization(self, braille_outputs: list[BrailleOutput]) -> None:
        for o in braille_outputs:
            restored = BrailleOutput.model_validate_json(o.model_dump_json())
            assert restored.element_id == o.element_id
            assert restored.braille_lines == o.braille_lines
