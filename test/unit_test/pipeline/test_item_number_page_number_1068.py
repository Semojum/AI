"""쪽 번호로 분류된 문항 번호가 점자에서 사라지던 문제(이슈 #1068).

좌표는 d8c 경계 파일 그대로. ① ZERO 층 블록은 발문 상자가 번호 자리까지 덮는다(생활과 윤리 body p0024, 픽셀 좌표).
② 번호 옆이 발문이 아닌 표면 붙일 짝이 없다(언어와 매체 body p0053, 0~1000 정규화). 그대로 두면 `02` 가 페이지행 원본
쪽 번호가 되고 진짜 쪽 번호 `53` 이 본문으로 밀린다. gold 는 `02 (26004-0022) 〈보기〉의 …` 다.
"""
from uuid import uuid4

import pytest

from app.core import pipeline
from app.core.pipeline import _parse_txt_result


@pytest.fixture(autouse=True)
def _form_off(monkeypatch):
    monkeypatch.setattr(pipeline, "_ITEM_CODE_FORM", "off")


def _el(typ, content, bbox):
    return {"id": str(uuid4()), "type": typ, "content": content, "bbox": bbox}


def _parse(els, meta):
    lay, em, _ = _parse_txt_result({"meta": meta, "elements": els}, "p")
    return [(b.type, em[b.element_id].corrected_text) for b in sorted(lay.elements, key=lambda b: b.reading_order)]


ZERO = {"extraction_method": "TEXT_NATIVE", "bbox_space": "pixel", "image_width": 1190, "image_height": 1502}
MINERU = {"extraction_method": "OCR", "bbox_space": "norm1000", "image_width": 1167, "image_height": 1474}

# 생활과 윤리 body p0024 — 번호 [92,691,123,736] · 발문 [92,705,549,757](왼쪽 끝이 같다)
P0024 = [
    _el("text", "다음 사상가의 관점에서 <문제 상황> 속 A에게 제시할 조언으로 가장 적절한 것은?", [92, 705, 549, 757]),
    _el("text", "최대 행복의 원리를 따를 경우", [107, 789, 539, 942]),
    _el("page_number", "06", [92, 691, 123, 736]),
    _el("text", "24", [92, 1440, 120, 1460]),
]
# 언어와 매체 body p0053 — 번호 아래가 바로 표다
P0053 = [
    _el("header_footer", "[26004-0022]", [233, 105, 313, 120]),
    _el("page_number", "02", [154, 124, 195, 151]),
    _el("table", "<table><tr><td>조음 방법</td></tr></table>", [238, 158, 910, 575]),
    _el("text", "〈보기〉의 자음 체계를 참고하여 탐구한 내용으로 적절하지 않은 것은?", [200, 600, 900, 640]),
    _el("page_number", "53", [85, 945, 114, 960]),
]


def test_왼쪽_끝이_같은_발문에_번호가_붙는다():
    out = _parse(P0024, ZERO)
    assert ("text", "06 다음 사상가의 관점에서 <문제 상황> 속 A에게 제시할 조언으로 가장 적절한 것은?") in out
    assert all(t != "06" for _, t in out)


def test_왼쪽_끝_붙이기를_끄면_종전(monkeypatch):
    monkeypatch.setenv("ITEM_NUMBER_JOIN_ALIGNED", "0")
    monkeypatch.setenv("ITEM_NUMBER_UNPAGE", "0")
    out = _parse(P0024, ZERO)
    assert ("page_number", "06") in out


def test_발문이_이미_번호로_시작하면_안_겹친다():
    els = [_el("text", "06 다음 사상가의 관점에서 고른 것은?", [92, 705, 549, 757]), _el("page_number", "06", [92, 691, 123, 736])]
    out = _parse(els, ZERO)
    assert ("text", "06 다음 사상가의 관점에서 고른 것은?") in out and ("text", "06 06 다음 사상가의 관점에서 고른 것은?") not in out


def test_종전_짝이_있으면_왼쪽_끝_짝은_안_본다():
    els = [_el("page_number", "02", [145, 603, 186, 632]),
           _el("text", "오른쪽 발문", [222, 607, 538, 626]),
           _el("text", "왼쪽 끝이 같은 다른 글", [145, 610, 900, 700])]
    out = _parse(els, MINERU)
    assert ("text", "02 오른쪽 발문") in out and ("text", "왼쪽 끝이 같은 다른 글") in out


def test_붙일_짝이_없는_가운데_번호는_본문으로_쪽_번호는_그대로():
    out = _parse(P0053, MINERU)
    assert ("text", "02") in out and ("page_number", "53") in out
    assert ("page_number", "02") not in out


def test_본문_되돌리기를_끄면_종전(monkeypatch):
    monkeypatch.setenv("ITEM_NUMBER_UNPAGE", "0")
    out = _parse(P0053, MINERU)
    assert ("page_number", "02") in out
