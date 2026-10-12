"""글상자 위아래 빈 줄 — 일반 상자는 띄고 평가문제 지문 상자 · 속글상자는 안 띈다(원장 C-33 · C-168, #1341).

「점자 도서 제작 지침」 1장 2절 5. 2)(6)(재추출 489~490행): 글상자 위아래에 빈 줄, 잇달아 나와도 사이에 빈 줄.
예외: 3장 평가문제 2)(3)(2990행) 지시문 · 발문과 지문 사이 빈 줄 없음 · 3)(4)(3094~3095행) 속글상자 위아래 빈 줄 없음.

★ 응답 contents(점역사가 받는 화면 · 다운로드 · 앱이 조판하는 글)와 쪽 조판 result.txt 가 **같은 함수**로 정한다.
  종전에는 쪽 조판(`_expand_box_borders`)에만 있어 제품에는 한 번도 안 갔다. 그래서 시험도 두 출력을 같이 본다.
지문 구역 = 문항 머리 · 묶음 지시 · 발문(`?`, 뒤 `(단, …)` · `[3점]`) · 지시문(`…시오.`) 요소에서 열고 제목에서 닫는다.
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


class TestQuestionZone:
    @pytest.mark.parametrize("src,want", [
        (_PROMPT, True),
        ("옳은 것은?", True),
        ("<!주>그림<!/주>", False),
        (_PLAIN, False),
        ("", False),
        ("여러 줄\n마지막이 물음인가?", True),
        ("물음표가 앞에 있나? 아니다.", False),
        ("옳은 것만을 <보기>에서 있는 대로 고른 것은? (단, 돌연변이는 고려하지 않는다.)", True),
        ("적절한 것은? [3점]", True),
        ("07 [26025-0079] 다음은 골격근의 수축 과정에 대한 자료이다.", True),   # 문항 머리
        ("[01~03] 다음 글을 읽고 물음에 답하시오.", True),                      # 묶음 지시 · 지시문
        ("빈칸에 들어갈 알맞은 말을 쓰시오.", True),
        ("$\\sqrt{2} \\times 4 \\text {의   값은?}$", True),                  # 수식 요소 발문
        ("[2부] 적용 학습", False),
    ])
    def test_지문_구역을_여는_요소(self, src: str, want: bool) -> None:
        from app.ai.braille.layout_braille import _opens_question

        assert _opens_question(src) is want

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


# ── 응답 contents · 쪽 조판 result.txt 가 같은 자리에 빈 줄을 낸다(#1341) ─────────────────────────
_TOP, _BOT = "<!상자><!/상자>", "<!상자끝><!/상자끝>"


def _two_outputs(items: list[tuple[str, str, int]]) -> tuple[list[str], list[str]]:
    """[(묵자 글, 요소 유형, 제목 단계)] → (응답 contents 를 이은 줄, 쪽 조판 줄). 응답 쪽이 BE · FE · 앱이 조판하는 글이다."""
    from app.ai.braille.layout_braille import flatten_elements

    ids = [uuid4() for _ in items]
    outs = [LLMOutput(element_id=i, corrected_text=t, render_mode="text_only",
                      routing_tier="ZERO", processing_time_ms=0) for i, (t, _ty, _h) in zip(ids, items)]
    bo = TextBraille().translate(outs)
    lr = LayoutResult(page_id="p", elements=[
        BBoxItem(element_id=i, type=ty, bbox=(0, 0, 0, 0), reading_order=k, heading_level=h or None)
        for k, (i, (_t, ty, h)) in enumerate(zip(ids, items), start=1)])
    flat = flatten_elements(bo, lr)                       # 파이프라인 차례: 응답이 먼저, 조판이 뒤
    contents = "".join(flat[i].text for i in ids if i in flat).split("\n")
    pages, _ = LayoutBraille().render(bo, 1, layout_result=lr)
    # 면 끝 페이지행 줄과 그 위 채움 빈 줄은 본문이 아니다(26줄 면 = 본문 25줄 + 페이지행).
    body = [ln for pg in pages for ln in (pg[:-1] if len(pg) == 26 else pg)]
    while body and not body[-1].strip(" ⠀"):
        body.pop()
    return contents, body


def _gaps(lines: list[str]) -> list[tuple[str, str, bool]]:
    """테두리마다 (위 · 아래, 꼴, 바깥쪽 이웃 줄이 빈 줄인가)."""
    blank = lambda k: 0 <= k < len(lines) and not lines[k].strip(" ⠀")
    out = []
    for i, ln in enumerate(lines):
        if ln[:2] in ("⠿⠛", "⠖⠒"):
            out.append(("위", ln[:2], blank(i - 1)))
        elif ln[:2] in ("⠿⠶", "⠓⠒"):
            out.append(("아래", ln[:2], blank(i + 1)))
    return out


def _no_double_blank(lines: list[str]) -> bool:
    body = lines[:max(i for i, ln in enumerate(lines) if ln.strip(" ⠀")) + 1]
    return not any(not body[i].strip(" ⠀") and not body[i + 1].strip(" ⠀") for i in range(len(body) - 1))


class TestBothOutputs:
    def test_일반_상자_요소_안쪽_위아래를_띈다(self) -> None:
        c, r = _two_outputs([("앞 문장입니다.\n" + _TOP + "\n가나다\n" + _BOT + "\n뒤 문장입니다.", "text", 0)])
        assert _gaps(c) == _gaps(r) == [("위", "⠿⠛", True), ("아래", "⠿⠶", True)]

    def test_지문_구역_요소_안쪽은_안_띈다(self) -> None:
        src = "07 [26025-0079] 다음은 골격근에 대한 자료이다.\n" + _TOP + "\n가나다\n" + _BOT + "\n이에 대한 설명으로 옳은 것은?"
        c, r = _two_outputs([(src, "text", 0)])
        assert _gaps(c) == _gaps(r) == [("위", "⠿⠛", False), ("아래", "⠿⠶", False)]

    def test_속글상자_위아래는_안_띈다(self) -> None:
        src = ("앞 문장입니다.\n" + _TOP + "\n가나다\n<!상자2><!/상자2>\n라마바\n<!상자끝2><!/상자끝2>\n사아자\n"
               + _BOT + "\n뒤 문장입니다.")
        c, r = _two_outputs([(src, "text", 0)])
        want = [("위", "⠿⠛", True), ("위", "⠖⠒", False), ("아래", "⠓⠒", False), ("아래", "⠿⠶", True)]
        assert _gaps(c) == _gaps(r) == want

    def test_요소_경계_빈_줄은_한_줄이다(self) -> None:
        c, r = _two_outputs([("앞 문장입니다.", "text", 0), (_TOP + "\n가나다\n" + _BOT, "text", 0),
                             ("뒤 문장입니다.", "text", 0), (_TOP + "\n라마바\n" + _BOT, "text", 0),
                             ("끝 문장입니다.", "text", 0)])
        assert _gaps(c) == _gaps(r) == [("위", "⠿⠛", True), ("아래", "⠿⠶", True)] * 2
        assert _no_double_blank(c) and _no_double_blank(r)

    def test_잇달은_상자_사이는_한_줄이다(self) -> None:
        c, r = _two_outputs([("앞 문장입니다.", "text", 0), (_TOP + "\n가나다\n" + _BOT, "text", 0),
                             (_TOP + "\n라마바\n" + _BOT, "text", 0), ("끝 문장입니다.", "text", 0)])
        assert _gaps(c) == _gaps(r) == [("위", "⠿⠛", True), ("아래", "⠿⠶", True)] * 2
        assert _no_double_blank(c) and _no_double_blank(r)

    def test_쪽_첫_요소_상자는_머리에_빈_줄이_없다(self) -> None:
        c, r = _two_outputs([(_TOP + "\n가나다\n" + _BOT, "text", 0), ("뒤 문장입니다.", "text", 0)])
        assert c[0].startswith("⠿⠛") and r[0].startswith("⠿⠛")

    def test_윗줄_5칸_제목_뒤_상자는_제목과_붙는다(self) -> None:
        """4단계 제목(5칸, 뒤 빈 줄 없음)이 상자 바로 위면 상자 제목이다(지침 1장 2절 5. 2)(4)① 399행). 빈 줄은 제목 위다."""
        c, r = _two_outputs([("앞 문장입니다.", "text", 0), ("과학 돋보기", "title", 4),
                             (_TOP + "\n가나다\n" + _BOT, "text", 0), ("뒤 문장입니다.", "text", 0)])
        assert _gaps(c)[0] == _gaps(r)[0] == ("위", "⠿⠛", False)
        for lines in (c, r):
            t = next(i for i, ln in enumerate(lines) if ln.startswith("⠀⠀⠀⠀") and not ln.startswith("⠀⠀⠀⠀⠀"))
            assert not lines[t - 1].strip(" ⠀")          # 제목 위는 띈다(4단계 제목 앞 빈 줄)
