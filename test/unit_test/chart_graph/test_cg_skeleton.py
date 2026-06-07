"""차트 rule-based 골격(§6.4) 회귀 — 제목 5칸·유형 라벨·표 변환(데이터 전사)·수학적 서술 2안.

§6.3.3 제목 5칸·§6.3.4(1) 유형 라벨·§6.4·Q5 표 변환/수학적 서술 2안·수치 보존(R5).
"""
from __future__ import annotations

import asyncio
from uuid import uuid4

from app.ai.braille.chart_graph_braille import ChartGraphBraille
from app.ai.braille.layout_braille import LayoutBraille
from app.ai.llm.chart_graph_opt import ChartGraphOpt, assemble_chart, _label, _table_description
from app.schemas.content import ExtractedContent
from app.schemas.layout import BBoxItem, LayoutResult
from app.utils.braille_back import decode

_STRUCT = {
    "chart_subtype": "bar", "title": "연도별 발행 권수",
    "axes": {"x": {"label": "연도", "unit": ""}, "y": {"label": "권수", "unit": "권"}},
    "data_points": [{"label": "2020", "value": 980}, {"label": "2021", "value": 1100}],
    "caption_src": "연도별 발행 권수 막대그래프. 980권에서 1100권으로 증가.",
}


class TestAssemble:
    def test_유형_라벨_매핑(self):
        assert _label({"chart_subtype": "bar"}) == "막대그래프"
        assert _label({"chart_subtype": "pie"}) == "비율그래프"
        assert _label({}) == "그래프"

    def test_표변환_데이터_전사(self):
        d = _table_description(_STRUCT)
        assert "2020: 980권" in d and "2021: 1100권" in d   # 수치+단위 전사

    def test_골격_제목5칸(self):
        text, indents = assemble_chart("막대그래프", "연도별 발행 권수", "2020: 980권")
        lines = text.split("\n")
        assert lines[0] == "연도별 발행 권수" and indents[0] == 5
        assert lines[1].startswith("<!점역자주>막대그래프:")


class TestOptimize:
    def test_zero_2안_표변환_수학서술(self):
        ext = ExtractedContent(element_id=uuid4(), ocr_confidence=1.0, structure=_STRUCT)
        opt = asyncio.run(ChartGraphOpt().optimize([ext], "ZERO"))[0]
        labels = [d.label for d in opt.drafts]
        assert labels == ["표 변환", "수학적 서술"]            # §6.4·Q5 2안
        assert opt.selected_idx == 0                          # 표 변환 우선(데이터 多)
        assert "980" in opt.drafts[0].text and "1100" in opt.drafts[0].text  # 수치 보존

    def test_수치누락_R5(self):
        # 표 변환에 수치가 다 들어가므로 R5 없음. 데이터 일부만 있는 캡션 변조 케이스를 모사:
        st = {"chart_subtype": "bar", "data_points": [{"label": "A", "value": 5}],
              "caption_src": "값 5"}
        ext = ExtractedContent(element_id=uuid4(), ocr_confidence=1.0, structure=st)
        asyncio.run(ChartGraphOpt().optimize([ext], "ZERO"))
        # 표 변환이 5를 포함하므로 R5 미발생(정상)
        assert "R5" not in ext.flags

    def test_e2e_제목_들여(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        eid = uuid4()
        ext = ExtractedContent(element_id=eid, ocr_confidence=1.0, structure=_STRUCT)
        opt = asyncio.run(ChartGraphOpt().optimize([ext], "ZERO"))
        bo = ChartGraphBraille().translate(opt)
        lr = LayoutResult(page_id="p", elements=[
            BBoxItem(element_id=eid, type="chart_graph", bbox=(0, 0, 0, 0), reading_order=1)])
        LayoutBraille().layout(bo, page_no=1, job_id="cg", layout_result=lr)
        result = (tmp_path / "storage/jobs/cg/temp/page_001/result/001_result.txt"
                  ).read_text(encoding="utf-8").split("\n")
        dec = decode("\n".join(result))
        assert "980" in dec and "1100" in dec
        content = [l for l in result if l.strip()]
        assert any(l.startswith("     ") and not l.startswith("      ") for l in content)  # 제목 5칸
