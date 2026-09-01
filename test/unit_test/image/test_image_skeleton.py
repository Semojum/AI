"""이미지 대체텍스트 회귀 — 생략 / 설명 / 참조.

★ 2026-08-20에 6안을 3안으로 줄였다. 근거는 규정 「점자 자료 제작 지침」 §6.1.1 첫 줄
   ("점자 그래픽 제작, 핵심 정보 설명 및 생략")과 gold 실측이다.
   설명 327(79.6%) · 생략 고지 50(12.2%) · 참조 33(8.0%).
ZERO 티어는 LLM 미사용(결정적)이라 안 개수가 흔들리지 않는다.
"""
from __future__ import annotations

import asyncio
from uuid import uuid4

from app.ai.braille.image_braille import ImageBraille
from app.ai.braille.layout_braille import LayoutBraille
from app.ai.llm.image_opt import ImageOpt
from app.ai.llm.visual_drafts import (
    LABELS,
    desc_label,
    prose_label,
    desc_draft,
    omission_draft,
    volume_ref_draft,
)
from app.core.pipeline import _number_volume_refs
from app.schemas.content import ExtractedContent, LLMOutput
from app.schemas.layout import BBoxItem, LayoutResult
from app.utils.braille_back import decode

_STRUCT = {
    "visual_type_label": "그림", "title": "광합성",
    "ocr_texts": ["6CO2", "C6H12O6"], "caption_src": "잎에서 빛을 받는다",
}


class TestFourDrafts:
    def test_안_라벨(self):
        ext = ExtractedContent(element_id=uuid4(), ocr_confidence=1.0, structure=_STRUCT)
        opt = asyncio.run(ImageOpt().optimize([ext], "ZERO"))[0]
        labels = [d.label for d in opt.drafts]
        # 재료가 겹쳐 접힌 안이 있을 수 있다(`visual_drafts._dedupe`) — 남은 것은
        # LABELS의 **부분 수열**이고 서로 달라야 한다.
        expected = list(dict.fromkeys(
            [LABELS[0], desc_label("이미지"), LABELS[2], prose_label("이미지")]))
        assert labels == [x for x in expected if x in labels], labels
        assert len(set(labels)) == len(labels), labels
        assert opt.selected_idx == 1                           # 기본=설명(gold 79.6%)

    def test_생략안_규정표기(self):
        ext = ExtractedContent(element_id=uuid4(), ocr_confidence=1.0, structure=_STRUCT)
        opt = asyncio.run(ImageOpt().optimize([ext], "ZERO"))[0]
        assert opt.drafts[0].text == "<!주>그림 생략<!/주>"   # §6.3.4(2)②

    def test_짧은제목_캡션_전사(self):
        ext = ExtractedContent(element_id=uuid4(), ocr_confidence=1.0, structure=_STRUCT)
        opt = asyncio.run(ImageOpt().optimize([ext], "ZERO"))[0]
        assert "잎에서 빛을 받는다" in opt.drafts[1].text

    def test_개조식_ocr_전사(self):
        ext = ExtractedContent(element_id=uuid4(), ocr_confidence=1.0, structure=_STRUCT)
        opt = asyncio.run(ImageOpt().optimize([ext], "ZERO"))[0]
        assert "6CO2" in opt.drafts[1].text and "C6H12O6" in opt.drafts[1].text   # §6.3.4(2)①
        assert opt.line_indents is not None                    # 개조식 위계 들여쓰기 전달

    def test_장식용_기본_생략(self):
        ext = ExtractedContent(element_id=uuid4(), ocr_confidence=1.0, structure={
            "visual_type_label": "그림", "decorative": True, "caption_src": "장식 클립아트"})
        opt = asyncio.run(ImageOpt().optimize([ext], "ZERO"))[0]
        assert opt.selected_idx == 0                            # 장식용 → 기본 생략(§6.3.4(2)②·Q7)
        assert opt.corrected_text == opt.drafts[0].text

    def test_캡션_없음_생략표기(self):
        """캡션·구조·제목이 없으면(캡셔닝 실패 포함) 규정상 '생략' 표기가 정답이다(§6.3.4(2)②).

        구 동작은 "[처리 불가: …]"를 냈는데, 이 문자열은 마커가 아니라 그대로 점자로
        인코딩돼 학생이 "처리 불가 이미지 캡션 없음"을 읽게 된다. 실패는 점자 본문이 아니라
        품질검사 R11(CAPTION_FAILED)로 점역사에게 알린다.
        """
        ext = ExtractedContent(element_id=uuid4(), ocr_confidence=1.0, structure={})
        opt = asyncio.run(ImageOpt().optimize([ext], "ZERO"))[0]
        assert "[처리 불가" not in opt.corrected_text
        assert "생략" in opt.corrected_text
        assert opt.selected_idx == 0          # 0안 = 생략
        assert [d.label for d in opt.drafts] == [LABELS[0]], \
            "캡셔닝 실패·캡션 없음이면 생략 한 안만 (2026-08-12 대표 지시)"   # 안 개수 유지 — 점역사가 다른 안 선택 가능


