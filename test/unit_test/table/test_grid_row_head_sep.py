"""#839 — 격자 표의 행 머리 뒤 구분자.

종전엔 `_render_grid` 가 그 자리에 쌍점을 **리터럴로** 박아, 표가 늘 쌍점으로 나갔다.
구분자 판정(`_sep_word_level`)은 이미 있었는데 `_render_unfold` 만 그 자리를 지났다.

규정 근거 — 「점자 도서 제작 지침」 재추출 1647행 "표의 셀과 셀 사이는 두 칸을 띄어
구분한다" · 「점자 자료 제작 지침」 §3.1(1)② "열 항목을 두 칸씩 띄어 풀어 적는다".
쌍점은 표 절 어디에도 없다 — 문장 수준 셀에 한한 도서 관행이다.
"""
import importlib
import os

import pytest

from app.ai.braille import table_braille as tb

# 낱말 수준 — gold(사회문화 p101)는 행 머리 뒤를 두 칸으로 적는다.
WORD_TABLE = "구분|2020|2021\n초혼|88.9|89.2\n재혼|11.1|10.8"

# 문장 수준 — 중앙값 셀이 14셀을 넘는다. 쌍점이 남아야 한다.
SENT_TABLE = ("구분|설명\n"
              "계층 이동의 의미|한 개인이나 집단의 사회적 위치가 바뀌는 현상을 뜻한다\n"
              "수직 이동의 특징|계층적 위치가 상승하거나 하강하는 이동을 가리킨다\n"
              "수평 이동의 특징|같은 계층 안에서 자리만 옮겨 가는 이동을 가리킨다")

COLON = "⠐⠂"


def _body(text: str) -> list[str]:
    """테두리·행 구분선을 뺀 내용 줄."""
    return [ln for ln in tb._render_grid(text)
            if ln.strip("⠀") and not ln.startswith(("⠿", "⠐⠐"))]


class TestGridRowHeadSeparator:
    def test_낱말_수준은_두_칸으로_적는다(self) -> None:
        body = _body(WORD_TABLE)
        assert body, "내용 줄이 없다"
        for ln in body:
            assert COLON not in ln, f"낱말 수준 표에 쌍점이 남았다: {ln!r}"

    def test_이슈_실물이_gold_모양으로_나온다(self) -> None:
        """사회문화 p101 '초혼  88.9  89.2' — 행 머리 뒤가 두 칸."""
        head = tb._translate("초혼")
        val = tb._translate("88.9")
        row = next(ln for ln in _body(WORD_TABLE) if head in ln)
        assert head + "⠀⠀" + val in row, f"행 머리 뒤가 두 칸이 아니다: {row!r}"

    def test_문장_수준은_쌍점을_지킨다(self) -> None:
        """관행이 쌍점인 자리까지 없애지 않는다 — 판정은 `_sep_word_level` 이 한다."""
        assert any(COLON in ln for ln in _body(SENT_TABLE)), "문장 수준 표에서 쌍점이 사라졌다"

    def test_값_사이는_여전히_두_칸이다(self) -> None:
        row = next(ln for ln in _body(WORD_TABLE) if tb._translate("초혼") in ln)
        assert tb._translate("88.9") + "⠀⠀" + tb._translate("89.2") in row

    def test_되돌림_스위치가_산다(self) -> None:
        os.environ["TABLE_GRID_SEP"] = "colon"
        try:
            assert any(COLON in ln for ln in _body(WORD_TABLE)), "TABLE_GRID_SEP=colon 이 안 먹는다"
        finally:
            os.environ.pop("TABLE_GRID_SEP", None)
        # 스위치를 내리면 곧바로 되돌아온다 — 임포트 때 굳지 않는다.
        assert not any(COLON in ln for ln in _body(WORD_TABLE))

    def test_두_렌더러가_같은_판정을_쓴다(self) -> None:
        """`_render_grid` 와 `_render_unfold` 가 같은 조항에 다른 답을 내면 안 된다(#839 원인)."""
        for text in (WORD_TABLE, SENT_TABLE):
            rows = [[c.strip() for c in r.split("|")] for r in text.splitlines() if r.strip()]
            want_colon = not tb._sep_word_level(rows)
            got_colon = any(COLON in ln for ln in _body(text))
            assert got_colon is want_colon, f"판정과 출력이 어긋난다: {text.splitlines()[0]!r}"


class TestRegulationMode:
    @pytest.fixture()
    def regulation(self):
        os.environ["BRAILLE_STYLE"] = "regulation"
        importlib.reload(tb)
        yield tb
        os.environ.pop("BRAILLE_STYLE", None)
        importlib.reload(tb)

    def test_규정_모드는_문장_표에도_쌍점을_안_쓴다(self, regulation) -> None:
        """쌍점은 규정 근거가 없다(지침 1647행은 두 칸 하나뿐)."""
        body = [ln for ln in regulation._render_grid(SENT_TABLE)
                if ln.strip("⠀") and not ln.startswith(("⠿", "⠐⠐"))]
        assert body
        for ln in body:
            assert COLON not in ln, f"규정 모드에 쌍점이 새어 나왔다: {ln!r}"
