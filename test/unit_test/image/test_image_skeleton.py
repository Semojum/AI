"""이미지 rule-based 골격(§6.3) 회귀 — 제목 5칸·유형 라벨·ocr 전사·생략.

§6.3.3(1) 제목 5칸·§6.3.4(1) 유형 라벨 필수·§6.3.4(2)① 원본 내용 전사·(2)② 장식 생략(Q7).
"""
from __future__ import annotations

import asyncio
from uuid import uuid4

from app.ai.braille.image_braille import ImageBraille
from app.ai.braille.layout_braille import LayoutBraille
from app.ai.llm.image_opt import ImageOpt, assemble_image
from app.schemas.content import ExtractedContent
from app.schemas.layout import BBoxItem, LayoutResult
from app.utils.braille_back import decode


class TestAssemble:
    def test_제목_유형_ocr(self):
        text, indents = assemble_image("그림", "광합성", ["6CO2", "C6H12O6"], "잎에서 빛을 받는다")
        lines = text.split("\n")
        assert lines[0] == "광합성" and indents[0] == 5                      # §6.3.3 제목 5칸
        assert lines[1] == "<!점역자주>그림: 잎에서 빛을 받는다<!/점역자주>"  # §6.3.4(1)
        assert "6CO2" in lines and "C6H12O6" in lines                        # §6.3.4(2)① 전사
        assert len(indents) == len(lines)

    def test_제목없음_유형라벨_필수(self):
        text, indents = assemble_image("사진", "", [], "건물 외관")
        assert text == "<!점역자주>사진: 건물 외관<!/점역자주>" and indents == [0]

    def test_설명없음_생략표기(self):
        text, _ = assemble_image("그림", "", [], "")
        assert text == "<!점역자주>그림 생략<!/점역자주>"


class TestOptimize:
    def test_zero_단일안_제목_들여(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        eid = uuid4()
        ext = ExtractedContent(element_id=eid, ocr_confidence=1.0, structure={
            "visual_type_label": "그림", "title": "세포 구조",
            "ocr_texts": ["핵"], "caption_src": "둥근 세포 안에 핵이 있다"})
        opt = asyncio.run(ImageOpt().optimize([ext], "ZERO"))
        assert opt[0].line_indents and opt[0].line_indents[0] == 5
        assert "<!점역자주>그림:" in opt[0].tn_text
        bo = ImageBraille().translate(opt)
        lr = LayoutResult(page_id="p", elements=[
            BBoxItem(element_id=eid, type="image", bbox=(0, 0, 0, 0), reading_order=1)])
        LayoutBraille().layout(bo, page_no=1, job_id="img", layout_result=lr)
        result = (tmp_path / "storage/jobs/img/temp/page_001/result/001_result.txt"
                  ).read_text(encoding="utf-8").split("\n")
        dec = decode("\n".join(result))
        assert "세포 구조" in dec and "핵" in dec
        content = [l for l in result if l.strip()]
        assert any(l.startswith("     ") and not l.startswith("      ") for l in content)  # 제목 5칸

    def test_장식용_생략(self):
        eid = uuid4()
        ext = ExtractedContent(element_id=eid, ocr_confidence=1.0,
                               structure={"visual_type_label": "그림", "decorative": True,
                                          "caption_src": "장식 클립아트"})
        opt = asyncio.run(ImageOpt().optimize([ext], "ZERO"))
        assert opt[0].corrected_text == ""    # §6.3.4(2)②·Q7 — 생략(빈 출력, layout이 제외)
