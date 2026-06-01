"""PART 10 — LayoutBraille 조판 단위 테스트.

조판/레이아웃 규정 정본 = 점자 도서 제작 지침(BBPG). 점자 글리프는 한국 점자
규정(KBR)에서 도출. (폐기된 JAJAK 기반 마커 전면 교체됨.)

BBPG 1장2절1: 32칸 줄바꿈, 25줄 페이지 넘김
BBPG 1장2절2: ⠼N⠲ 점자 페이지 번호 우측 정렬

TestLayoutRulesSpec: BBPG 제1·2장 레이아웃 규칙 검증.
  - testable=True 규칙은 직접 assert.
  - 미구현 규칙은 명세 문서화용으로 testable=False (조판 본체 #2에서 배선).
"""

import json
from pathlib import Path
from uuid import uuid4

import pytest

from app.ai.braille.kor_math_rules import _NUMBER_INDICATOR
from app.ai.braille.layout_braille import (
    LayoutBraille, _COLS, _ROWS, _right_align,
    format_underline_blank, format_citation, format_paragraph_start,
    format_bullet_item, format_page_change_line,
    format_box_top, format_box_bottom, format_overflow_page_number,
    _break_line, _cell_count, _center, _HEADING_BLANK,
    _RULE_LINE_WRAP, _RULE_HEADING_BLANK, _RULE_PARA_INDENT, _RULE_BULLET_INDENT,
    _UNDERLINE_BLANK_MARKER, _BULLET_MARKERS, _PAGE_CHANGE_FILL,
    _OVERFLOW_PAGE_NUMBER, _BOX_BORDER_END, _BOX_TOP_FILL, _BOX_BOTTOM_FILL,
    _is_border_line,
)
from app.schemas.content import BrailleOutput
from app.schemas.layout import BBoxItem, LayoutResult

_BBPG_RULES = json.loads(
    (Path(__file__).parent.parent.parent / "test_data" / "bbpg_layout_rules.json")
    .read_text(encoding="utf-8")
)


def _out(lines: list[str], element_id=None) -> BrailleOutput:
    return BrailleOutput(element_id=element_id or uuid4(), braille_lines=lines)


def _layout(*items) -> LayoutResult:
    """items: (element_id, type, reading_order, heading_level) 튜플."""
    return LayoutResult(
        page_id="p",
        elements=[
            BBoxItem(element_id=eid, type=t, bbox=(0, 0, 0, 0),
                     reading_order=o, heading_level=h)
            for (eid, t, o, h) in items
        ],
    )


def _read_lines(tmp_path, job_id: str, page_no: int = 1) -> list[str]:
    p = (tmp_path / f"storage/jobs/{job_id}/temp/page_{page_no:03d}/result"
         / f"{page_no:03d}_result.txt")
    return p.read_text(encoding="utf-8").split("\n")


