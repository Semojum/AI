"""도표 규정 골격 회귀 — 개념도(§6.6.1)·흐름도(§6.6.2) rule-based 조립.

§6.3.3(1) 제목 5칸 · §6.3.4(1) 유형 점역자주 · §6.6.1(3) 위계 개조식(2단계 5/3·3단계 7/5/3)
· §6.6.2(4) 흐름도 번호+한 줄·분기 3칸(도형 점형은 점역사 확인 후 — 구조만).
"""
from __future__ import annotations

import asyncio
from uuid import uuid4

from app.ai.braille.diagram_braille import DiagramBraille
from app.ai.braille.layout_braille import LayoutBraille
from app.ai.llm.diagram_opt import (
    DiagramOpt, assemble_concept_map, assemble_flowchart,
    _tree_depth, _concept_indent,
)
from app.schemas.content import ExtractedContent
from app.schemas.layout import BBoxItem, LayoutResult
from app.utils.braille_back import decode

_CONCEPT_3 = {
    "subtype": "concept_map",
    "nodes": [
        {"text": "생물", "children": [
            {"text": "동물", "children": [{"text": "포유류"}, {"text": "조류"}]},
            {"text": "식물", "children": [{"text": "속씨식물"}]},
        ]},
    ],
}
_CONCEPT_2 = {
    "subtype": "concept_map",
    "title": "먹이 사슬",
    "nodes": [{"text": "생산자", "children": [{"text": "소비자"}]}],
}
_FLOW = {
    "subtype": "flowchart",
    "boxes": [
        {"no": 1, "text": "시작"},
        {"no": 2, "text": "조건?", "branches": [{"label": "예", "to": 3}, {"label": "아니오", "to": 4}]},
        {"no": 3, "text": "처리"},
        {"no": 4, "text": "종료"},
    ],
}


class TestConceptIndent:
    def test_깊이(self):
        assert _tree_depth(_CONCEPT_3["nodes"]) == 3
        assert _tree_depth(_CONCEPT_2["nodes"]) == 2

    def test_들여쓰기_규칙(self):
        # 2단계: 상위 5칸·하위 3칸 (§6.6.1(3)①)
        assert _concept_indent(0, 2) == 5 and _concept_indent(1, 2) == 3
        # 3단계: 최상위 7칸·중위 5칸·하위 3칸 (§6.6.1(3)②)
        assert [_concept_indent(l, 3) for l in (0, 1, 2)] == [7, 5, 3]


class TestConceptAssemble:
    def test_3단계_개조식_전사(self):
        text, indents = assemble_concept_map(_CONCEPT_3)
        lines = text.split("\n")
        assert lines[0] == "<!점역자주>개념도<!/점역자주>" and indents[0] == 0   # §6.3.4(1)
        # 중심개념부터 하위로(§6.6.1(2)), 7/5/3 들여쓰기
        assert lines[1:] == ["생물", "동물", "포유류", "조류", "식물", "속씨식물"]
        assert indents[1:] == [7, 5, 3, 3, 5, 3]

    def test_2단계_제목5칸(self):
        text, indents = assemble_concept_map(_CONCEPT_2)
        lines = text.split("\n")
        assert lines[0] == "먹이 사슬" and indents[0] == 5                      # §6.3.3(1)
        assert lines[1] == "<!점역자주>개념도<!/점역자주>"
        assert (lines[2], indents[2]) == ("생산자", 5) and (lines[3], indents[3]) == ("소비자", 3)


class TestFlowAssemble:
    def test_번호_한줄_분기3칸(self):
        text, indents = assemble_flowchart(_FLOW)
        lines = text.split("\n")
        assert lines[0] == "<!점역자주>흐름도<!/점역자주>"                      # §6.3.4(1)
        assert lines[1:] == ["1 시작", "2 조건?", "예: 3", "아니오: 4", "3 처리", "4 종료"]
        # 상자 indent 0, 분기 선택지 3칸(§6.6.2(4)⑥)
        assert indents[1:] == [0, 0, 3, 3, 0, 0]


class TestOptimize:
    def test_concept_라우팅(self):
        ext = ExtractedContent(element_id=uuid4(), ocr_confidence=1.0, structure=_CONCEPT_3)
        opt = asyncio.run(DiagramOpt().optimize([ext], "ZERO"))[0]
        assert opt.render_mode == "narrative"
        assert "생물" in opt.corrected_text and opt.line_indents[1] == 7

    def test_flow_라우팅_visual_subtype(self):
        # structure.subtype 없이 visual_subtype로만 흐름도 판별
        st = {"boxes": _FLOW["boxes"]}
        ext = ExtractedContent(element_id=uuid4(), ocr_confidence=1.0,
                               structure=st, visual_subtype="flowchart")
        opt = asyncio.run(DiagramOpt().optimize([ext], "ZERO"))[0]
        assert "1 시작" in opt.corrected_text

    def test_구조없음_폴백(self):
        ext = ExtractedContent(element_id=uuid4(), ocr_confidence=1.0,
                               corrected_text="가계도 설명", visual_subtype="concept_map")
        opt = asyncio.run(DiagramOpt().optimize([ext], "ZERO"))[0]
        assert "개념도" in opt.corrected_text and "가계도 설명" in opt.corrected_text

    def test_빈입력_처리불가(self):
        ext = ExtractedContent(element_id=uuid4(), ocr_confidence=1.0, visual_subtype="flowchart")
        opt = asyncio.run(DiagramOpt().optimize([ext], "ZERO"))[0]
        assert opt.corrected_text.startswith("[처리 불가") and opt.routing_tier == "FALLBACK"


class TestE2E:
    def test_개념도_위계_들여쓰기(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        eid = uuid4()
        ext = ExtractedContent(element_id=eid, ocr_confidence=1.0, structure=_CONCEPT_3)
        opt = asyncio.run(DiagramOpt().optimize([ext], "ZERO"))
        bo = DiagramBraille().translate(opt)
        lr = LayoutResult(page_id="p", elements=[
            BBoxItem(element_id=eid, type="diagram", bbox=(0, 0, 0, 0), reading_order=1)])
        LayoutBraille().layout(bo, page_no=1, job_id="dg", layout_result=lr)
        result = (tmp_path / "storage/jobs/dg/temp/page_001/result/001_result.txt"
                  ).read_text(encoding="utf-8").split("\n")
        content = [l for l in result if l.strip()]
        dec = decode("\n".join(result))
        assert "생물" in dec and "포유류" in dec                       # 셀 값 전사
        # 최상위 7칸·하위 3칸 들여쓰기가 result.txt에 반영
        top = next(l for l in content if "생물" in decode(l))
        assert top.startswith(" " * 7) and not top.startswith(" " * 8)
        leaf = next(l for l in content if "포유류" in decode(l))
        assert leaf.startswith(" " * 3) and not leaf.startswith(" " * 4)
