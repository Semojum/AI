"""날개 용어 풀이 자리(원장 C-77 · 점역사 답 Q8) — 후치된 날개의 '제목 + 풀이' 덩이를 그 용어가 처음 나온 본문 문단 바로 뒤로.

쪽 끝에 남는 것: 개념 체크 · 정답 상자, 예문((예))이 달린 풀이. 좌표는 사회 책 홀수 쪽 꼴(왼쪽 좁은 날개 · 오른쪽 본문),
MinerU 가 날개를 본문보다 먼저 내보낸 차례다.
"""
from uuid import uuid4

from app.ai.braille.regulations import make_rule
from app.core.pipeline import _anchor_wing_terms, _reorder_columns
from app.schemas.content import ExtractedContent
from app.schemas.layout import BBoxItem

PAGE = [
    ("title", (60, 120, 260, 140), "의무론"),
    ("text", (60, 145, 260, 260), "언제 어디서나 우리가 따라야 할 도덕 법칙이 있다고 보는 윤리"),
    ("title", (60, 330, 260, 350), "공리주의"),
    ("text", (60, 355, 260, 470), "최대 다수의 최대 행복을 행위의 기준으로 삼는 윤리"),
    ("title", (60, 500, 260, 520), "음운"),
    ("text", (60, 525, 260, 590), "(예) 물, 불, 풀"),
    ("title", (60, 600, 260, 620), "개념 체크"),
    ("text", (60, 625, 260, 660), "1. 칸트가 강조한 것은?"),
    ("text", (60, 665, 260, 680), "정답"),
    ("title", (300, 100, 1000, 130), "1. 서양 윤리의 흐름"),
    ("text", (300, 150, 1000, 300), "칸트는 의무론의 입장에서 선의지를 강조하였다."),
    ("text", (300, 320, 1000, 500), "벤담은 공리주의를 내세웠다. 말소리를 이루는 음운도 다룬다."),
    ("text", (300, 520, 1000, 700), "두 윤리는 오늘날에도 함께 쓰인다."),
]


def _page():
    items, ext = [], {}
    for k, (etype, bbox, text) in enumerate(PAGE, start=1):
        eid = uuid4()
        items.append(BBoxItem(element_id=eid, type=etype, bbox=bbox, reading_order=k))
        ext[eid] = ExtractedContent(element_id=eid, corrected_text=text)
    return items, ext


def _texts(items, ext):
    return [ext[it.element_id].corrected_text for it in sorted(items, key=lambda b: b.reading_order)]


def test_용어_풀이를_처음_나온_문단_뒤로(monkeypatch):
    monkeypatch.delenv("WING_TERM_ORDER", raising=False)
    items, ext = _page()
    _anchor_wing_terms(items, ext, _reorder_columns(items))
    assert _texts(items, ext) == [PAGE[i][2] for i in (9, 10, 0, 1, 11, 2, 3, 12, 4, 5, 6, 7, 8)]
    heads = [e for e in ext.values() if e.layout_rules]
    assert sorted(e.corrected_text for e in heads) == ["공리주의", "의무론"]
    assert all(e.layout_rules == ["NLD-2.2.4"] for e in heads)
    assert make_rule("NLD-2.2.4").source == "점자 도서 제작 지침"     # 댕글링 rule_id 아님


def test_끄면_날개는_통째로_쪽_끝(monkeypatch):
    monkeypatch.setenv("WING_TERM_ORDER", "0")
    items, ext = _page()
    _anchor_wing_terms(items, ext, _reorder_columns(items))
    assert _texts(items, ext) == [PAGE[i][2] for i in (9, 10, 11, 12, 0, 1, 2, 3, 4, 5, 6, 7, 8)]
    assert not any(e.layout_rules for e in ext.values())


def test_후치_곁단이_없으면_그대로(monkeypatch):
    monkeypatch.delenv("WING_TERM_ORDER", raising=False)
    items, ext = _page()
    before = _texts(items, ext)
    _anchor_wing_terms(items, ext, [])
    assert _texts(items, ext) == before
