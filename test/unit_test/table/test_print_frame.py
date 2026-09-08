"""표 묵자 초안에도 테두리·구분선을 그린다.

점자 렌더러(`_render_grid`·`_render_linear`)는 【글상자】 테두리와 【표 구분선】을 내는데
묵자 초안만 안 냈다. 그래서 FE 피커에서 **다섯 안이 죄다 테두리 없는 줄글**로 보였고
`테두리+구분선`·`테두리만` 이라는 이름과 어긋났다(unfold 와 linear 는 출력이 아예 같았다).
"""
from app.ai.llm.table_opt import _print_drafts

T = "후보|득표수|득표율\n가 후보|3,420|40.0\n나 후보|2,907|34.0"


def _drafts():
    return {d.label: (d.text or "") for d in _print_drafts(T, "unfold")[0]}


def test_다섯_안이_모두_다르다():
    texts = list(_drafts().values())
    assert len(set(texts)) == len(texts), "초안이 겹치면 점역사가 고를 이유가 없다"


def test_테두리_구분선_안은_둘_다_있다():
    t = _drafts()["테두리+구분선"]
    assert t.startswith("┌") and t.rstrip().endswith("└") and "├" in t


def test_테두리만_안은_구분선이_없다():
    t = _drafts()["테두리만"]
    assert t.startswith("┌") and t.rstrip().endswith("└") and "├" not in t


def test_풀어쓰기와_번호체계는_테두리를_안_두른다():
    # 표를 풀어 쓰는 형식이라 테두리가 뜻을 갖지 않는다.
    for lb in ("테두리 없음", "번호 체계"):
        assert "┌" not in _drafts()[lb]


def test_전치_주는_테두리_밖이다():
    t = _drafts()["행열 바꿈"]
    assert t.split("\n")[0].startswith("[점역자 주]")
    assert t.split("\n")[1] == "┌"


class TestRoundTrip:
    """묵자 테두리를 되읽는다 — 점역사가 고쳐 되돌리는 mode b 입력이 이 형식이다.

    점역기는 `┌ ├ └` 를 모르고 조용히 버려서, 테두리 줄이 통째로 0셀이 되고 소실
    가드가 `[처리 불가: 점역 불가 문자 ┌]` 를 찍었다(대표 지적 2026-09-08).
    우리가 쓴 형식은 우리가 읽어야 한다 — 이 짝이 어긋나면 여기서 깨진다.
    """

    ROWS = [["후보", "득표수", "득표율"],
            ["가 후보", "3,420", "40.0"],
            ["나 후보", "2,907", "34.0"]]

    def _back(self, label):
        from app.ai.braille.table_braille import parse_print_frames, parse_table_tags
        return parse_table_tags(parse_print_frames(_drafts()[label]))

    def test_테두리_안은_칸까지_되살아난다(self):
        for lb in ("테두리+구분선", "테두리만"):
            assert self._back(lb) == self.ROWS, f"{lb} 안의 칸 구분이 깨졌다"

    def test_전치_안은_전치된_격자로_되살아난다(self):
        # 점역사가 보고 고치는 것은 전치된 표다 — 그 모양 그대로 되돌린다.
        assert self._back("행열 바꿈") == [list(c) for c in zip(*self.ROWS)]

    def test_구분선_줄은_칸이_되지_않는다(self):
        assert all("├" not in c for r in self._back("테두리+구분선") for c in r)

    def test_테두리가_없으면_원문_그대로(self):
        from app.ai.braille.table_braille import parse_print_frames
        assert parse_print_frames("그냥 한 줄\n또 한 줄") == "그냥 한 줄\n또 한 줄"

    def test_빈칸_표시는_빈_셀로_돌아온다(self):
        from app.ai.braille.table_braille import parse_print_frames, parse_table_tags
        rows = parse_table_tags(parse_print_frames("┌\n갑: (빈칸)  3\n└"))
        assert rows == [["갑", "", "3"]]

    def test_짝_깨진_테두리는_글자만_지운다(self):
        # 점역사가 아래 테두리를 지우면 표로 되살릴 수 없다. 그 줄을 남기면 0셀이 돼
        # 다시 `[처리 불가]` 가 되므로 글자만 지우고 본문은 그대로 둔다.
        from app.ai.braille.table_braille import parse_print_frames
        assert parse_print_frames("┌\n갑: 1  2\n을: 3  4") == "갑: 1  2\n을: 3  4"

    def test_구분선만_지워도_표로_읽는다(self):
        from app.ai.braille.table_braille import parse_print_frames, parse_table_tags
        assert parse_table_tags(parse_print_frames("┌\n갑: 1  2\n을: 3  4\n└")) == [
            ["갑", "1", "2"], ["을", "3", "4"]]
