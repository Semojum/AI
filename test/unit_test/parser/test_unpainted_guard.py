"""안 그려지는 글자 버리기(C006) — 유령 글자만 버리는가.

크롭 PDF 는 잘려 나간 바깥 글자를 텍스트 레이어에 그대로 갖고 있다. 화면에는 안
그려지는데 추출기는 읽는다. 판정은 **그 자리에 실제로 무엇이 그려졌는가**로 한다.
"""
import fitz
import pytest

from app.ai.parser.mineru_runner import _drop_unpainted, _is_painted


def _el(bbox, content="본문 글자", etype="text", eid="e1"):
    return {"element_id": eid, "reading_order": 0, "type": etype,
            "bbox": list(bbox), "content": content}


def _page_with_text_top_half():
    """위 절반에만 글을 그린 한 쪽. 아래 절반은 아무것도 안 그려진다."""
    doc = fitz.open()
    page = doc.new_page(width=600, height=800)
    page.insert_text((50, 100), "visible text here", fontsize=20)
    return doc, page


def test_unpainted_element_is_dropped():
    doc, page = _page_with_text_top_half()
    # 아래 절반(600~900/1000)에는 아무것도 안 그려졌다 — 레이어에만 있는 유령이다.
    out = _drop_unpainted([_el((100, 600, 900, 700), "유령 글자")], page, 1)
    assert out == []
    doc.close()


def test_painted_element_is_kept():
    doc, page = _page_with_text_top_half()
    out = _drop_unpainted([_el((50, 90, 700, 150), "visible text here")], page, 1)
    assert len(out) == 1
    doc.close()


@pytest.mark.parametrize("etype", ["image", "chart_graph", "cartoon", "diagram", "table"])
def test_visual_elements_are_never_dropped(etype):
    """그림·표는 안 건드린다 — 요소째 사라지면 거기 무엇이 있었다는 사실조차 못 알린다."""
    doc, page = _page_with_text_top_half()
    out = _drop_unpainted([_el((100, 600, 900, 700), "그림 설명", etype)], page, 1)
    assert len(out) == 1
    doc.close()


def test_empty_content_is_kept():
    """글이 없는 요소는 이 가드의 대상이 아니다(빈 캡션 등 다른 경로가 판단한다)."""
    doc, page = _page_with_text_top_half()
    out = _drop_unpainted([_el((100, 600, 900, 700), "   ")], page, 1)
    assert len(out) == 1
    doc.close()


def test_reading_order_is_renumbered_after_a_drop():
    doc, page = _page_with_text_top_half()
    els = [_el((50, 90, 700, 150), "visible text here", eid="keep"),
           _el((100, 600, 900, 700), "유령", eid="ghost"),
           _el((50, 90, 700, 150), "visible text here", eid="keep2")]
    out = _drop_unpainted(els, page, 1)
    assert [e["element_id"] for e in out] == ["keep", "keep2"]
    assert [e["reading_order"] for e in out] == [0, 1]
    doc.close()


def test_shaded_box_keeps_the_element():
    """음영·테두리가 걸치면 살린다 — 놓치는 쪽이 버리는 쪽보다 안전하다."""
    doc = fitz.open()
    page = doc.new_page(width=600, height=800)
    page.draw_rect(fitz.Rect(60, 480, 540, 560), color=None, fill=(0.94, 0.94, 0.94))
    out = _drop_unpainted([_el((100, 600, 900, 700), "글자는 없고 음영만")], page, 1)
    assert len(out) == 1
    doc.close()


def test_degenerate_bbox_is_kept():
    """잴 수 없는 자리는 살린다."""
    doc, page = _page_with_text_top_half()
    assert _is_painted(page.get_pixmap(dpi=100), [500, 500, 500, 500]) is True
    doc.close()


def test_rotated_page_is_left_alone():
    """회전 지면은 손대지 않는다 — bbox 와 렌더가 다른 좌표계라 오검출이 남는다.

    보정 네 가지를 회전 지면 텍스트 요소 160개에 재 봤는데 가장 나은 것도 93%였다.
    이 가드의 기준은 오검출 0 이라 93%로는 못 켠다(코퍼스 270° 478쪽 실측).
    """
    doc = fitz.open()
    page = doc.new_page(width=600, height=800)
    page.insert_text((50, 100), "visible text here", fontsize=20)
    page.set_rotation(270)
    ghost = _el((100, 600, 900, 700), "회전 지면의 유령")
    assert len(_drop_unpainted([ghost], page, 1)) == 1
    doc.close()
