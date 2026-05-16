"""PART 10 — LayoutBraille 조판 단위 테스트.

§2.1.1: 32칸 줄바꿈, 25줄 페이지 넘김
§2.1.2: ⠼N⠲ 페이지 번호 우측 정렬
"""

from uuid import uuid4

import pytest

from app.ai.braille.kor_math_rules import _NUMBER_INDICATOR
from app.ai.braille.layout_braille import LayoutBraille, _COLS, _ROWS
from app.schemas.content import BrailleOutput


def _out(lines: list[str]) -> BrailleOutput:
    return BrailleOutput(element_id=uuid4(), braille_lines=lines)


@pytest.fixture()
def lb(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    return LayoutBraille()


class TestLayoutBraille:

    def test_single_page_has_rows_lines(self, lb) -> None:
        result = lb.layout([_out(["안녕"])], page_no=1, job_id="j1")
        assert len(result) == _ROWS

    def test_page_number_in_last_line(self, lb) -> None:
        result = lb.layout([_out(["안녕"])], page_no=1, job_id="j2")
        assert _NUMBER_INDICATOR in result[-1]

    def test_overflow_creates_second_page(self, lb) -> None:
        result = lb.layout([_out(["x"] * 30)], page_no=1, job_id="j3")
        assert len(result) == _ROWS * 2

    def test_all_lines_within_32_cols(self, lb) -> None:
        result = lb.layout([_out(["a" * 10])], page_no=1, job_id="j4")
        for line in result:
            assert len(line) <= _COLS, f"줄 길이 {len(line)} > {_COLS}: {line!r}"

    def test_second_page_number_digit(self, lb) -> None:
        result = lb.layout([_out(["a"] * 30)], page_no=1, job_id="j5")
        second_last = result[2 * _ROWS - 1]
        assert "⠃" in second_last  # digit '2'

    def test_files_saved_in_temp_result(self, lb, tmp_path) -> None:
        lb.layout([_out(["테스트"])], page_no=1, job_id="save-test")
        base = tmp_path / "storage/jobs/save-test/temp/page_001/result"
        assert (base / "001_result.txt").exists()
        assert (base / "001_result.brf").exists()

    def test_empty_input_still_one_page(self, lb) -> None:
        result = lb.layout([], page_no=3, job_id="j6")
        assert len(result) == _ROWS
        assert _NUMBER_INDICATOR in result[-1]
