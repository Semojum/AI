"""글상자 안 표는 한 단계 아래 테두리로 그린다(#1110) — 「점자 도서 제작 지침」 1장 2절 5. 2)(3) 속글상자 ·
(5) 위계 3단계(재추출 396~397행 · 451~457행). 2단계 = 위 ⠖⠒…⠲ · 아래 ⠓⠒…⠚.

표에는 상자 태그를 못 다니 추출 때 사각형 안 · 태그 구간 안 표에 경계 키 `box_level` 을 남기고
(`pdf_analyzer.tag_boxed_elements`), 최종 읽기순서에서도 상자 안일 때만 쓴다(`pipeline._mark_table_box_levels`).
"""
from uuid import uuid4

from app.ai.braille.table_braille import TableBraille, _TBL_BOT, _TBL_TOP, _relevel_borders
from app.ai.preprocessor.pdf_analyzer import tag_boxed_elements
from app.core.pipeline import _mark_table_box_levels
from app.schemas.content import ExtractedContent, LLMOutput
from app.schemas.layout import BBoxItem

L2_TOP = "⠖" + "⠒" * 30 + "⠲"
L2_BOT = "⠓" + "⠒" * 30 + "⠚"
L3_TOP = "⠖" + "⠐" * 30 + "⠲"


def test_다시_그리기는_테두리_줄만_바꾼다():
    lines = [_TBL_TOP, "⠀⠀⠁⠃", _TBL_BOT]
    _relevel_borders(lines, 2)
    assert lines == [L2_TOP, "⠀⠀⠁⠃", L2_BOT]


def test_위아래_짝이_없으면_그대로_둔다():
    lines = ["⠿⠛⠛⠀⠐⠶⠘⠥⠈⠕⠶⠂⠀" + "⠛" * 18 + "⠿", "⠀⠀⠁⠃", _TBL_BOT]   # 제목 박은 위 테두리
    before = list(lines)
    _relevel_borders(lines, 2)
    assert lines == before


def _table(eid):
    return LLMOutput(element_id=eid, corrected_text="구분|2000년|2005년\n초혼|88.9|89.2",
                     render_mode="table_grid", routing_tier="ZERO")


def test_상자_안_표는_모든_초안이_2단계(monkeypatch):
    monkeypatch.delenv("TABLE_BOX_LEVEL", raising=False)
    eid = uuid4()
    bo = TableBraille({eid: 1}).translate([_table(eid)])[0]
    assert bo.braille_lines[0] == L2_TOP and bo.braille_lines[-1] == L2_BOT
    for d in bo.drafts:
        assert _TBL_TOP not in d.braille_lines and _TBL_BOT not in d.braille_lines, d.label


def test_2단계_상자_안_표는_3단계():
    eid = uuid4()
    bo = TableBraille({eid: 2}).translate([_table(eid)])[0]
    assert bo.braille_lines[0] == L3_TOP


def test_상자_밖_표와_끈_스위치는_1단계(monkeypatch):
    eid = uuid4()
    assert TableBraille().translate([_table(eid)])[0].braille_lines[0] == _TBL_TOP
    monkeypatch.setenv("TABLE_BOX_LEVEL", "0")
    assert TableBraille({eid: 1}).translate([_table(eid)])[0].braille_lines[0] == _TBL_TOP


def _el(typ, y, content="본문"):
    return {"id": str(uuid4()), "type": typ, "content": content, "bbox": [10, y, 90, y + 8]}


def test_추출은_사각형_안_표에_키를_단다():
    els = [_el("text", 40, "첫 줄 본문이 길어서 제목으로 안 올라간다"), _el("table", 55, "<table></table>"),
           _el("text", 70), _el("table", 85, "<table></table>"),  # 끝 글 뒤 — 그려지는 자리는 점역이 다시 본다
           _el("table", 200, "<table></table>")]                 # 사각형 밖
    assert tag_boxed_elements(els, [[0, 0, 100, 100]]) == 1
    assert [e.get("box_level", 0) for e in els if e["type"] == "table"] == [1, 1, 0]


def _page(*specs):
    items, ext = [], {}
    for k, (etype, text, lv) in enumerate(specs, start=1):
        eid = uuid4()
        items.append(BBoxItem(element_id=eid, type=etype, bbox=(0, 0, 1, 1), reading_order=k))
        ext[eid] = ExtractedContent(element_id=eid, corrected_text=text, box_level=lv)
    return items, ext


def test_최종_읽기순서에서도_상자_안일_때만_위계를_남긴다():
    items, ext = _page(
        ("text", "<!상자>자료<!/상자>\n본문", 0),
        ("table", "<table></table>", 1),                       # 경계 키 1 · 상자 안 → 1
        ("text", "끝\n<!상자끝><!/상자끝>", 0),
        ("table", "<table></table>", 1),                       # 재배정으로 상자 밖에 그려진다 → 0
    )
    _mark_table_box_levels(items, ext)
    assert [ext[it.element_id].box_level for it in items if it.type == "table"] == [1, 0]


def test_찢어진_상자_사이에_낀_본문_표는_키가_없으면_그대로():
    """동아시아사 p0033 — 재배정이 곁단 상자 여는 태그와 닫는 태그를 갈라 본문 표가 그 사이에 끼었다."""
    items, ext = _page(
        ("text", "<!상자>쿠릴타이<!/상자> 지도 설명", 0),
        ("text", "본문", 0),
        ("table", "<table></table>", 0),
        ("text", "울루스\n<!상자끝><!/상자끝>", 0),
    )
    _mark_table_box_levels(items, ext)
    assert [ext[it.element_id].box_level for it in items if it.type == "table"] == [0]


def test_바깥_상자_구간에만_든_안쪽_사각형_표는_한_단계만_올린다():
    """사각형으로는 2단계 상자 안인데 재배정으로 안쪽 상자 태그 밖(바깥 상자 안)에 그려지면 1이다."""
    items, ext = _page(
        ("text", "<!상자><!/상자>\n바깥", 0),
        ("text", "<!상자2><!/상자2>\n안쪽\n<!상자끝2><!/상자끝2>", 0),
        ("table", "<table></table>", 2),
        ("text", "끝\n<!상자끝><!/상자끝>", 0),
    )
    _mark_table_box_levels(items, ext)
    assert [ext[it.element_id].box_level for it in items if it.type == "table"] == [1]
