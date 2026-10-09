"""ZERO 쪽에서 쪽 번호가 꼬리말 글과 한 블록으로 묶여 페이지행 원본 쪽 번호가 빠지던 문제(이슈 #1247).

좌표는 d8c 경계 파일 그대로(2x 픽셀). 생명과학 Ⅰ body p0085: 꼬리말 `06강 항상성  85` 가 차례 첫 블록이고
그래프 눈금 `0` 이 숫자만 든 블록이라 `page_number` 로 잡혀 페이지행 원본 번호 자리를 차지했다.
"""
import pytest

from app.core import pipeline
from app.core.pipeline import _blocks_with_bbox, _parse_txt_result

H = 1474
FOOT_TAIL = {"content": "06강 항상성  85", "bbox": [977, 1393, 1077, 1417]}
FOOT_HEAD = {"content": "24  2027학년도 EBS 수능특강 생활과 윤리", "bbox": [90, 1393, 420, 1417]}
TICK = {"content": "0", "bbox": [558, 360, 564, 374]}
BODY = {"content": "그림은 사람의 혈당 조절 과정을 나타낸 것이다.", "bbox": [125, 300, 900, 330]}


@pytest.fixture(autouse=True)
def _form_off(monkeypatch):
    monkeypatch.setattr(pipeline, "_ITEM_CODE_FORM", "off")


def _kinds(els):
    return [(e["type"], e["content"]) for e in sorted(els, key=lambda e: e["order"])]


def test_뒤_숫자를_쪽_번호로_떼어_맨_앞에_둔다():
    els = _blocks_with_bbox([BODY, TICK, FOOT_TAIL], H)
    assert _kinds(els) == [("page_number", "85"), ("text", BODY["content"]), ("page_number", "0"), ("text", "06강 항상성")]
    assert "bbox" not in els[0]


def test_앞_숫자도_뗀다():
    assert _kinds(_blocks_with_bbox([BODY, FOOT_HEAD], H))[:2] == [("page_number", "24"), ("text", BODY["content"])]


def test_가장_아래_블록이_아니거나_아래_띠_밖이면_안_뗀다(monkeypatch):
    choice = {"content": "⑤ 질문 2, 질문 3  질문 3  질문 1", "bbox": [125, 1340, 766, 1362]}
    assert _kinds(_blocks_with_bbox([choice, FOOT_TAIL], H))[:2] == [("page_number", "85"), ("text", choice["content"])]
    assert _kinds(_blocks_with_bbox([BODY, choice], H)) == [("text", BODY["content"]), ("text", choice["content"])]
    assert _kinds(_blocks_with_bbox([BODY, FOOT_TAIL], 0))[-1] == ("text", "06강 항상성  85")
    monkeypatch.setenv("ZERO_FOOT_PAGE_NUMBER", "0")
    assert _kinds(_blocks_with_bbox([BODY, FOOT_TAIL], H))[-1] == ("text", "06강 항상성  85")


def test_떼어_낸_번호가_첫_쪽_번호로_남고_발문에_안_붙는다():
    meta = {"extraction_method": "TEXT_NATIVE", "bbox_space": "pixel", "image_width": 1168, "image_height": H}
    lay, em, _ = _parse_txt_result({"meta": meta, "elements": _blocks_with_bbox([BODY, TICK, FOOT_TAIL], H)}, "p")
    got = [(b.type, em[b.element_id].corrected_text) for b in sorted(lay.elements, key=lambda b: b.reading_order)]
    assert got[0] == ("page_number", "85")
    assert ("text", "06강 항상성") in got
