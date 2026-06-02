"""PART 7-1~7-3 이미지 파이프라인 단위 테스트 (ImageCap 목 → ImageOpt → ImageBraille).

현주 파트(image_cap.py) 대신 test_data/page_001/type/image/image_cap.json 목 데이터 사용.

Done Criteria:
  - 전체 처리 < 7초 (ZERO 티어, GPU 없음)
  - 모든 BrailleOutput이 32칸 이하 줄로 구성
"""

from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from app.ai.braille.image_braille import ImageBraille
from app.ai.llm.image_opt import ImageOpt
from app.schemas.content import BrailleOutput, ExtractedContent

_DATA_PATH = Path(__file__).parent.parent.parent / "test_data" / "page_001" / "type" / "image" / "image_cap.json"
_TIME_LIMIT_S = 7.0


def _load_mock() -> list[ExtractedContent]:
    raw: list[dict[str, Any]] = json.loads(_DATA_PATH.read_text(encoding="utf-8"))
    return [ExtractedContent.model_validate(d) for d in raw]


@pytest.fixture(scope="module")
def mock_extracted() -> list[ExtractedContent]:
    return _load_mock()


@pytest.fixture(scope="module")
def opt_outputs(mock_extracted: list[ExtractedContent]) -> list[Any]:
    with patch("app.ai.llm.image_opt.model_manager"):
        return asyncio.run(ImageOpt().optimize(mock_extracted, routing_tier="ZERO"))


@pytest.fixture(scope="module")
def braille_outputs(opt_outputs: list[Any]) -> list[BrailleOutput]:
    return ImageBraille().translate(opt_outputs)


class TestImagePipelineBasic:

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
        # 모듈은 논리 줄을 내고 32칸 줄바꿈은 layout이 수행(BBPG-1.2.1).
        # break_points로 wrap한 결과가 32칸 이하인지 검증.
        from app.ai.braille.layout_braille import _wrap_line
        for o in braille_outputs:
            brs = o.break_points if len(o.break_points) == len(o.braille_lines) else [[]] * len(o.braille_lines)
            for line, br in zip(o.braille_lines, brs):
                for seg in _wrap_line(line, br, 32)[0]:
                    assert len(seg) <= 32, f"32칸 초과: {len(seg)}칸 — {seg!r}"

    def test_rule_trail_present(self, braille_outputs: list[BrailleOutput]) -> None:
        for o in braille_outputs:
            assert len(o.rule_trail) >= 1

    def test_element_ids_preserved(
        self,
        mock_extracted: list[ExtractedContent],
        braille_outputs: list[BrailleOutput],
    ) -> None:
        assert [str(e.element_id) for e in mock_extracted] == [str(o.element_id) for o in braille_outputs]


class TestImageTiming:
    """ZERO 티어 이미지 파이프라인 전체 처리 < 7초."""

    def test_pipeline_completes_within_time_limit(self, mock_extracted: list[ExtractedContent]) -> None:
        start = time.monotonic()
        with patch("app.ai.llm.image_opt.model_manager"):
            outputs = asyncio.run(ImageOpt().optimize(mock_extracted, routing_tier="ZERO"))
        ImageBraille().translate(outputs)
        elapsed = time.monotonic() - start
        assert elapsed < _TIME_LIMIT_S, (
            f"이미지 파이프라인 {elapsed:.2f}s > {_TIME_LIMIT_S}s 제한"
        )


class TestImageTNContent:

    def test_tn_text_set_in_llm_output(self, opt_outputs: list[Any]) -> None:
        for o in opt_outputs:
            assert o.tn_text is not None, f"tn_text 없음: {o.element_id}"

    def test_blocked_image_produces_output(self) -> None:
        from uuid import uuid4
        blocked = ExtractedContent(
            element_id=uuid4(),
            corrected_text="",
            ocr_confidence=0.0,
            flags=["C2_FALLBACK"],
        )
        with patch("app.ai.llm.image_opt.model_manager"):
            result = asyncio.run(ImageOpt().optimize([blocked], routing_tier="ZERO"))
        braille = ImageBraille().translate(result)
        assert len("".join(braille[0].braille_lines)) > 0

    def test_round_trip_serialization(self, braille_outputs: list[BrailleOutput]) -> None:
        for o in braille_outputs:
            restored = BrailleOutput.model_validate_json(o.model_dump_json())
            assert restored.element_id == o.element_id
            assert restored.braille_lines == o.braille_lines
