"""곁단 '개념 체크' 글상자(#1155) — 제목 → 번호 문항 → 정답 → 번호 답 묶음을 글상자로 감싸고 제목은 위 테두리로.

gold 꼴: `=GGGG @RC:5 ;NF[ GGG…=`(위 테두리에 '개념 체크'), 동아시아사 body p0009 · 생활과 윤리 body p0096.
"""
from uuid import uuid4

from app.core.pipeline import _box_concept_checks
from app.schemas.content import ExtractedContent
from app.schemas.layout import BBoxItem


def _page(*specs):
    items, ext = [], {}
    for k, (etype, text) in enumerate(specs, start=1):
        eid = uuid4()
        items.append(BBoxItem(element_id=eid, type=etype, bbox=(0, 0, 1, 1), reading_order=k))
        ext[eid] = ExtractedContent(element_id=eid, corrected_text=text)
    return items, ext


GROUP = [("title", "개념 체크"), ("text", "1.  동아시아의 (   ) 시대 인류로는 …"), ("text", "2.  신석기 시대에 (   ) …"),
         ("title", "정⃞답⃞"), ("text", "1. 구석기  2. 창장강  3. 조몬")]


def _texts(items, ext):
    return [ext[it.element_id].corrected_text for it in sorted(items, key=lambda b: b.reading_order)]


def test_개념_체크_묶음을_글상자로_감싸고_제목을_올린다(monkeypatch):
    monkeypatch.delenv("CONCEPT_CHECK_BOX", raising=False)
    items, ext = _page(("text", "본문"), *GROUP, ("text", "다음 본문"))
    _box_concept_checks(items, ext)
    t = _texts(items, ext)
    assert "개념 체크" not in t                                      # 제목 요소는 위 테두리로 갔다
    assert t[1].startswith("<!상자>개념 체크<!/상자>\n1.")
    assert t[4].endswith("\n<!상자끝><!/상자끝>") and t[3] == "정⃞답⃞"
    assert t[0] == "본문" and t[-1] == "다음 본문" and len(items) == len(ext) == 6


def test_정답이_없거나_사이에_다른_글이_끼면_그대로(monkeypatch):
    monkeypatch.delenv("CONCEPT_CHECK_BOX", raising=False)
    for specs in (GROUP[:3], [GROUP[0], GROUP[1], ("text", "본문 한 줄"), *GROUP[3:]]):
        items, ext = _page(*specs)
        before = _texts(items, ext)
        _box_concept_checks(items, ext)
        assert _texts(items, ext) == before


def test_이미_상자_안이면_그대로(monkeypatch):
    monkeypatch.delenv("CONCEPT_CHECK_BOX", raising=False)
    items, ext = _page(("text", "<!상자><!/상자>\n자료"), *GROUP, ("text", "끝\n<!상자끝><!/상자끝>"))
    before = _texts(items, ext)
    _box_concept_checks(items, ext)
    assert _texts(items, ext) == before


def test_끈_스위치는_그대로(monkeypatch):
    monkeypatch.setenv("CONCEPT_CHECK_BOX", "0")
    items, ext = _page(*GROUP)
    before = _texts(items, ext)
    _box_concept_checks(items, ext)
    assert _texts(items, ext) == before
