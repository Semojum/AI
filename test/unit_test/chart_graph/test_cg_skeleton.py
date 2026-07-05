"""차트 대체텍스트 4안 회귀 — 생략/짧은 제목/개조식(표 변환)/줄글 (QA 2026-07-05).

개조식 = §6.4·Q5 표 변환(data_points 전사). 줄글 = 수학적 서술. 수치 보존(누락 시 R5).
"""
from __future__ import annotations

import asyncio
from uuid import uuid4

from app.ai.braille.chart_graph_braille import ChartGraphBraille
from app.ai.braille.layout_braille import LayoutBraille
from app.ai.llm.chart_graph_opt import ChartGraphOpt, _label
from app.ai.llm.visual_drafts import LABELS
from app.schemas.content import ExtractedContent
from app.schemas.layout import BBoxItem, LayoutResult
from app.utils.braille_back import decode

_STRUCT = {
    "chart_subtype": "bar", "title": "연도별 발행 권수",
    "axes": {"x": {"label": "연도", "unit": ""}, "y": {"label": "권수", "unit": "권"}},
    "data_points": [{"label": "2020", "value": 980}, {"label": "2021", "value": 1100}],
    "caption_src": "연도별 발행 권수 막대그래프. 980권에서 1100권으로 증가.",
}


class TestLabel:
    def test_유형_라벨_매핑(self):
        assert _label({"chart_subtype": "bar"}) == "막대그래프"
        assert _label({"chart_subtype": "pie"}) == "비율그래프"
        assert _label({}) == "그래프"


class TestFourDrafts:
    def test_4안_라벨(self):
        ext = ExtractedContent(element_id=uuid4(), ocr_confidence=1.0, structure=_STRUCT)
        opt = asyncio.run(ChartGraphOpt().optimize([ext], "ZERO"))[0]
        assert [d.label for d in opt.drafts] == list(LABELS)
        assert opt.selected_idx == 2                                   # 기본=개조식(표 변환)

    def test_개조식_데이터_전사(self):
        ext = ExtractedContent(element_id=uuid4(), ocr_confidence=1.0, structure=_STRUCT)
        outline = asyncio.run(ChartGraphOpt().optimize([ext], "ZERO"))[0].drafts[2].text
        assert "2020: 980권" in outline and "2021: 1100권" in outline   # 수치+단위 전사
        assert "가로축 연도" in outline                                # 축 머리 항목

    def test_수치_보존_R5없음(self):
        st = {"chart_subtype": "bar", "data_points": [{"label": "A", "value": 5}], "caption_src": "값 5"}
        ext = ExtractedContent(element_id=uuid4(), ocr_confidence=1.0, structure=st)
        asyncio.run(ChartGraphOpt().optimize([ext], "ZERO"))
        assert "R5" not in ext.flags                                   # 표 변환이 5 포함 → 정상

    def test_e2e_수치_유지(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        eid = uuid4()
        ext = ExtractedContent(element_id=eid, ocr_confidence=1.0, structure=_STRUCT)
        bo = ChartGraphBraille().translate(asyncio.run(ChartGraphOpt().optimize([ext], "ZERO")))
        assert len(bo[0].drafts) == 4
        lr = LayoutResult(page_id="p", elements=[
            BBoxItem(element_id=eid, type="chart_graph", bbox=(0, 0, 0, 0), reading_order=1)])
        LayoutBraille().layout(bo, page_no=1, job_id="cg", layout_result=lr)
        result = (tmp_path / "storage/jobs/cg/temp/page_001/result/001_result.txt"
                  ).read_text(encoding="utf-8")
        dec = decode(result)
        assert "980" in dec and "1100" in dec
