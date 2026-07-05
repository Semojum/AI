"""이미지 대체텍스트 4안 회귀 — 생략/짧은 제목/개조식/줄글 (QA 2026-07-05).

§6.3.4(2)② 생략 표기·짧은 제목(캡션 전사)·개조식(§6.3.4(2)① 원본 글자 전사)·줄글.
ZERO 티어는 LLM 미사용(결정적)이라 항상 4안이 나온다.
"""
from __future__ import annotations

import asyncio
from uuid import uuid4

from app.ai.braille.image_braille import ImageBraille
from app.ai.braille.layout_braille import LayoutBraille
from app.ai.llm.image_opt import ImageOpt
from app.ai.llm.visual_drafts import LABELS
from app.schemas.content import ExtractedContent
from app.schemas.layout import BBoxItem, LayoutResult
from app.utils.braille_back import decode

_STRUCT = {
    "visual_type_label": "그림", "title": "광합성",
    "ocr_texts": ["6CO2", "C6H12O6"], "caption_src": "잎에서 빛을 받는다",
}


class TestFourDrafts:
    def test_4안_라벨(self):
        ext = ExtractedContent(element_id=uuid4(), ocr_confidence=1.0, structure=_STRUCT)
        opt = asyncio.run(ImageOpt().optimize([ext], "ZERO"))[0]
        assert [d.label for d in opt.drafts] == list(LABELS)   # 생략/짧은 제목/개조식/줄글
        assert opt.selected_idx == 2                           # 기본=개조식

    def test_생략안_규정표기(self):
        ext = ExtractedContent(element_id=uuid4(), ocr_confidence=1.0, structure=_STRUCT)
        opt = asyncio.run(ImageOpt().optimize([ext], "ZERO"))[0]
        assert opt.drafts[0].text == "<!점역자주>그림 생략<!/점역자주>"   # §6.3.4(2)②

    def test_짧은제목_캡션_전사(self):
        ext = ExtractedContent(element_id=uuid4(), ocr_confidence=1.0, structure=_STRUCT)
        opt = asyncio.run(ImageOpt().optimize([ext], "ZERO"))[0]
        assert "잎에서 빛을 받는다" in opt.drafts[1].text

    def test_개조식_ocr_전사(self):
        ext = ExtractedContent(element_id=uuid4(), ocr_confidence=1.0, structure=_STRUCT)
        opt = asyncio.run(ImageOpt().optimize([ext], "ZERO"))[0]
        assert "6CO2" in opt.drafts[2].text and "C6H12O6" in opt.drafts[2].text   # §6.3.4(2)①
        assert opt.line_indents is not None                    # 개조식 위계 들여쓰기 전달

    def test_장식용_기본_생략(self):
        ext = ExtractedContent(element_id=uuid4(), ocr_confidence=1.0, structure={
            "visual_type_label": "그림", "decorative": True, "caption_src": "장식 클립아트"})
        opt = asyncio.run(ImageOpt().optimize([ext], "ZERO"))[0]
        assert opt.selected_idx == 0                            # 장식용 → 기본 생략(§6.3.4(2)②·Q7)
        assert opt.corrected_text == opt.drafts[0].text

    def test_캡션_없음_처리불가(self):
        ext = ExtractedContent(element_id=uuid4(), ocr_confidence=1.0, structure={})
        opt = asyncio.run(ImageOpt().optimize([ext], "ZERO"))[0]
        assert "[처리 불가" in opt.corrected_text


class TestEndToEnd:
    def test_조판_개조식_내용(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        eid = uuid4()
        ext = ExtractedContent(element_id=eid, ocr_confidence=1.0, structure={
            "visual_type_label": "그림", "title": "세포 구조",
            "ocr_texts": ["핵"], "caption_src": "둥근 세포 안에 핵이 있다"})
        opt = asyncio.run(ImageOpt().optimize([ext], "ZERO"))
        bo = ImageBraille().translate(opt)
        assert len(bo[0].drafts) == 4                          # 4안 모두 점역됨
        lr = LayoutResult(page_id="p", elements=[
            BBoxItem(element_id=eid, type="image", bbox=(0, 0, 0, 0), reading_order=1)])
        LayoutBraille().layout(bo, page_no=1, job_id="img", layout_result=lr)
        result = (tmp_path / "storage/jobs/img/temp/page_001/result/001_result.txt"
                  ).read_text(encoding="utf-8")
        dec = decode(result)
        assert "세포 구조" in dec and "핵" in dec
