"""글상자 안 표는 한 단계 아래 테두리로 그린다(#1110) — 「점자 도서 제작 지침」 1장 2절 5. 2)(3) 속글상자 ·
(5) 위계 3단계(재추출 396~397행 · 451~457행). 2단계 = 위 ⠖⠒…⠲ · 아래 ⠓⠒…⠚.

표에는 상자 태그를 못 다니 앞뒤 글 요소의 태그로 최종 읽기순서에서 위계를 가린다(`pipeline._mark_table_box_levels`).
"""
from uuid import uuid4

from app.ai.braille.table_braille import TableBraille, _TBL_BOT, _TBL_TOP, _relevel_borders
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


def _page(*specs):
    items, ext = [], {}
    for k, (etype, text) in enumerate(specs, start=1):
        eid = uuid4()
        items.append(BBoxItem(element_id=eid, type=etype, bbox=(0, 0, 1, 1), reading_order=k))
        ext[eid] = ExtractedContent(element_id=eid, corrected_text=text)
    return items, ext


def test_읽기순서로_상자_안_표만_위계를_받는다():
    items, ext = _page(
        ("text", "<!상자>자료<!/상자>\n본문"),
        ("table", "<table></table>"),
        ("text", "<!상자2><!/상자2>\n안쪽"),
        ("table", "<table></table>"),
        ("text", "끝\n<!상자끝2><!/상자끝2>\n<!상자끝><!/상자끝>"),
        ("table", "<table></table>"),
    )
    _mark_table_box_levels(items, ext)
    assert [ext[it.element_id].box_level for it in items if it.type == "table"] == [1, 2, 0]
