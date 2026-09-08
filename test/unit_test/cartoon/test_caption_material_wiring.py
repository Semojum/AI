"""캡션 재료 블록(#636)이 초안 조립기까지 배선됐는지 — `⟦재료⟧` 유출 + 주표 안/밖 경계.

배선 전에는 `split_material` 을 읽는 코드가 app/ 에 없어서 `CAPTION_MATERIAL=1` 이면
`⟦재료⟧` 마커와 `못읽음:` 열쇠말이 그대로 점자로 나갔다(실측 3/3 형식 이탈).

경계 근거 — 점역자 주표는 **유형 낱말만** 감싼다(원장 C-D4 채택 2026-09-08).
  「점자 자료 제작 지침」 §5.3.1(1) 2811행 "'만화'를 점역자 주표를 사용하여 5칸에
  표기하고, 한 칸 띈 후 만화 제목을 적는다" · §5.3.3(5) 2827행 "인물명 … 점역자
  주표는 사용하지 않는다".
"""
from __future__ import annotations

import asyncio
from uuid import uuid4

from app.ai.llm.cartoon_opt import CartoonOpt, _material_items
from app.schemas.content import ExtractedContent

_CAP = """만화: 안내자가 전시물 앞에서 학생들에게 설명하고 있음.
⟦재료⟧
상황: 안내자가 전시물 앞에서 학생들에게 설명하고 있음.
대사: 왕: 이것이 무엇인가?
대사: 학생1: 백제의 금동대향로입니다.
요소: 전시대 위 물건 3개
못읽음: 뒤쪽 안내판 글씨
없음: 말풍선 꼬리"""


def _desc(caption: str) -> str:
    ext = ExtractedContent(element_id=uuid4(), ocr_confidence=1.0, corrected_text=caption)
    opt = asyncio.run(CartoonOpt().optimize([ext], "ZERO"))[0]
    return opt.drafts[opt.selected_idx].text


def test_재료_마커와_열쇠말이_초안에_안_샌다():
    out = _desc(_CAP)
    for leak in ("⟦재료⟧", "요소:", "못읽음:", "없음:", "상황:"):
        assert leak not in out, (leak, out)


def test_만화_머리줄은_5칸_주표는_유형어만():
    """§5.3.1(1) L2811 — "'만화'를 점역자 주표를 사용하여 **5칸**에 표기하고,
    **한 칸 띈 후** 만화 제목을 적는다." 쌍점을 안 쓰고 주표는 '만화' 만 감싼다.
    gold 실측도 5칸이다(corpus/pages/braille 전수 11/11 = 100%).
    """
    out = _desc(_CAP)
    lines = out.split("\n")
    head = next(l for l in lines if "안내자가" in l)
    assert head.startswith("<!4칸><!주>만화<!/주> "), head    # 5칸 · 주표는 유형어만
    # 화이트리스트에 없는 화자(`왕`·`학생1`)도 주 밖이다 — 재료가 경계를 이미 그었다.
    for say in ("왕: 이것이 무엇인가?", "학생1: 백제의 금동대향로입니다."):
        ln = next(l for l in lines if say in l)
        assert "<!주>" not in ln and "<!/주>" not in ln, ln


def test_대사는_한_번만_실린다():
    out = _desc(_CAP)
    assert out.count("백제의 금동대향로입니다") == 1, out


def test_장면_줄은_상황이_둘_이상일_때만():
    # gold 27/27 이 한 장면이라 `장면 N` 줄이 0건이다.
    assert "장면" not in "".join(t for _lv, t in _material_items(
        [("상황", "한 남성이 자료를 가리키고 있음."), ("대사", "남성: 보십시오.")])[1])
    _head, items = _material_items(
        [("상황", "학생이 묻고 있음."), ("상황", "선생님이 답하고 있음.")])
    assert [t for lv, t in items if lv == 1] == ["장면 1", "장면 2"], items


def test_재료가_없으면_종전_경로_그대로():
    out = _desc("만화: 두 사람이 마주 앉아 이야기한다\n학생: 안녕?")
    assert "학생: 안녕?" in out