@pytest.fixture()
def lb(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    return LayoutBraille()


class TestLayoutBraille:

    def test_single_page_has_rows_lines(self, lb, tmp_path) -> None:
        lb.layout([_out(["안녕"])], page_no=1, job_id="j1")
        assert len(_read_lines(tmp_path, "j1")) == _ROWS

    def test_page_number_in_last_line(self, lb, tmp_path) -> None:
        lb.layout([_out(["안녕"])], page_no=1, job_id="j2")
        assert _NUMBER_INDICATOR in _read_lines(tmp_path, "j2")[-1]

    def test_overflow_creates_second_page(self, lb, tmp_path) -> None:
        lb.layout([_out([f"r{i}" for i in range(30)])], page_no=1, job_id="j3")
        assert len(_read_lines(tmp_path, "j3")) == _ROWS * 2

    def test_all_lines_within_32_cols(self, lb, tmp_path) -> None:
        lb.layout([_out(["a" * 100])], page_no=1, job_id="j4")
        for line in _read_lines(tmp_path, "j4"):
            assert _cell_count(line) <= _COLS, f"줄 길이 {len(line)} > {_COLS}: {line!r}"

    def test_second_page_number_digit(self, lb, tmp_path) -> None:
        lb.layout([_out([f"r{i}" for i in range(30)])], page_no=1, job_id="j5")
        lines = _read_lines(tmp_path, "j5")
        assert "⠃" in lines[2 * _ROWS - 1]  # 둘째 페이지 번호 digit '2'

    def test_files_saved_in_temp_result(self, lb, tmp_path) -> None:
        lb.layout([_out(["테스트"])], page_no=1, job_id="save-test")
        base = tmp_path / "storage/jobs/save-test/temp/page_001/result"
        assert (base / "001_result.txt").exists()
        assert (base / "001_result.brf").exists()

    def test_empty_input_still_one_page(self, lb, tmp_path) -> None:
        rate = lb.layout([], page_no=3, job_id="j6")
        lines = _read_lines(tmp_path, "j6", page_no=3)
        assert len(lines) == _ROWS
        assert _NUMBER_INDICATOR in lines[-1]
        assert rate == 0.0

    def test_layout_returns_float_rate(self, lb) -> None:
        rate = lb.layout([_out(["안녕"])], page_no=1, job_id="j-rate")
        assert isinstance(rate, float) and rate == 0.0


def _rule(rule_id: str) -> dict:
    return next(r for r in _BBPG_RULES["rules"] if r["id"] == rule_id)


class TestLayoutRulesSpec:
    """BBPG 제1·2장 레이아웃 규칙 — 명세 기반 테스트.

    데이터 파일(bbpg_layout_rules.json)의 params와 실제 헬퍼 출력을 함께 검증.
    """

    # ── 이미 구현된 기능 연계 확인 ────────────────────────────────────────────

    def test_right_align_fills_to_32(self) -> None:
        """_right_align은 text를 32칸 우측에 정렬한다."""
        text = "⠼⠁⠲"
        result = _right_align(text, _COLS)
        assert len(result) == _COLS
        assert result.endswith(text)
        assert result.startswith(" " * (_COLS - len(text)))

    def test_page_number_right_aligned_in_page(self, lb, tmp_path) -> None:
        """BBPG 1장2절2 — 점자 페이지 번호는 32칸 우측 정렬."""
        lb.layout([_out(["테스트"])], page_no=1, job_id="align-test")
        last_line = _read_lines(tmp_path, "align-test")[-1]
        assert len(last_line) == _COLS
        assert last_line.endswith("⠲")  # 페이지 번호 종료 점형

    # ── BBPG 마커/헬퍼 검증 ───────────────────────────────────────────────────

    def test_underline_blank_marker(self) -> None:
        """BBPG 2장2절3 — 밑줄 빈칸은 길이와 관계없이 ⠸⠤ 1개 (KBR 밑줄 빈칸)."""
        rule = _rule("BBPG-2.2.3-underline-blank")
        assert rule["params"]["underline_blank_marker"] == _UNDERLINE_BLANK_MARKER == "⠸⠤"
        assert rule["params"]["count_always"] == 1
        assert format_underline_blank("다음 _에 알맞은") == "다음 ⠸⠤에 알맞은"
        # 길이 무관 1개
        assert format_underline_blank("다음 __에 알맞은") == "다음 ⠸⠤에 알맞은"
        assert format_underline_blank("다음 _____에 알맞은") == "다음 ⠸⠤에 알맞은"
        # 빈칸이 없으면 그대로
        assert format_underline_blank("변화 없음") == "변화 없음"

    def test_bullet_tier_markers(self) -> None:
        """BBPG 2장3절5 — 글머리 위계 2단계: 1단계 동그라미 ⠸⠴, 2단계 붙임표 ⠤ (KBR 제72항)."""
        rule = _rule("BBPG-2.3.5-bullet-tiers")
        assert rule["params"]["tier1_marker"] == _BULLET_MARKERS[1] == "⠸⠴"
        assert rule["params"]["tier2_marker"] == _BULLET_MARKERS[2] == "⠤"
        assert rule["params"]["indent_cols"] == 3
        # 3칸 표기(2칸 들여 후 마커) + 기호 뒤 1칸
        assert format_bullet_item("실험학습", 1) == "  ⠸⠴ 실험학습"
        assert format_bullet_item("주의점", 2) == "  ⠤ 주의점"
        # 위계 범위 밖은 2단계로 클램프
        assert format_bullet_item("항목", 3) == "  ⠤ 항목"
        assert format_bullet_item("항목", 0) == "  ⠸⠴ 항목"
        # 마커 뒤 정확히 1칸
        assert format_bullet_item("항목", 1) == "  ⠸⠴ 항목"

    def test_page_change_line(self) -> None:
        """BBPG 2장2절2-3) — 변경선은 첫 칸부터 ⠤로 채운 선 + 우측정렬 원본 페이지번호."""
        rule = _rule("BBPG-2.2.2-page-change-line")
        assert rule["params"]["fill_glyph"] == _PAGE_CHANGE_FILL == "⠤"
        assert rule["params"]["total_cols"] == _COLS
        orig = "⠼⠃"  # 원본 페이지 번호 2
        line = format_page_change_line(orig)
        assert len(line) == _COLS
        assert line.startswith("⠤")
        assert line.endswith(orig)
        # 채움 길이 = 32 - 원본번호 길이
        assert line == "⠤" * (_COLS - len(orig)) + orig

    def test_overflow_page_number(self) -> None:
        """BBPG 2장2절2 — 선행 페이지 초과 시 ⠼⠤. JAJAK no-page ⠒⠒ 마커는 폐기."""
        rule = _rule("BBPG-2.2.2-overflow-page")
        assert rule["params"]["overflow_page_number"] == _OVERFLOW_PAGE_NUMBER == "⠼⠤"
        assert rule["params"]["no_page_placeholder"] is None
        assert format_overflow_page_number() == "⠼⠤"

    def test_citation_indent_3cols(self) -> None:
        """BBPG 2장2절6 — 출전이 본문 아래에 있을 경우 다음 줄 3칸에 적는다."""
        rule = _rule("BBPG-2.2.6-citation-below")
        assert rule["params"]["indent_cols"] == 3
        result = format_citation("정호승, 슬픔이 기쁨에게")
        assert result == "   정호승, 슬픔이 기쁨에게"

    def test_paragraph_start_indent(self) -> None:
        """BBPG 2장2절2 — 새 문단은 3칸에서 시작."""
        rule = _rule("BBPG-2.2.2-paragraph")
        assert rule["params"]["first_line_indent"] == 3
        assert rule["params"]["continuation_indent"] == 0
        assert format_paragraph_start("본문 내용") == "   본문 내용"

    def test_box_borders(self) -> None:
        """BBPG 1장2절5 — 글상자 위 ⠿…⠛…⠿ / 아래 ⠿…⠶…⠿ (32칸)."""
        rule = _rule("BBPG-1.2.5-box")
        assert rule["params"]["border_end"] == _BOX_BORDER_END == "⠿"
        assert rule["params"]["top_fill"] == _BOX_TOP_FILL == "⠛"
        assert rule["params"]["bottom_fill"] == _BOX_BOTTOM_FILL == "⠶"
        top, bottom = format_box_top(), format_box_bottom()
        assert len(top) == len(bottom) == _COLS
        assert top[0] == top[-1] == "⠿"
        assert bottom[0] == bottom[-1] == "⠿"
        assert top == "⠿" + "⠛" * (_COLS - 2) + "⠿"
        assert bottom == "⠿" + "⠶" * (_COLS - 2) + "⠿"
        # 중간 채움 글리프 구분
        assert set(top[1:-1]) == {"⠛"}
        assert set(bottom[1:-1]) == {"⠶"}

    def test_bbpg_rules_json_loadable(self) -> None:
        """bbpg_layout_rules.json 파일 로드 및 필수 필드 검증."""
        assert "rules" in _BBPG_RULES
        assert len(_BBPG_RULES["rules"]) >= 10
        for r in _BBPG_RULES["rules"]:
            assert "id" in r
            assert "rule_id" in r and r["rule_id"].startswith("BBPG")
            assert "description" in r
            assert "testable" in r


class TestBreakLine:
    """32칸 단어경계 라인 브레이킹 (_break_line)."""

    def test_short_line_noop(self) -> None:
        assert _break_line("짧은 줄") == (["짧은 줄"], 0, [])

    def test_word_boundary_split(self) -> None:
        # 각 단어 2셀, 32칸이면 단어 경계에서만 분리 (강제분리 0)
        line = " ".join(["가나"] * 15)  # 15단어 → 한 줄 초과
        broken, forced, wraps = _break_line(line)
        for b in broken:
            assert _cell_count(b) <= _COLS
        assert forced == 0
        assert len(broken) >= 2

    def test_force_split_long_word(self) -> None:
        broken, forced, wraps = _break_line("가" * 40)
        assert broken == ["가" * 32, "가" * 8]
        assert forced == 1
        assert wraps == [32]

    def test_force_split_multiple(self) -> None:
        broken, forced, wraps = _break_line("가" * 70)
        assert broken == ["가" * 32, "가" * 32, "가" * 6]
        assert forced == 2
        assert wraps == [32, 64]


class TestLayoutBody:
    """PART 10 조판 본체 — 정렬·제목 빈줄·브레이킹·overflow rate·rule_trail."""

    def test_reading_order_sort(self, lb, tmp_path) -> None:
        e1, e2 = uuid4(), uuid4()
        lr = _layout((e1, "text", 2, 0), (e2, "text", 1, 0))
        lb.layout([_out(["둘째"], e1), _out(["첫째"], e2)],
                  page_no=1, job_id="ord", layout_result=lr)
        lines = _read_lines(tmp_path, "ord")
        assert lines[0].strip() == "첫째" and lines[1].strip() == "둘째"

    def test_32_cell_line_breaking(self, lb, tmp_path) -> None:
        eid = uuid4()
        lr = _layout((eid, "text", 1, 0))
        lb.layout([_out(["가" * 50], eid)], page_no=1, job_id="brk", layout_result=lr)
        for line in _read_lines(tmp_path, "brk"):
            assert _cell_count(line) <= _COLS

    def test_heading_blank_lines(self, lb, tmp_path) -> None:
        """heading level 1 → 앞 2줄·뒤 1줄 빈 줄 (페이지 첫 줄 빈 줄은 별도)."""
        e1, e2 = uuid4(), uuid4()
        lr = _layout((e1, "text", 1, 0), (e2, "title", 2, 1))
        lb.layout([_out(["본문"], e1), _out(["제목"], e2)],
                  page_no=1, job_id="hd", layout_result=lr)
        lines = _read_lines(tmp_path, "hd")
        assert lines[0].strip() == "본문"           # text 첫줄 3칸 들여
        assert lines[1] == "" and lines[2] == ""    # 제목 앞 2줄
        assert lines[3].strip() == "제목"           # 1단계 제목(가운데 정렬)
        assert lines[4] == ""                        # 뒤 1줄

    def test_heading_blank_not_in_rule_trail(self, lb) -> None:
        # 조판 정책(태민 2026-06-01): heading 빈 줄은 적용하되 rule_trail에 기록하지 않는다.
        eid = uuid4()
        lr = _layout((eid, "title", 1, 1))
        bo = _out(["제목"], eid)
        lb.layout([bo], page_no=1, job_id="hdr", layout_result=lr)
        assert not any(r.tag == "heading_blank" for r in bo.rule_trail)

    def test_line_wrap_applied_but_not_in_rule_trail(self, lb, tmp_path) -> None:
        # 32칸 줄바꿈은 적용하되 rule_trail에 기록하지 않는다(조판 서식 규칙 제외).
        eid = uuid4()
        lr = _layout((eid, "sidebar", 1, 0))
        bo = _out(["가" * 40], eid)
        lb.layout([bo], page_no=1, job_id="lw", layout_result=lr)
        lines = [ln for ln in _read_lines(tmp_path, "lw") if ln.strip()]
        assert len(lines) >= 2  # 40칸 → 32+8 분리 (조판 동작 유지)
        assert not any(r.tag == "line_wrap" for r in bo.rule_trail)

    def test_overflow_rate_c6(self, lb) -> None:
        """강제 분리 다발 → line_overflow_rate > 0.30 (C6 트리거 가능)."""
        eid = uuid4()
        lr = _layout((eid, "text", 1, 0))
        rate = lb.layout([_out(["가" * 200], eid)],
                         page_no=1, job_id="ovf", layout_result=lr)
        assert rate > 0.30

    def test_no_overflow_rate_zero(self, lb) -> None:
        eid = uuid4()
        lr = _layout((eid, "text", 1, 0))
        rate = lb.layout([_out(["짧은 줄", "또 한 줄"], eid)],
                         page_no=1, job_id="no-ovf", layout_result=lr)
        assert rate == 0.0

    def test_header_footer_in_page_line(self, lb, tmp_path) -> None:
        """header_footer 요소는 본문 흐름에서 빠지고 페이지행(마지막 줄)에 배치."""
        e1, e2 = uuid4(), uuid4()
        lr = _layout((e1, "text", 1, 0), (e2, "header_footer", 2, 0))
        lb.layout([_out(["본문"], e1), _out(["꼬리"], e2)],
                  page_no=1, job_id="hf", layout_result=lr)
        lines = _read_lines(tmp_path, "hf")
        assert lines[0].strip() == "본문"
        assert "꼬리" not in "\n".join(lines[:-1])  # 본문에 없음
        assert "꼬리" in lines[-1]                    # 페이지행에 배치

    def test_no_layout_result_still_works(self, lb, tmp_path) -> None:
        """layout_result 없이도 조판은 동작(메타 기본값=text)."""
        rate = lb.layout([_out(["가" * 40])], page_no=1, job_id="nolr")
        for line in _read_lines(tmp_path, "nolr"):
            assert _cell_count(line) <= _COLS
        assert rate > 0.0  # 강제분리 발생

    def test_text_paragraph_indent(self, lb, tmp_path) -> None:
        """BBPG 2장2절2 — text 새 문단 첫 줄 3칸, 이어지는 줄 첫칸."""
        eid = uuid4()
        lr = _layout((eid, "text", 1, 0))
        bo = _out(["가" * 50], eid)  # 50 → 첫줄 29(3칸+29) 후 줄바꿈
        lb.layout([bo], page_no=1, job_id="pind", layout_result=lr)
        lines = _read_lines(tmp_path, "pind")
        assert lines[0].startswith("   ")            # 첫 줄 3칸 (조판 동작 유지)
        assert not lines[1].startswith("   ")        # 이어지는 줄 첫칸
        # 들여쓰기는 조판 서식이므로 rule_trail에 기록하지 않는다(태민 정책)
        assert not any(r.tag == "indent" for r in bo.rule_trail)

    def test_list_item_indent(self, lb, tmp_path) -> None:
        """list_item은 3칸 들여만(글머리 tier 추론 안 함)."""
        eid = uuid4()
        lr = _layout((eid, "list_item", 1, 0))
        bo = _out(["1. 환경 설치"], eid)
        lb.layout([bo], page_no=1, job_id="li", layout_result=lr)
        lines = _read_lines(tmp_path, "li")
        assert lines[0] == "   1. 환경 설치"          # 번호 원본 유지 + 3칸 (조판 동작 유지)
        # 글머리 들여쓰기도 조판 서식 → rule_trail 미기록(태민 정책)
        assert not any(r.tag == "indent" for r in bo.rule_trail)

    def test_heading_level1_centered(self, lb, tmp_path) -> None:
        """1단계 제목 가운데 정렬 (BBPG 2장2절1)."""
        eid = uuid4()
        lr = _layout((eid, "title", 1, 1))
        lb.layout([_out(["제목"], eid)], page_no=1, job_id="ctr", layout_result=lr)
        first = next(l for l in _read_lines(tmp_path, "ctr") if l.strip())
        assert first.startswith(" ") and first.strip() == "제목"  # 좌측 패딩 = 가운데

    def test_heading_level3_indent5(self, lb, tmp_path) -> None:
        """3단계 제목 5칸 들여 (BBPG 2장2절1)."""
        eid = uuid4()
        lr = _layout((eid, "title", 1, 3))
        lb.layout([_out(["소제목"], eid)], page_no=1, job_id="h3", layout_result=lr)
        first = next(l for l in _read_lines(tmp_path, "h3") if l.strip())
        assert first.startswith("     ") and first.strip() == "소제목"

    def test_empty_element_no_tagging(self, lb, tmp_path) -> None:
        """내용 없는 요소(빈 줄뿐)는 rule_trail·빈 줄을 만들지 않는다."""
        e1, e2 = uuid4(), uuid4()
        lr = _layout((e1, "text", 1, 0), (e2, "text", 2, 0))
        empty = _out([""], e1)
        real = _out(["내용"], e2)
        lb.layout([empty, real], page_no=1, job_id="empty", layout_result=lr)
        assert empty.rule_trail == []           # 빈 요소 태깅 없음
        assert _read_lines(tmp_path, "empty")[0].strip() == "내용"  # 선두 빈 줄 없음

    def test_orig_page_continuation_prefix(self, lb, tmp_path) -> None:
        """한 원본 페이지가 여러 점자 페이지에 걸치면 2번째부터 알파벳 접두(a39…) (BBPG 1장2절2)."""
        e1, e2 = uuid4(), uuid4()
        lr = _layout((e1, "sidebar", 1, 0), (e2, "page_number", 2, 0))
        body = _out([f"줄{i}" for i in range(30)], e1)  # 30줄 → 2 점자 페이지
        pgn = _out(["⠼⠉⠊"], e2)                          # 원본 39
        lb.layout([body, pgn], page_no=1, job_id="cont", layout_result=lr)
        lines = _read_lines(tmp_path, "cont")
        assert lines[_ROWS - 1].startswith("⠼⠉⠊")        # 1번째 점자페이지: 접두 없음
        assert lines[2 * _ROWS - 1].startswith("⠁⠼⠉⠊")   # 2번째: a 접두

    def test_page_number_left_in_page_line(self, lb, tmp_path) -> None:
        """page_number 요소 → 페이지행 좌측 원본 번호, 점자 페이지번호는 우측."""
        e1, e2 = uuid4(), uuid4()
        lr = _layout((e1, "text", 1, 0), (e2, "page_number", 2, 0))
        lb.layout([_out(["본문"], e1), _out(["⠼⠉⠊"], e2)],  # 원본 39의 점자
                  page_no=1, job_id="pgn", layout_result=lr)
        page_line = _read_lines(tmp_path, "pgn")[-1]
        assert page_line.startswith("⠼⠉⠊")     # 좌측 원본 번호
        assert page_line.rstrip().endswith("⠲")  # 우측 점자 페이지번호
        assert "⠼⠉⠊" not in "\n".join(_read_lines(tmp_path, "pgn")[:-1])  # 본문 아님


class TestBorderIndentB2:
    """B2 회귀: 32칸 테두리에 문단·글머리 들여(3칸)를 더하면 _break_line이 테두리를
    강제 분리해 망가진다. text/list_item 타입이라도 테두리 줄은 들여 미적용 + 경고."""

    def test_is_border_line(self) -> None:
        assert _is_border_line(format_box_top())       # ⠿⠛…⠿ (32칸)
        assert _is_border_line(format_box_bottom())    # ⠿⠶…⠿ (32칸)
        assert _is_border_line(_BOX_BORDER_END * _COLS)  # 표 전체 테두리
        assert not _is_border_line("⠁⠃⠉")             # 일반 텍스트
        assert not _is_border_line(_BOX_BORDER_END * 20)  # 32칸 아님

    def test_border_in_text_not_split(self, lb, tmp_path) -> None:
        eid = uuid4()
        lr = _layout((eid, "text", 1, 0))
        lb.layout([_out([format_box_top()], eid)],
                  page_no=1, job_id="b2t", layout_result=lr)
        first = next(l for l in _read_lines(tmp_path, "b2t") if l.strip())
        assert first == format_box_top()           # 32칸 그대로, 들여·분리 없음
        assert _cell_count(first) == _COLS

    def test_border_in_list_item_not_split(self, lb, tmp_path) -> None:
        eid = uuid4()
        lr = _layout((eid, "list_item", 1, 0))
        lb.layout([_out([format_box_bottom()], eid)],
                  page_no=1, job_id="b2l", layout_result=lr)
        first = next(l for l in _read_lines(tmp_path, "b2l") if l.strip())
        assert first == format_box_bottom()
        assert _cell_count(first) == _COLS

    def test_titled_border_in_text_not_split(self, lb, tmp_path) -> None:
        # 제목(범례) 포함 테두리는 내부에 빈칸이 있어 단어경계 분리가 더 잘 일어남
        from app.ai.braille.translator import substitute_tags
        eid = uuid4()
        border = substitute_tags("<!표윗테두리>범례<!/표윗테두리>")
        assert _cell_count(border) == _COLS
        lr = _layout((eid, "text", 1, 0))
        lb.layout([_out([border], eid)], page_no=1, job_id="b2tt", layout_result=lr)
        first = next(l for l in _read_lines(tmp_path, "b2tt") if l.strip())
        assert first == border                      # 분리 없이 보존

    def test_normal_text_still_indented(self, lb, tmp_path) -> None:
        # 테두리 없는 일반 text는 기존대로 3칸 들여 유지(과잉 억제 방지)
        eid = uuid4()
        lr = _layout((eid, "text", 1, 0))
        lb.layout([_out(["일반 문단"], eid)], page_no=1, job_id="b2n", layout_result=lr)
        first = next(l for l in _read_lines(tmp_path, "b2n") if l.strip())
        assert first.startswith("   ")


class TestBulletMarkerKBR72:
    """KBR 제72항: list_item 첫머리 ○□△ 숨김표 글리프 → 글머리형 정정 (글머리 분기)."""

    @staticmethod
    def _bo(line: str, rule_trail=None) -> BrailleOutput:
        from app.ai.braille.regulations import make_rule
        if rule_trail is None:
            rule_trail = [make_rule("KBR-6.13.49", span_start=0, span_end=3, tag="symbol")]
        return BrailleOutput(element_id=str(uuid4()), braille_lines=[line], rule_trail=rule_trail)

    def test_동그라미_글머리_변환(self) -> None:
        bo = self._bo("⠸⠚⠇⠁⠃")           # ○ 숨김표(⠸⠚⠇) + 내용 ⠁⠃
        LayoutBraille()._apply_bullet_marker(bo)
        assert bo.braille_lines[0] == "⠸⠚⠁⠃"   # 꼬리 ⠇ 제거 → 글머리 ⠸⠚
        rids = [r.rule_id for r in bo.rule_trail]
        assert "KBR-6.14.72" in rids            # 글머리로 정정
        assert "KBR-6.13.49" not in rids        # 숨김표 entry 제거

    def test_네모_세모_글머리(self) -> None:
        for hidden, bullet in [("⠸⠄⠇", "⠸⠄"), ("⠸⠬⠇", "⠸⠬")]:
            bo = self._bo(hidden + "⠁")
            LayoutBraille()._apply_bullet_marker(bo)
            assert bo.braille_lines[0] == bullet + "⠁"
            assert any(r.rule_id == "KBR-6.14.72" for r in bo.rule_trail)

    def test_숨김표아니면_불변(self) -> None:
        bo = self._bo("⠁⠃⠉", rule_trail=[])    # 첫머리가 글머리 글리프 아님
        LayoutBraille()._apply_bullet_marker(bo)
        assert bo.braille_lines[0] == "⠁⠃⠉"
        assert bo.rule_trail == []

    def test_format_element_list_item_3칸들여_글머리(self) -> None:
        from app.ai.braille.regulations import make_rule
        bo = BrailleOutput(
            element_id=str(uuid4()), braille_lines=["⠸⠚⠇⠁⠃"],
            rule_trail=[make_rule("KBR-6.13.49", span_start=0, span_end=3, tag="symbol")],
        )
        lines, _ = LayoutBraille()._format_element(bo, "list_item", 0)
        assert lines[0] == "   ⠸⠚⠁⠃"            # 3칸 들여 + 글머리형
        assert any(r.rule_id == "KBR-6.14.72" for r in bo.rule_trail)
