"""#1416 상자 안 마지막 요소가 표면 상자는 표 뒤에서 닫힌다.

묵자 사회 · 문화 본문 108쪽: 상자 하나가 설명 글과 그 아래 표를 함께 두른다. 닫는 태그는 글 요소에만 달 수 있어 종전에는
표 앞에서 닫혔다. 추출이 표에 `box_close_after` 를 남기고, 파이프라인이 읽기순서를 다 매긴 뒤 표 다음 글 요소 머리로 옮긴다.
아래 테두리 점형은 「점자 도서 제작 지침」 1장 2절 5. 2)(2)(재추출 394행): 첫 칸 `=`(⠿)으로 시작해 중간을 `7`(⠶)로 채운다.
"""
from uuid import uuid4

from app.ai.braille.translator import translate_tagged_text
from app.ai.preprocessor.pdf_analyzer import tag_boxed_elements
from app.core.pipeline import _mark_table_box_levels, _move_box_closes
from app.schemas.content import ExtractedContent
from app.schemas.layout import BBoxItem

RECT = [100.0, 100.0, 900.0, 400.0]
CLOSE = "<!상자끝><!/상자끝>"
BOTTOM = "⠿" + "⠶" * 30 + "⠿"


def _els(*kinds):
    ys = iter(range(120, 400, 60))
    return [{"type": k, "bbox": [150, (y := next(ys)), 850, y + 40],
             "content": "<table><tr><td>가</td></tr></table>" if k == "table" else f"글 {i}"} for i, k in enumerate(kinds)]


def test_마지막이_표면_표에_닫는_표지를_남기고_태그는_마지막_글에_둔다():
    els = _els("text", "table")
    assert tag_boxed_elements(els, [RECT]) == 1
    assert els[0]["content"].endswith(CLOSE)
    assert els[1]["box_close_after"] == [[1, CLOSE]]


def test_표가_가운데면_표지가_없다():
    els = _els("text", "table", "text")
    tag_boxed_elements(els, [RECT])
    assert "box_close_after" not in els[1] and els[2]["content"].endswith(CLOSE)


def _page(types, texts):
    items, ext = [], {}
    for k, (t, txt) in enumerate(zip(types, texts), start=1):
        eid = uuid4()
        items.append(BBoxItem(element_id=eid, type=t, bbox=(0, k * 10, 100, k * 10 + 5), reading_order=k))
        ext[eid] = ExtractedContent(element_id=eid, corrected_text=txt, ocr_confidence=1.0, box_level=1 if t == "table" else 0)
    return items, ext


def test_표_다음_글_요소_머리로_옮기고_표는_상자_안이_된다():
    items, ext = _page(["text", "table", "text"], [f"<!상자><!/상자>\n설명 글\n{CLOSE}", "<table></table>", "① 다음 글"])
    assert _move_box_closes(items, ext, {items[1].element_id: [[1, CLOSE]]}) == 1
    a, t, b = (ext[it.element_id] for it in items)
    assert a.corrected_text == "<!상자><!/상자>\n설명 글"
    assert b.corrected_text == f"{CLOSE}\n① 다음 글"
    _mark_table_box_levels(items, ext)
    assert t.box_level == 1                                   # 종전에는 상자 밖이라 0
    assert translate_tagged_text(b.corrected_text).split("\n")[0] == BOTTOM


def test_안쪽부터_닫는다():
    inner = "<!상자끝2><!/상자끝2>"
    items, ext = _page(["text", "table", "text"], [f"글\n{inner}\n{CLOSE}", "<table></table>", "다음"])
    _move_box_closes(items, ext, {items[1].element_id: [[1, CLOSE], [2, inner]]})
    assert ext[items[2].element_id].corrected_text == f"{inner}\n{CLOSE}\n다음"
    assert ext[items[0].element_id].corrected_text == "글"


def test_다음이_글이_아니거나_없으면_그대로다(monkeypatch):
    for types in (["text", "table", "table"], ["text", "table"]):
        texts = [f"글\n{CLOSE}", "<table></table>", "<table></table>"][:len(types)]
        items, ext = _page(types, texts)
        assert _move_box_closes(items, ext, {items[1].element_id: [[1, CLOSE]]}) == 0
        assert ext[items[0].element_id].corrected_text.endswith(CLOSE)
    items, ext = _page(["text", "table", "text"], [f"글\n{CLOSE}", "<table></table>", "다음"])
    monkeypatch.setenv("BOX_CLOSE_AFTER_TABLE", "0")
    assert _move_box_closes(items, ext, {items[1].element_id: [[1, CLOSE]]}) == 0
