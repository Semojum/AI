"""짧은 선택지를 3-2 · 2-2-1 로 합친다(이슈 #1238, 원장 C-166).

「점자 도서 제작 지침」 3장 3절 2. 4)(3)(`점자 도서 제작 지침_재추출.txt` 3449~3456행): 한 줄에 둘 이상 들어가면
두 칸 띄워 5지는 3개면 3-2, 2개면 2-2-1 로 적는다. 기대값은 같은 절 [예 3-68](3459~3479행)의 점자 줄 그대로다 —
3470~3471행 `①ⓐ` 다섯 = 3-2 · 3477~3479행 `①㉠, ㉡` 다섯 = 2-2-1(셋이면 들임 2 + 13 × 3 + 4 = 45칸이라 안 들어간다).
화면(통 문자열 `flatten_elements`)과 다운로드(조판 `layout`)가 같은 줄을 내야 한다.
"""
from __future__ import annotations

import asyncio
import contextvars
from unittest.mock import patch
from uuid import uuid4

from app.ai.braille.constants import CHOICES_ONE_PER_LINE
from app.ai.braille.layout_braille import LayoutBraille, _combine_choice_lines, flatten_elements
from app.ai.braille.translator import translate_body
from app.core import limits, pipeline
from app.schemas.content import BrailleOutput, RuleApplication
from app.schemas.layout import BBoxItem, LayoutResult
from app.schemas.task import PageTask
from protos.generated import braille_service_pb2 as pb

_A = "①ⓐ\n②ⓑ\n③ⓒ\n④ⓓ\n⑤ⓔ"
_K = "①㉠, ㉡\n②㉠, ㉢\n③㉡, ㉢\n④㉡, ㉣\n⑤㉢, ㉣"
# [예 3-68] 점자 줄(재추출본 3470~3471 · 3477~3479행, 백틱 = 빈칸)
_A_ROWS = ["⠀⠀⠼⠂⠀⠶⠴⠁⠶⠀⠀⠼⠆⠀⠶⠴⠃⠶⠀⠀⠼⠒⠀⠶⠴⠉⠶",
           "⠀⠀⠼⠲⠀⠶⠴⠙⠶⠀⠀⠼⠢⠀⠶⠴⠑⠶"]
_K_ROWS = ["⠀⠀⠼⠂⠀⠶⠿⠁⠶⠐⠀⠶⠿⠒⠶⠀⠀⠼⠆⠀⠶⠿⠁⠶⠐⠀⠶⠿⠔⠶",
           "⠀⠀⠼⠒⠀⠶⠿⠒⠶⠐⠀⠶⠿⠔⠶⠀⠀⠼⠲⠀⠶⠿⠒⠶⠐⠀⠶⠿⠂⠶",
           "⠀⠀⠼⠢⠀⠶⠿⠔⠶⠐⠀⠶⠿⠂⠶"]


def _bo(text: str) -> BrailleOutput:
    lines, breaks = translate_body(text)
    return BrailleOutput(element_id=uuid4(), corrected_text=text, braille_lines=lines, break_points=breaks)


def _both(text: str, etype: str = "list_item") -> tuple[list[str], list[str]]:
    """(통 문자열 줄, 조판 줄). 둘 다 같은 요소를 새로 점역해 따로 잰다."""
    out = []
    for flat in (True, False):
        bo = _bo(text)
        lr = LayoutResult(page_id="p1", elements=[
            BBoxItem(element_id=bo.element_id, type=etype, bbox=(0, 0, 1, 1), reading_order=1)])
        if flat:
            out.append(flatten_elements([bo], lr)[bo.element_id].text.strip("\n").split("\n"))
        else:
            LayoutBraille().layout([bo], page_no=1, job_id="t", layout_result=lr)
            out.append(bo.braille_lines)
    return out[0], out[1]


def test_예3_68_셋이_들어가면_3_2():
    assert _both(_A) == (_A_ROWS, _A_ROWS)


def test_예3_68_둘만_들어가면_2_2_1():
    assert _both(_K) == (_K_ROWS, _K_ROWS)


def test_길면_한_줄에_하나():
    text = "\n".join(f"{c} 세포 호흡이 일어나 에너지를 얻는다." for c in "①②③④⑤")
    flat, lay = _both(text)
    assert len(flat) == 5 and all(ln.startswith("⠀⠀⠼") for ln in flat)


