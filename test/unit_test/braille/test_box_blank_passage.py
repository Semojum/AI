"""평가문제 지문 글상자에는 앞뒤 빈 줄을 두지 않는다 (2026-08-10, 원장 C-33).

조항이 둘 겹쳐 있다:
    §2.1.6(5) 글상자 위아래를 한 줄씩 띈다.
              단, 평가문제에서 글상자가 지문으로 제시된 경우 '4.2.2 (2)'를 따른다.
    §4.2.2(2) 발문과 선택지, 발문과 지문, 지시문과 지문 사이에는 **빈 줄을 두지 않는다.**

종전에는 §2.1.6(5)만 보고 전부 띄웠다. 실측 — 10쪽에서 위 100%·아래 94%인데
정답 도서 2,917쪽은 위 21.1%·아래 31.1%다(관행이 아니라 규정과 맞는 값: 일반 상자는
띄고 지문 상자는 안 띈다).

발문과 상자 사이에 단서 `(단, …)`·그림 캡션이 끼는 일이 잦아 **직전 요소만 보면 2/6**밖에
못 잡는다. 발문을 만나면 다음 **제목**까지를 지문 구간으로 본다 → 10쪽 표본 5/6(83%),
정답 도서 목표치(~79%)와 같은 자리.
"""
from __future__ import annotations

import os
import tempfile
from uuid import uuid4

import pytest

from app.ai.braille.layout_braille import LayoutBraille
from app.ai.braille.text_braille import TextBraille
from app.schemas.content import LLMOutput
from app.schemas.layout import BBoxItem, LayoutResult

_BOX = ("<!상자>보기<!/상자>\n"
        "ㄱ. A는 간기에 복제된다.\n"
        "<!상자끝><!/상자끝>")
_PROMPT = "이에 대한 설명으로 옳은 것만을 <보기>에서 있는 대로 고른 것은?"
_PLAIN = "등차수열과 등비수열의 뜻을 정리하면 다음과 같다."


def _render(lead: str, lead_type: str = "text") -> list[str]:
    e1, e2 = uuid4(), uuid4()
    outs = [
        LLMOutput(element_id=e1, corrected_text=lead, render_mode="text_only",
                  routing_tier="ZERO", processing_time_ms=0),
        LLMOutput(element_id=e2, corrected_text=_BOX, render_mode="text_only",
                  routing_tier="ZERO", processing_time_ms=0),
    ]
    bo = TextBraille().translate(outs)
    lr = LayoutResult(page_id="p", elements=[
        BBoxItem(element_id=e1, type=lead_type, bbox=(0, 0, 0, 0), reading_order=1),
        BBoxItem(element_id=e2, type="text", bbox=(0, 0, 0, 0), reading_order=2)])
    d = tempfile.mkdtemp()
    cwd = os.getcwd()
    os.chdir(d)
    try:
        LayoutBraille().layout(bo, page_no=1, job_id="t", layout_result=lr)
        text = open(f"{d}/storage/jobs/t/temp/page_001/result/001_result.txt",
                    encoding="utf-8").read()
    finally:
        os.chdir(cwd)
    return text.splitlines()


def _render_three(a: str, b: str, c: str) -> list[str]:
    ids = [uuid4() for _ in range(3)]
    outs = [LLMOutput(element_id=i, corrected_text=t, render_mode="text_only",
                      routing_tier="ZERO", processing_time_ms=0)
            for i, t in zip(ids, (a, b, c))]
    bo = TextBraille().translate(outs)
    lr = LayoutResult(page_id="p", elements=[
        BBoxItem(element_id=i, type="text", bbox=(0, 0, 0, 0), reading_order=k)
        for k, i in enumerate(ids, start=1)])
    d = tempfile.mkdtemp()
    cwd = os.getcwd()
    os.chdir(d)
    try:
        LayoutBraille().layout(bo, page_no=1, job_id="t", layout_result=lr)
        return open(f"{d}/storage/jobs/t/temp/page_001/result/001_result.txt",
                    encoding="utf-8").read().splitlines()
    finally:
        os.chdir(cwd)


def _box_top_index(lines: list[str]) -> int:
    return next(i for i, ln in enumerate(lines) if ln.startswith("⠿⠛"))


class TestPassageBox:
    def test_발문_뒤_상자는_빈_줄_없음(self) -> None:
        lines = _render(_PROMPT)
        i = _box_top_index(lines)
        assert lines[i - 1].strip(), "발문과 지문 상자 사이에 빈 줄이 있다 (§4.2.2(2))"

    def test_일반_문장_뒤_상자는_빈_줄_있음(self) -> None:
        lines = _render(_PLAIN)
        i = _box_top_index(lines)
        assert not lines[i - 1].strip(), "일반 글상자는 위를 띄어야 한다 (§2.1.6(5))"

    @pytest.mark.parametrize("lead,want_blank", [(_PROMPT, False), (_PLAIN, True)])
    def test_아래도_같이_간다(self, lead: str, want_blank: bool) -> None:
        """아래 테두리 다음 줄. ⚠ 뒤에 요소가 없으면 **페이지 하단 패딩**이 빈 줄로 세어져
        판정이 뒤집힌다 — 후속 요소를 두고 잰다."""
        lines = _render_three(lead, _BOX, "① ㄱ  ② ㄷ  ③ ㄱ, ㄴ")
        i = next(k for k, ln in enumerate(lines) if ln.startswith("⠿⠶"))
        assert (not lines[i + 1].strip()) is want_blank


class TestPromptDetect:
    @pytest.mark.parametrize("src,want", [
        (_PROMPT, True),
        ("옳은 것은?", True),
        ("<!주>그림<!/주>", False),
        (_PLAIN, False),
        ("", False),
        ("여러 줄\n마지막이 물음인가?", True),
        ("물음표가 앞에 있나? 아니다.", False),
    ])
    def test_발문_판정(self, src: str, want: bool) -> None:
        assert LayoutBraille._is_prompt_text(src) is want

    def test_제목이_지문_구간을_닫는다(self) -> None:
        """제목이 나오면 새 단락이다 — 그 뒤 상자는 다시 띄운다."""
        e1, e2, e3 = uuid4(), uuid4(), uuid4()
        outs = [
            LLMOutput(element_id=e1, corrected_text=_PROMPT, render_mode="text_only",
                      routing_tier="ZERO", processing_time_ms=0),
            LLMOutput(element_id=e2, corrected_text="등차수열", render_mode="text_only",
                      routing_tier="ZERO", processing_time_ms=0),
            LLMOutput(element_id=e3, corrected_text=_BOX, render_mode="text_only",
                      routing_tier="ZERO", processing_time_ms=0),
        ]
        bo = TextBraille().translate(outs)
        lr = LayoutResult(page_id="p", elements=[
            BBoxItem(element_id=e1, type="text", bbox=(0, 0, 0, 0), reading_order=1),
            BBoxItem(element_id=e2, type="title", bbox=(0, 0, 0, 0), reading_order=2),
            BBoxItem(element_id=e3, type="text", bbox=(0, 0, 0, 0), reading_order=3)])
        d = tempfile.mkdtemp()
        cwd = os.getcwd()
        os.chdir(d)
        try:
            LayoutBraille().layout(bo, page_no=1, job_id="t", layout_result=lr)
            lines = open(f"{d}/storage/jobs/t/temp/page_001/result/001_result.txt",
                         encoding="utf-8").read().splitlines()
        finally:
            os.chdir(cwd)
        i = _box_top_index(lines)
        assert not lines[i - 1].strip(), "제목 뒤 상자는 다시 띄어야 한다"
