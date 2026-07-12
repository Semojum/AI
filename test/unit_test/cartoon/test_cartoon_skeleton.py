"""만화 대체텍스트 4안 회귀 — 생략/짧은 제목/개조식/줄글 (QA 2026-07-05).

개조식은 §5.3 골격(장면·대사 전사): §5.3.3(1) 장면·§5.3.3(2)(3) 대사·§6.3.4(3) 화자불명 말풍선.
ZERO 티어는 LLM 미사용(결정적).
"""
from __future__ import annotations

import asyncio
from uuid import uuid4

from app.ai.braille.cartoon_braille import CartoonBraille
from app.ai.braille.layout_braille import LayoutBraille
from app.ai.llm.cartoon_opt import CartoonOpt
from app.ai.llm.visual_drafts import LABELS
from app.schemas.content import ExtractedContent
from app.schemas.layout import BBoxItem, LayoutResult
from app.utils.braille_back import decode

_STRUCT = {
    "title": "우정",
    "panels": [
        {"order": 1, "scene_src": "교실 안", "dialogues": [{"speaker": "학생", "text": "안녕?"}]},
        {"order": 2, "dialogues": [{"speaker": "", "text": "반가워"}]},  # 화자 불명 → 말풍선
    ],
}


class TestFourDrafts:
    def test_4안_라벨(self):
        ext = ExtractedContent(element_id=uuid4(), ocr_confidence=1.0, structure=_STRUCT)
        opt = asyncio.run(CartoonOpt().optimize([ext], "ZERO"))[0]
        assert [d.label for d in opt.drafts] == list(LABELS)
        assert opt.selected_idx == 2                                   # 기본=개조식

    def test_생략안(self):
        ext = ExtractedContent(element_id=uuid4(), ocr_confidence=1.0, structure=_STRUCT)
        opt = asyncio.run(CartoonOpt().optimize([ext], "ZERO"))[0]
        assert opt.drafts[0].text == "<!점역자주>만화 생략<!/점역자주>"

    def test_개조식_장면_대사_전사(self):
        ext = ExtractedContent(element_id=uuid4(), ocr_confidence=1.0, structure=_STRUCT)
        outline = asyncio.run(CartoonOpt().optimize([ext], "ZERO"))[0].drafts[2].text
        assert "장면 1" in outline                                     # §5.3.3(1)
        assert "학생:안녕?" in outline                                 # §5.3.3(2)(3) 대사 전사
        assert "말풍선:반가워" in outline                              # §6.3.4(3) 화자 불명

    def test_구조없음_캡션_4안(self):
        ext = ExtractedContent(element_id=uuid4(), ocr_confidence=1.0, corrected_text="두 컷 만화")
        opt = asyncio.run(CartoonOpt().optimize([ext], "ZERO"))[0]
        assert len(opt.drafts) == 4
        assert "두 컷 만화" in opt.drafts[1].text                      # 캡션 → 짧은 제목

    def test_전부_없음_생략표기(self):
        """시드가 전부 없으면 규정상 '생략' 표기(§6.3.4(2)②). 실패 문자열은 점자로 찍지 않는다."""
        ext = ExtractedContent(element_id=uuid4(), ocr_confidence=1.0, corrected_text="")
        opt = asyncio.run(CartoonOpt().optimize([ext], "ZERO"))[0]
        assert "[처리 불가" not in opt.corrected_text
        assert "생략" in opt.corrected_text
        assert opt.selected_idx == 0


class TestEndToEnd:
    def test_조판_역점역_내용(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        eid = uuid4()
        ext = ExtractedContent(element_id=eid, ocr_confidence=1.0, structure=_STRUCT)
        opt = asyncio.run(CartoonOpt().optimize([ext], "ZERO"))
        assert opt[0].line_indents is not None                         # 개조식 골격 들여쓰기
        bo = CartoonBraille().translate(opt)
        assert len(bo[0].drafts) == 4
        lr = LayoutResult(page_id="p", elements=[
            BBoxItem(element_id=eid, type="cartoon", bbox=(0, 0, 0, 0), reading_order=1)])
        LayoutBraille().layout(bo, page_no=1, job_id="cartoon", layout_result=lr)
        result = (tmp_path / "storage/jobs/cartoon/temp/page_001/result/001_result.txt"
                  ).read_text(encoding="utf-8")
        dec = decode(result)
        for word in ("만화", "우정", "안녕", "반가워", "장면"):
            assert word in dec, f"역점역에 '{word}' 없음: {dec}"
