"""도표 규정 골격 회귀 (2) — 조직도·가계도·연대표·양식·화면이미지·슬라이드.

§6.6.5 조직도(1칸+2칸/단계) · §6.6.4 가계도(하향식 1/3/5·상향식 3칸)
· §6.6.6 연대표(날짜+사건·동일연도 5/3) · §6.6.3 양식(글상자·한 줄) · §6.6.7 화면이미지(글상자·구획)
· §6.6.8 슬라이드(제목·들여쓰기·노트). 불확실 글리프(밑줄 빈칸·관계 기호·하이퍼링크)는 보류.
"""
from __future__ import annotations

import asyncio
from uuid import uuid4

from app.ai.braille.diagram_braille import DiagramBraille
from app.ai.braille.layout_braille import LayoutBraille
from app.ai.llm.diagram_opt import (
    DiagramOpt,
    assemble_org_chart, assemble_family_tree, assemble_timeline,
    assemble_form, assemble_screen_image, assemble_slide,
    _hier_indent, _group_timeline,
)
from app.schemas.content import ExtractedContent
from app.schemas.layout import BBoxItem, LayoutResult
from app.utils.braille_back import decode

_ORG = {
    "subtype": "org_chart",
    "title": "회사 조직",
    "nodes": [
        {"text": "대표", "children": [
            {"text": "개발팀", "children": [{"text": "프론트"}, {"text": "백엔드"}]},
            {"text": "영업팀"},
        ]},
    ],
}
_FAM_DOWN = {
    "subtype": "family_tree",
    "nodes": [{"text": "할아버지", "children": [
        {"text": "아버지", "children": [{"text": "나"}]}]}],
}
_FAM_UP = {
    "subtype": "family_tree", "mode": "bottom_up",
    "items": [{"text": "나"}, {"text": "어머니"}, {"text": "외할머니"}],
}
_TIMELINE = {
    "subtype": "timeline",
    "events": [
        {"date": "1392", "text": "조선 건국"},
        {"date": "1443", "text": "훈민정음 창제"},
        {"date": "1443", "text": "집현전 확대"},
        {"date": "1500", "text": ""},  # 사건 없는 날짜 → 생략(§6.6.6(2)③)
    ],
}
_FORM = {
    "subtype": "form",
    "title": "신청서",
    "items": [{"text": "이름:"}, {"text": "주소:", "note": "긴 빈칸 두 줄"}],
}
_SCREEN = {
    "subtype": "screen_image",
    "sections": [
        {"name": "주 메뉴", "lines": ["홈", "소개"]},
        {"name": "본문", "lines": ["환영합니다"]},
    ],
}
_SLIDE = {
    "subtype": "slide",
    "title": "발표 제목",
    "items": [{"text": "개요", "level": 0}, {"text": "세부", "level": 1}],
    "note": "추가 설명",
}


class TestHierIndent:
    def test_위계_들여쓰기(self):
        # 최상위 1칸, 하위 단계마다 +2칸 (§6.6.5(2)·§6.6.4(2)②)
        assert [_hier_indent(l) for l in (0, 1, 2)] == [1, 3, 5]


class TestOrgChart:
    def test_위계_전사(self):
        text, indents = assemble_org_chart(_ORG)
        lines = text.split("\n")
        assert (lines[0], indents[0]) == ("회사 조직", 5)                     # §6.3.3(1)
        assert lines[1] == "<!점역자주>조직도: 들여쓰기로 상하 위계를 나타냄<!/점역자주>"
        assert lines[2:] == ["대표", "개발팀", "프론트", "백엔드", "영업팀"]
        assert indents[2:] == [1, 3, 5, 5, 3]                                # §6.6.5(2)


class TestFamilyTree:
    def test_하향식_트리(self):
        text, indents = assemble_family_tree(_FAM_DOWN)
        lines = text.split("\n")
        assert lines[0] == "<!점역자주>가계도(하향식): 선조에서 후손 순<!/점역자주>"
        assert lines[1:] == ["할아버지", "아버지", "나"]
        assert indents[1:] == [1, 3, 5]                                      # §6.6.4(2)②

    def test_상향식_평면_3칸(self):
        text, indents = assemble_family_tree(_FAM_UP)
        lines = text.split("\n")
        assert lines[0] == "<!점역자주>가계도(상향식): 후손에서 선조 순<!/점역자주>"
        assert lines[1:] == ["나", "어머니", "외할머니"]
        assert indents[1:] == [3, 3, 3]                                      # §6.6.4(3)②


class TestTimeline:
    def test_그룹핑(self):
        groups = _group_timeline(_TIMELINE["events"])
        assert groups == [("1392", ["조선 건국"]),
                          ("1443", ["훈민정음 창제", "집현전 확대"]),
                          ("1500", [""])]

    def test_날짜_사건_동일연도(self):
        text, indents = assemble_timeline(_TIMELINE)
        lines = text.split("\n")
        assert lines[0] == "<!점역자주>연대표<!/점역자주>"
        # 단일=날짜+사건 한 줄(0칸), 동일연도=연도 5칸·사건 3칸, 사건 없는 1500은 생략
        assert lines[1:] == ["1392 조선 건국", "1443", "훈민정음 창제", "집현전 확대"]
        assert indents[1:] == [0, 5, 3, 3]                                   # §6.6.6(2)②·(4)