def test_4지는_둘씩():
    flat, _ = _both("①ⓐ\n②ⓑ\n③ⓒ\n④ⓓ")
    assert flat == ["⠀⠀⠼⠂⠀⠶⠴⠁⠶⠀⠀⠼⠆⠀⠶⠴⠃⠶", "⠀⠀⠼⠒⠀⠶⠴⠉⠶⠀⠀⠼⠲⠀⠶⠴⠙⠶"]


def test_6지는_안_합친다():
    flat, _ = _both(_A + "\n⑥ⓕ")
    assert len(flat) == 6


def test_낱값을_켜면_한_줄에_하나():
    """④ 초등 이하 문제 자료 · 한 줄에 하나로 적는 책은 요청 낱값으로 끈다. 문맥 밖으로 안 샌다."""
    def on():
        CHOICES_ONE_PER_LINE.set(True)
        return _both(_A)[0]
    assert len(contextvars.copy_context().run(on)) == 5
    assert _both(_A)[0] == _A_ROWS


def test_서버_스위치로_되돌린다(monkeypatch):
    monkeypatch.setenv("CHOICE_COMBINE", "0")
    assert len(_both(_A)[0]) == 5


def test_근거_좌표가_묶인_줄로_옮겨지고_두_번_불러도_같다():
    bo = _bo(_A)
    item2 = bo.braille_lines[1]
    bo.rule_trail = [RuleApplication(rule_id="t", source="t", section="t", rule_name="t", contents="t",
                                     line_no=1, col_start=3, col_end=len(item2)),
                     RuleApplication(rule_id="u", source="u", section="u", rule_name="u", contents="u",
                                     line_no=4, col_start=0, col_end=2)]
    _combine_choice_lines(bo, "list_item", 2)
    once = (list(bo.braille_lines), bo.corrected_text, [r.model_dump() for r in bo.rule_trail])
    _combine_choice_lines(bo, "list_item", 2)
    assert (bo.braille_lines, bo.corrected_text, [r.model_dump() for r in bo.rule_trail]) == once
    r2, r5 = bo.rule_trail
    assert (r2.line_no, bo.braille_lines[0][r2.col_start:r2.col_end]) == (0, item2[3:])
    assert (r5.line_no, bo.braille_lines[1][r5.col_start:r5.col_end]) == (1, "⠼⠢")
    assert bo.corrected_text.split("\n") == ["①ⓐ  ②ⓑ  ③ⓒ", "④ⓓ  ⑤ⓔ"]


def test_묶은_줄_뒤_글은_안_접는다():
    """2-2 둘째 줄이 30칸이라 접기 문턱(28)을 넘는다. 다음 글을 묶은 줄 끝에 이으면 안 된다."""
    flat, _ = _both("①㉠, ㉡\n②㉠, ㉢\n③㉡, ㉢\n④㉡, ㉣\n다음 글을 읽고 물음에 답하시오.", etype="text")
    assert flat[:2] == _K_ROWS[:2] and len(flat) == 3


# ── 요청 낱값 배선(BrailleRequest 12) ─────────────────────────────────────────

def test_번호와_빈_값():
    assert pb.BrailleRequest.DESCRIPTOR.fields_by_name["choices_one_per_line"].number == 12
    old = pb.BrailleRequest(job_id="j", page_no=3, mode="c")
    assert old.SerializeToString() == pb.BrailleRequest(job_id="j", page_no=3, mode="c",
                                                        choices_one_per_line=False).SerializeToString()
    assert PageTask.from_proto(pb.BrailleRequest(job_id="j", page_no=1, choices_one_per_line=True)).choices_one_per_line
    assert not PageTask.from_proto(old).choices_one_per_line


def test_run_이_조판_풀까지_값을_넘긴다():
    """조판(flatten · layout)도 `run_braille` 로 돈다. 동시 요청끼리, 이어 돈 쪽끼리 안 섞인다."""
    seen: dict = {}

    async def fake(task):
        seen[task.job_id] = await limits.run_braille(CHOICES_ONE_PER_LINE.get)
        await asyncio.sleep(0.01)
        return {"status": "OK", "processing_meta": {}, "braille_text_list": []}

    async def go():
        await asyncio.gather(pipeline.run(PageTask(job_id="on", page_no=1, mode="c", choices_one_per_line=True)),
                             pipeline.run(PageTask(job_id="off", page_no=1, mode="c")))
        await pipeline.run(PageTask(job_id="after", page_no=1, mode="c"))

    with patch.object(pipeline, "_run_pipeline", fake), \
         patch.object(pipeline, "_record_metrics", lambda *a, **k: None):
        asyncio.run(go())
    assert seen == {"on": True, "off": False, "after": False}