class TestEndToEnd:
    def test_조판_개조식_내용(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        eid = uuid4()
        ext = ExtractedContent(element_id=eid, ocr_confidence=1.0, structure={
            "visual_type_label": "그림", "title": "세포 구조",
            "ocr_texts": ["핵"], "caption_src": "둥근 세포 안에 핵이 있다"})
        opt = asyncio.run(ImageOpt().optimize([ext], "ZERO"))
        bo = ImageBraille().translate(opt)
        assert 3 <= len(bo[0].drafts) <= 4                # 모든 안이 점역됨
        lr = LayoutResult(page_id="p", elements=[
            BBoxItem(element_id=eid, type="image", bbox=(0, 0, 0, 0), reading_order=1)])
        LayoutBraille().layout(bo, page_no=1, job_id="img", layout_result=lr)
        result = (tmp_path / "storage/jobs/img/temp/page_001/result/001_result.txt"
                  ).read_text(encoding="utf-8")
        dec = decode(result)
        assert "세포 구조" in dec and "핵" in dec


class TestExtraDrafts:
    """생략·참조 안 — 정답 도서의 점형과 셀 단위로 같아야 한다 (원장 C-28).

    아래 기대값은 EBS-E26-009 본책 p0020(별책 참조)과 여러 책의 '생략 고지'에서 그대로
    떠 온 정답 셀이다. 형식이 흔들리면 여기서 깨진다.
    """

    def _cells(self, draft) -> str:
        opt = LLMOutput(element_id=uuid4(), corrected_text=draft.text, render_mode="narrative",
                        routing_tier="ZERO", processing_time_ms=0,
                        drafts=[draft], selected_idx=0)
        return "".join(ImageBraille().translate([opt])[0].drafts[0].braille_lines)

    def test_재료가_없으면_설명이_유형어만_낸다(self):
        """'유형만'을 별도 안으로 두지 않아도 그 점형이 나온다.

        gold 900쪽 표본에 `⠠⠄지도⠠⠄` 꼴이 4건 있다(전체 411건의 1%). 별도 안으로 두면
        피커에 고를 것 없는 칸이 하나 더 서므로, **설명이 재료 없을 때의 모습**으로 흡수했다.
        """
        assert self._cells(desc_draft("그림", "", "", [])[0]) == "⠠⠄⠈⠪⠐⠕⠢⠠⠄"
        assert self._cells(desc_draft("지도", "", "", [])[0]) == "⠠⠄⠨⠕⠊⠥⠠⠄"

    def test_별책참조_정답셀(self):
        assert self._cells(volume_ref_draft("그림", "20-4")) == \
            "⠠⠄⠈⠪⠐⠕⠢⠀⠼⠃⠚⠤⠼⠙⠀⠰⠣⠢⠨⠥⠠⠄"

    def test_생략고지_정답셀(self):
        assert self._cells(omission_draft("그림")) == "⠠⠄⠈⠪⠐⠕⠢⠀⠠⠗⠶⠐⠜⠁⠠⠄"

    def test_별책참조_번호는_묵자쪽_순번(self):
        """번호는 '묵자쪽-그 쪽에서의 순번'이다 — 요소 하나만 봐서는 못 만든다."""
        outs = [LLMOutput(element_id=uuid4(), corrected_text="x", render_mode="narrative",
                          routing_tier="ZERO", processing_time_ms=0,
                          drafts=[volume_ref_draft("그림")], selected_idx=0) for _ in range(3)]
        _number_volume_refs(outs, 20)
        assert [o.drafts[0].text for o in outs] == [
            "<!주>그림 20-1 참조<!/주>",
            "<!주>그림 20-2 참조<!/주>",
            "<!주>그림 20-3 참조<!/주>",
        ]