class TestForm:
    def test_글상자_항목_노트(self):
        text, indents = assemble_form(_FORM)
        lines = text.split("\n")
        assert (lines[0], indents[0]) == ("신청서", 5)
        assert lines[1] == "<!점역자주>양식<!/점역자주>"
        assert lines[2] == "<!테두리_위><!/테두리_위>"                     # §6.6.3(2) 글상자
        assert lines[3] == "이름:" and lines[4] == "주소:"                   # §6.6.3(3) 한 줄에 하나
        assert lines[5] == "<!점역자주>긴 빈칸 두 줄<!/점역자주>"           # §6.6.3(5)
        assert lines[6] == "<!테두리_아래><!/테두리_아래>"


class TestScreenImage:
    def test_글상자_구획(self):
        text, indents = assemble_screen_image(_SCREEN)
        lines = text.split("\n")
        assert lines[0] == "<!점역자주>화면 이미지<!/점역자주>"
        assert lines[1] == "<!테두리_위><!/테두리_위>"                     # §6.6.7(1)
        assert lines[2:-1] == ["주 메뉴", "홈", "소개", "본문", "환영합니다"]  # §6.6.7(3)①
        assert indents[2:-1] == [0, 2, 2, 0, 2]
        assert lines[-1] == "<!테두리_아래><!/테두리_아래>"


class TestSlide:
    def test_제목_들여쓰기_노트(self):
        text, indents = assemble_slide(_SLIDE)
        lines = text.split("\n")
        assert (lines[0], indents[0]) == ("발표 제목", 5)
        assert lines[1] == "<!점역자주>발표용 슬라이드<!/점역자주>"
        assert (lines[2], indents[2]) == ("개요", 0)
        assert (lines[3], indents[3]) == ("세부", 2)                         # §6.6.8(2)
        assert lines[4] == "<!점역자주>노트: 추가 설명<!/점역자주>"          # §6.6.8(3)


class TestOptimizeRouting:
    def test_각_하위유형_라우팅(self):
        for st, needle in [(_ORG, "대표"), (_FAM_DOWN, "할아버지"), (_FAM_UP, "외할머니"),
                           (_TIMELINE, "조선 건국"), (_FORM, "이름:"),
                           (_SCREEN, "주 메뉴"), (_SLIDE, "개요")]:
            ext = ExtractedContent(element_id=uuid4(), ocr_confidence=1.0, structure=st)
            opt = asyncio.run(DiagramOpt().optimize([ext], "ZERO"))[0]
            assert opt.render_mode == "narrative"
            assert needle in opt.corrected_text
            assert opt.line_indents is not None

    def test_visual_subtype로_라우팅(self):
        # structure.subtype 없이 visual_subtype로만 조직도 판별
        st = {"nodes": _ORG["nodes"]}
        ext = ExtractedContent(element_id=uuid4(), ocr_confidence=1.0,
                               structure=st, visual_subtype="org_chart")
        opt = asyncio.run(DiagramOpt().optimize([ext], "ZERO"))[0]
        assert "대표" in opt.corrected_text and opt.line_indents[-1] == 3  # 영업팀 1단계


class TestE2E:
    def test_조직도_위계_들여쓰기(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        eid = uuid4()
        ext = ExtractedContent(element_id=eid, ocr_confidence=1.0, structure=_ORG)
        bo = DiagramBraille().translate(asyncio.run(DiagramOpt().optimize([ext], "ZERO")))
        lr = LayoutResult(page_id="p", elements=[
            BBoxItem(element_id=eid, type="diagram", bbox=(0, 0, 0, 0), reading_order=1)])
        LayoutBraille().layout(bo, page_no=1, job_id="og", layout_result=lr)
        result = (tmp_path / "storage/jobs/og/temp/page_001/result/001_result.txt"
                  ).read_text(encoding="utf-8").split("\n")
        content = [l for l in result if l.strip()]
        # 최상위 1칸·최하위(프론트) 5칸 들여쓰기가 result.txt에 반영
        top = next(l for l in content if "대표" in decode(l))
        assert top.startswith(" ") and not top.startswith("  ")
        leaf = next(l for l in content if "프론트" in decode(l))
        assert leaf.startswith(" " * 5) and not leaf.startswith(" " * 6)

    def test_화면이미지_글상자_재렌더(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        eid = uuid4()
        ext = ExtractedContent(element_id=eid, ocr_confidence=1.0, structure=_SCREEN)
        bo = DiagramBraille().translate(asyncio.run(DiagramOpt().optimize([ext], "ZERO")))
        # 글상자 위/아래 테두리가 box_borders로 수집됨(layout이 재렌더)
        assert any(b.kind for b in bo[0].box_borders)
        lr = LayoutResult(page_id="p", elements=[
            BBoxItem(element_id=eid, type="diagram", bbox=(0, 0, 0, 0), reading_order=1)])
        LayoutBraille().layout(bo, page_no=1, job_id="sc", layout_result=lr)
        result = (tmp_path / "storage/jobs/sc/temp/page_001/result/001_result.txt"
                  ).read_text(encoding="utf-8")
        dec = decode(result)
        assert "주 메뉴" in dec and "환영합니다" in dec
        # 테두리 글리프(⠿)가 본문 위·아래에 렌더됨
        assert "⠿" in result
