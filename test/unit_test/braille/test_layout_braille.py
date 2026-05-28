"""PART 10 — LayoutBraille 조판 단위 테스트.

§2.1.1: 32칸 줄바꿈, 25줄 페이지 넘김
§2.1.2: ⠼N⠲ 페이지 번호 우측 정렬

TestLayoutRulesSpec: 점자 자료 제작 지침 제2장 레이아웃 규칙 검증.
  - testable=True 규칙은 직접 assert.
  - 미구현 규칙은 xfail로 명세 문서화 (구현 후 xfail 제거).
"""

import json
from pathlib import Path
from uuid import uuid4

import pytest

from app.ai.braille.kor_math_rules import _NUMBER_INDICATOR
from app.ai.braille.layout_braille import (
    LayoutBraille, _COLS, _ROWS, _right_align,
    format_no_page_marker, format_page_change_marker,
    format_underline_blank, format_citation,
    indent_numbered_item, format_bullet_item,
    _NO_PAGE_MARKER, _PAGE_CHANGE_MARKER, _UNDERLINE_BLANK_MARKER,
    _BULLET_MARKERS, _NUMBERED_INDENT,
)
from app.schemas.content import BrailleOutput

_JAJAK_RULES = json.loads(
    (Path(__file__).parent.parent.parent / "test_data" / "jajak_layout_rules.json")
    .read_text(encoding="utf-8")
)


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


def _rule(rule_id: str) -> dict:
    return next(r for r in _JAJAK_RULES["rules"] if r["id"] == rule_id)


class TestLayoutRulesSpec:
    """점자 자료 제작 지침 제2장 레이아웃 규칙 — 명세 기반 테스트.

    구현된 규칙: 직접 assert.
    미구현 규칙: xfail로 명세 문서화.
    """

    # ── 이미 구현된 기능 연계 확인 ────────────────────────────────────────────

    def test_right_align_fills_to_32(self) -> None:
        """_right_align은 text를 32칸 우측에 정렬한다."""
        text = "⠼⠁⠲"
        result = _right_align(text, _COLS)
        assert len(result) == _COLS
        assert result.endswith(text)
        assert result.startswith(" " * (_COLS - len(text)))

    def test_page_number_right_aligned_in_page(self, lb, tmp_path, monkeypatch) -> None:
        """§2.1.2 — 페이지 번호는 32칸 우측 정렬."""
        monkeypatch.chdir(tmp_path)
        result = lb.layout([_out(["테스트"])], page_no=1, job_id="align-test")
        last_line = result[-1]
        assert len(last_line) == _COLS
        assert last_line.endswith("⠲")  # 페이지 번호 종료 점형

    # ── 미구현 레이아웃 규칙 (xfail 명세 문서화) ──────────────────────────────

    def test_no_original_page_number_marker(self) -> None:
        """예 2-2 — 원본 페이지 번호 없는 경우 ⠒⠒ 사용 (§2.1.3)."""
        rule = _rule("JAJAK-2.1.3-3")
        assert rule["params"]["no_page_marker"] == _NO_PAGE_MARKER
        assert format_no_page_marker() == "⠒⠒"

    def test_page_change_marker(self) -> None:
        """예 2-13 — 원본 페이지 변경선은 ⠨⠂ 1개 (§2.4.5)."""
        rule = _rule("JAJAK-2.4.5-page-change")
        assert rule["params"]["marker"] == _PAGE_CHANGE_MARKER
        assert rule["params"]["count"] == 1
        assert format_page_change_marker() == "⠨⠂"
        # 반복 호출해도 항상 1개
        assert format_page_change_marker().count("⠨⠂") == 1

    def test_citation_indent_3cols(self) -> None:
        """예 2-22 — 출전이 본문 아래에 있을 경우 다음 줄 3칸에 적는다 (§2.4.9)."""
        rule = _rule("JAJAK-2.4.9-citation-below")
        assert rule["params"]["indent_cols"] == 3
        result = format_citation("정호승, 슬픔이 기쁨에게")
        assert result.startswith("   ")  # 3칸 들여
        assert result == "   정호승, 슬픔이 기쁨에게"

    def test_numbered_item_indent(self) -> None:
        """예 2-11 — 단형 들여쓰기: 1단계 1칸, 2단계 3칸, 3단계 이상 5칸 (§2.4.2)."""
        rule = _rule("JAJAK-2.4.2-numbering")
        assert rule["params"] == {"indent_level1": 1, "indent_level2": 3, "indent_level3_plus": 5}
        assert indent_numbered_item("항목", 1) == " 항목"
        assert indent_numbered_item("항목", 2) == "   항목"
        assert indent_numbered_item("항목", 3) == "     항목"
        assert indent_numbered_item("항목", 4) == "     항목"  # 3단계 이상은 5칸

    def test_bullet_tier_markers(self) -> None:
        """예 2-34 — 글머리 기호: 1단계 ⠿⠒, 2단계 ⠿⠄, 3단계 ⠤ (§2.5.5)."""
        rule = _rule("JAJAK-2.5.5-bullet-tiers")
        assert rule["params"]["tier1_marker"] == _BULLET_MARKERS[1]
        assert rule["params"]["tier2_marker"] == _BULLET_MARKERS[2]
        assert rule["params"]["tier3_marker"] == _BULLET_MARKERS[3]
        assert format_bullet_item("실험학습", 1) == "⠿⠒ 실험학습"
        assert format_bullet_item("주의점", 2) == "⠿⠄ 주의점"
        assert format_bullet_item("묽은 염산", 3) == "⠤ 묽은 염산"
        # 기호 뒤 정확히 1칸
        assert format_bullet_item("항목", 1)[len("⠿⠒")] == " "

    def test_underline_blank_marker(self) -> None:
        """예 2-15 — 밑줄 빈칸은 길이와 관계없이 ⠒⠂ 1개 (§2.4.6)."""
        rule = _rule("JAJAK-2.4.6-underline-blank")
        assert rule["params"]["underline_blank_marker"] == _UNDERLINE_BLANK_MARKER
        assert rule["params"]["count_always"] == 1
        # 짧은 빈칸
        assert format_underline_blank("다음 _에 알맞은") == "다음 ⠒⠂에 알맞은"
        # 긴 빈칸도 ⠒⠂ 1개
        assert format_underline_blank("다음 __에 알맞은") == "다음 ⠒⠂에 알맞은"
        assert format_underline_blank("다음 _____에 알맞은") == "다음 ⠒⠂에 알맞은"
        # 빈칸이 없으면 그대로
        assert format_underline_blank("변화 없음") == "변화 없음"

    def test_jajak_rules_json_loadable(self) -> None:
        """jajak_layout_rules.json 파일 로드 및 필수 필드 검증."""
        assert "rules" in _JAJAK_RULES
        assert len(_JAJAK_RULES["rules"]) >= 10
        for r in _JAJAK_RULES["rules"]:
            assert "id" in r
            assert "description" in r
            assert "testable" in r
