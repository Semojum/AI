"""PART 6-1~6-3 표 파이프라인 단위 테스트 (TableCap 목 → TableOpt → TableBraille).

현주 파트(table_cap.py) 대신 test_data/page_001/type/table/table_cap.json 목 데이터 사용.

Done Criteria:
  - GriTS > 0.88: 셀 텍스트의 88% 이상이 점자 출력에 존재해야 함.
  - 모든 BrailleOutput이 32칸 이하 줄로 구성되어야 함.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import pytest

from app.ai.braille.table_braille import TableBraille
from app.ai.llm.table_opt import TableOpt
from app.schemas.content import BrailleOutput, ExtractedContent

_DATA_PATH = Path(__file__).parent.parent.parent / "test_data" / "page_001" / "type" / "table" / "table_cap.json"
_GRITS_THRESHOLD = 0.88


def _load_mock() -> list[ExtractedContent]:
    raw: list[dict[str, Any]] = json.loads(_DATA_PATH.read_text(encoding="utf-8"))
    return [ExtractedContent.model_validate(d) for d in raw]


# 한국 점자 규정 제41항에서 직접 도출한 숫자 점자 매핑 (translator 미사용, 비순환)
_DIGIT_BRAILLE = {
    "0": "⠚", "1": "⠁", "2": "⠃", "3": "⠉", "4": "⠙",
    "5": "⠑", "6": "⠋", "7": "⠛", "8": "⠓", "9": "⠊",
}
_NUMBER_INDICATOR = "⠼"  # 수표시 (제41항)


def _numeric_to_expected_braille(text: str) -> str:
    """순수 숫자 문자열 → 수표 + 점자 셀 (제41항 규정 직접 적용, translator 미사용)."""
    return _NUMBER_INDICATOR + "".join(_DIGIT_BRAILLE.get(d, d) for d in text)


def _grits(extracted: ExtractedContent, output: BrailleOutput, render_mode: str) -> float:
    """GriTS 구조 점수: 규정 불변량 기반 (비순환).

    순환 검증 방지: translate_tagged_text 사용 금지.
    대신 규정에서 직접 도출 가능한 구조 불변량만 검사:
      - linear: 행 수만큼 ⠄(유도점) 행 존재 (출력 줄 수 == 입력 행 수)
      - table_grid: 테두리(⠿) 2줄 + 구분선(⠒) (row-1)줄 존재
      - 숫자 셀: 수표(⠼) + 규정 제41항 셀 값이 출력에 존재 (translator와 독립)
    """
    ts = extracted.table_structure
    if not ts:
        return 1.0
    cells = ts.get("cells", [])
    if not cells:
        return 1.0

    max_row = max(c.get("row", 0) for c in cells) + 1
    combined = "".join(output.braille_lines)
    checks: list[bool] = []

    if render_mode == "linear":
        # linear: 각 행이 ⠄(유도점)으로 시작하는 줄로 출력됨
        guide_lines = [ln for ln in output.braille_lines if ln.startswith("⠄")]
        checks.append(len(guide_lines) == max_row)  # 행 수 정확히 일치
        checks.append(len(output.braille_lines) == max_row)  # 총 줄 수 일치
    else:
        # table_grid: border(⠿×32) 2줄 + separator(⠒×32) (row-1)줄 + data row줄
        border_lines = [ln for ln in output.braille_lines if set(ln) == {"⠿"}]
        sep_lines    = [ln for ln in output.braille_lines if set(ln) == {"⠒"}]
        expected_lines = 2 + max_row + (max_row - 1)  # borders + data + separators
        checks.append(len(border_lines) == 2)
        checks.append(len(sep_lines) == max_row - 1)
        checks.append(len(output.braille_lines) == expected_lines)

    # 숫자 셀: 규정 제41항 변환값이 출력에 포함되어야 함 (translator 독립 검증)
    numeric_cells = [
        c for c in cells
        if c.get("text", "").strip().isdigit()
    ]
    for nc in numeric_cells:
        expected = _numeric_to_expected_braille(nc["text"].strip())
        checks.append(expected in combined)

    return sum(checks) / len(checks) if checks else 1.0


@pytest.fixture(scope="module")
def mock_extracted() -> list[ExtractedContent]:
    return _load_mock()


@pytest.fixture(scope="module")
def opt_outputs(mock_extracted: list[ExtractedContent]) -> list[Any]:
    return asyncio.run(TableOpt().optimize(mock_extracted, routing_tier="ZERO"))


@pytest.fixture(scope="module")
def braille_outputs(opt_outputs: list[Any]) -> list[BrailleOutput]:
    return TableBraille().translate(opt_outputs)


class TestTablePipelineBasic:

    def test_mock_data_exists(self) -> None:
        assert _DATA_PATH.exists(), f"목 데이터 없음: {_DATA_PATH}"

    def test_mock_data_nonempty(self, mock_extracted: list[ExtractedContent]) -> None:
        assert len(mock_extracted) >= 1

    def test_output_count_matches_input(
        self,
        mock_extracted: list[ExtractedContent],
        braille_outputs: list[BrailleOutput],
    ) -> None:
        assert len(braille_outputs) == len(mock_extracted)

    def test_all_braille_lines_nonempty(self, braille_outputs: list[BrailleOutput]) -> None:
        for o in braille_outputs:
            assert len(o.braille_lines) >= 1, f"빈 줄 목록: {o.element_id}"

    def test_all_lines_within_32_cols(self, braille_outputs: list[BrailleOutput]) -> None:
        for o in braille_outputs:
            for line in o.braille_lines:
                assert len(line) <= 32, (
                    f"32칸 초과 (id={o.element_id}): {len(line)}칸 — {line!r}"
                )

    def test_rule_trail_excludes_generic(self, braille_outputs: list[BrailleOutput]) -> None:
        # 정책(태민 2026-06-01): 포괄 표 규칙(BBPG-3.1.1)·조판 규칙(BBPG-1.2.1) 미기록.
        # 구조화 표는 점역자 주가 없으면 rule_trail이 비는 것이 정상.
        for o in braille_outputs:
            rids = [r.rule_id for r in o.rule_trail]
            assert "BBPG-3.1.1" not in rids
            assert "BBPG-1.2.1" not in rids

    def test_element_ids_preserved(
        self,
        mock_extracted: list[ExtractedContent],
        braille_outputs: list[BrailleOutput],
    ) -> None:
        src_ids = [str(e.element_id) for e in mock_extracted]
        out_ids = [str(o.element_id) for o in braille_outputs]
        assert src_ids == out_ids


class TestGriTS:
    """GriTS > 0.88: 규정 불변량 기반 구조 보존율 (비순환).

    translate_tagged_text 미사용 — 다음 불변량만 검사:
      1. 행 수가 출력 줄 수에 반영되었는지 (linear/grid 모드별)
      2. 구조 기호(⠿ 테두리, ⠒ 구분선, ⠄ 유도점)가 규정 수에 맞는지
      3. 숫자 셀: 제41항 수표(⠼) + 셀 값이 출력에 포함되는지
    """

    def test_average_grits_above_threshold(
        self,
        mock_extracted: list[ExtractedContent],
        opt_outputs: list[Any],
        braille_outputs: list[BrailleOutput],
    ) -> None:
        scores = [
            _grits(e, o, opt.render_mode)
            for e, opt, o in zip(mock_extracted, opt_outputs, braille_outputs)
        ]
        avg = sum(scores) / len(scores)
        assert avg > _GRITS_THRESHOLD, (
            f"GriTS 평균 {avg:.3f} < {_GRITS_THRESHOLD}: {scores}"
        )

    def test_each_table_grits_above_threshold(
        self,
        mock_extracted: list[ExtractedContent],
        opt_outputs: list[Any],
        braille_outputs: list[BrailleOutput],
    ) -> None:
        for e, opt, o in zip(mock_extracted, opt_outputs, braille_outputs):
            score = _grits(e, o, opt.render_mode)
            assert score > _GRITS_THRESHOLD, (
                f"GriTS {score:.3f} < {_GRITS_THRESHOLD} (id={e.element_id}, mode={opt.render_mode})\n"
                f"  cells: {e.table_structure}\n"
                f"  output: {o.braille_lines}"
            )

    def test_numeric_cells_contain_regulation_braille(
        self,
        mock_extracted: list[ExtractedContent],
        braille_outputs: list[BrailleOutput],
    ) -> None:
        """숫자 셀 검증: 제41항 매핑(translator 독립)으로 수표+셀값 직접 확인."""
        for item, output in zip(mock_extracted, braille_outputs):
            ts = item.table_structure
            if not ts:
                continue
            combined = "".join(output.braille_lines)
            for cell in ts.get("cells", []):
                text = cell.get("text", "").strip()
                if text.isdigit():
                    expected = _numeric_to_expected_braille(text)
                    assert expected in combined, (
                        f"숫자 셀 '{text}' → 기대 점자 {expected!r}가 출력에 없음\n"
                        f"  출력: {combined!r}"
                    )


class TestTableRenderModes:

    def test_2col_table_uses_linear_mode(self, opt_outputs: list[Any]) -> None:
        two_col_items = [o for o in opt_outputs if o.render_mode == "linear"]
        assert len(two_col_items) >= 1, "2열 표의 linear 렌더 모드 없음"

    def test_3col_table_uses_grid_mode(self, opt_outputs: list[Any]) -> None:
        grid_items = [o for o in opt_outputs if o.render_mode == "table_grid"]
        assert len(grid_items) >= 1, "3열 이상 표의 table_grid 렌더 모드 없음"

    def test_grid_output_has_border(self, braille_outputs: list[BrailleOutput]) -> None:
        grid_outputs = [
            o for o in braille_outputs
            if any("⠿" in line for line in o.braille_lines)
        ]
        assert len(grid_outputs) >= 1, "⠿ 테두리 없음"

    def test_linear_output_has_guide(self, braille_outputs: list[BrailleOutput]) -> None:
        linear_outputs = [
            o for o in braille_outputs
            if any("⠄" in line for line in o.braille_lines)
        ]
        assert len(linear_outputs) >= 1, "⠄ 유도점 없음"

    def test_blocked_fallback_produces_placeholder(self) -> None:
        from uuid import uuid4
        blocked = ExtractedContent(
            element_id=uuid4(),
            ocr_confidence=0.1,
            flags=["C4_FALLBACK"],
        )
        result = asyncio.run(TableOpt().optimize([blocked], routing_tier="ZERO"))
        assert result[0].corrected_text == "[표 수동 입력 필요]"

    def test_empty_table_produces_placeholder(self) -> None:
        from uuid import uuid4
        empty = ExtractedContent(element_id=uuid4(), ocr_confidence=0.9)
        result = asyncio.run(TableOpt().optimize([empty], routing_tier="ZERO"))
        assert "[처리 불가" in result[0].corrected_text


class TestTableRoundTrip:

    def test_round_trip_serialization(self, braille_outputs: list[BrailleOutput]) -> None:
        for o in braille_outputs:
            restored = BrailleOutput.model_validate_json(o.model_dump_json())
            assert restored.element_id == o.element_id
            assert restored.braille_lines == o.braille_lines
