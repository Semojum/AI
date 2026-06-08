"""중첩 시각자료 회귀 — 점역사 QnA Q11.

· 그림 안의 그래프 → 그래프 설명을 테두리로 묶는다(image_opt → nested_text → image_braille).
· 표 안의 그림   → 그림을 글상자처럼 1단으로 풀어 쓴다(table_opt → nested_text → table_braille).
공용 테두리+들여쓰기 공존은 layout `_expand_box_borders` 재매핑으로 보장한다.
"""
from __future__ import annotations

import asyncio
from uuid import uuid4

from app.ai.braille.image_braille import ImageBraille
from app.ai.braille.layout_braille import LayoutBraille
from app.ai.braille.nested_block import box_narrative
from app.ai.braille.table_braille import TableBraille
from app.ai.llm.image_opt import ImageOpt
from app.ai.llm.table_opt import TableOpt
from app.schemas.content import ExtractedContent
from app.schemas.layout import BBoxItem, LayoutResult
from app.utils.braille_back import decode

_IMG_WITH_GRAPH = {
    "visual_type_label": "지도", "title": "유럽 지도",
    "caption_src": "유럽 국가 분포도",
    "nested": [{"type": "chart", "label": "막대그래프",
                "description": "국가별 인구", "ocr_texts": ["프랑스 67", "독일 83"]}],
}
_TBL_WITH_IMG = {
    "cells": [{"row": 0, "col": 0, "text": "지역"}, {"row": 0, "col": 1, "text": "유물"},
              {"row": 1, "col": 0, "text": "경주"}, {"row": 1, "col": 1, "text": "금관"}],
    "title": "출토 유물",
    "nested": [{"type": "image", "label": "사진", "description": "금관 사진"}],
}


class TestBoxNarrative:
    def test_테두리로_묶음(self):
        txt = box_narrative([{"label": "막대그래프", "description": "국가별 인구",
                              "ocr_texts": ["프랑스 67"]}])
        lines = txt.split("\n")
        assert lines[0] == "<!표윗테두리><!/표윗테두리>"   # 테두리 쌍(빈 제목)
        assert lines[1] == "<!점역자주>막대그래프: 국가별 인구<!/점역자주>"
        assert "프랑스 67" in lines                       # 원본 내용 전사
        assert lines[-1] == "<!표아랫테두리><!/표아랫테두리>"
        assert box_narrative([]) is None

    def test_default_label(self):
        txt = box_narrative([{"description": "설명만"}], default_label="그림")
        assert "<!점역자주>그림: 설명만<!/점역자주>" in txt


class TestImageNestedGraph:
    def test_opt_nested_text(self):
        ext = ExtractedContent(element_id=uuid4(), ocr_confidence=1.0, structure=_IMG_WITH_GRAPH)
        opt = asyncio.run(ImageOpt().optimize([ext], "ZERO"))[0]
        assert opt.nested_text and "<!표윗테두리>" in opt.nested_text
        assert "막대그래프" in opt.nested_text

    def test_braille_테두리_수집(self):
        ext = ExtractedContent(element_id=uuid4(), ocr_confidence=1.0, structure=_IMG_WITH_GRAPH)
        opt = asyncio.run(ImageOpt().optimize([ext], "ZERO"))
        bo = ImageBraille().translate(opt)[0]
        kinds = sorted(b.kind for b in bo.box_borders)
        assert kinds == ["bottom", "top"]                # 그래프 설명을 테두리로 묶음
        dec = decode("\n".join(bo.braille_lines))
        assert "국가별 인구" in dec and "프랑스" in dec    # 그래프 설명·원본 전사가 본문에 포함

    def test_없으면_nested_None(self):
        st = {k: v for k, v in _IMG_WITH_GRAPH.items() if k != "nested"}
        ext = ExtractedContent(element_id=uuid4(), ocr_confidence=1.0, structure=st)
        opt = asyncio.run(ImageOpt().optimize([ext], "ZERO"))[0]
        assert opt.nested_text is None


class TestTableNestedImage:
    def test_opt_nested_text(self):
        ext = ExtractedContent(element_id=uuid4(), ocr_confidence=1.0, table_structure=_TBL_WITH_IMG)
        opt = asyncio.run(TableOpt().optimize([ext], "ZERO"))[0]
        assert opt.nested_text and "<!표윗테두리>" in opt.nested_text
        assert "사진" in opt.nested_text and "금관 사진" in opt.nested_text

    def test_braille_테두리_수집(self):
        ext = ExtractedContent(element_id=uuid4(), ocr_confidence=1.0, table_structure=_TBL_WITH_IMG)
        opt = asyncio.run(TableOpt().optimize([ext], "ZERO"))
        bo = TableBraille().translate(opt)[0]
        kinds = sorted(b.kind for b in bo.box_borders)
        assert kinds == ["bottom", "top"]                # 표 안 그림을 글상자(1단)로
        dec = decode("\n".join(bo.braille_lines))
        assert "금관 사진" in dec


class TestE2E:
    def test_image_제목5칸_테두리_공존(self, tmp_path, monkeypatch):
        """테두리(중첩)와 제목 5칸 들여쓰기가 동시에 살아남는지(layout 재매핑)."""
        monkeypatch.chdir(tmp_path)
        eid = uuid4()
        ext = ExtractedContent(element_id=eid, ocr_confidence=1.0, structure=_IMG_WITH_GRAPH)
        opt = asyncio.run(ImageOpt().optimize([ext], "ZERO"))
        bo = ImageBraille().translate(opt)
        lr = LayoutResult(page_id="p", elements=[
            BBoxItem(element_id=eid, type="image", bbox=(0, 0, 0, 0), reading_order=1)])
        LayoutBraille().layout(bo, page_no=1, job_id="ns", layout_result=lr)
        result = (tmp_path / "storage/jobs/ns/temp/page_001/result/001_result.txt"
                  ).read_text(encoding="utf-8").split("\n")
        content = [l for l in result if l.strip()]
        dec = decode("\n".join(result))
        assert "국가별 인구" in dec                        # 중첩 그래프 설명 본문 포함
        title = next(l for l in content if "유럽 지도" in decode(l))
        assert title.startswith(" " * 5) and not title.startswith(" " * 6)  # 제목 5칸 유지
