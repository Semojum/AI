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
