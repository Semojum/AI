"""#1424(원장 C-175) — 글상자 안 표는 위아래에 빈 줄을 두지 않는다. 상자 밖 표는 종전대로 한 줄씩 띈다.

표 위아래 한 줄(「점자 도서 제작 지침」 2장 2절 2. 2)(2)④ 905행)과 속글상자 위아래 빈 줄 없음(3장 평가문제 3)(4)
3095~3096행)이 맞서 모호 → 관행. gold dev · val 상자 안 표 134 중 93% 가 붙여 적는다.
응답 contents(`flatten_elements`)와 쪽 조판(`layout` → result.txt)이 같은 `_block_blanks` 를 쓰므로 둘 다 본다.
"""
import os
import tempfile
from uuid import uuid4

import pytest

from app.ai.braille.layout_braille import LayoutBraille, flatten_elements
from app.ai.braille.table_braille import _TBL_BOT, _TBL_TOP, TableBraille
from app.ai.braille.text_braille import TextBraille
from app.schemas.content import LLMOutput
from app.schemas.layout import BBoxItem, LayoutResult

_OPEN = "<!상자>보기<!/상자>\n상자 안 글이다."
_CLOSE = "<!상자끝><!/상자끝>\n상자 밖 글이다."


def _outputs(box_level: int):
    ids = [uuid4() for _ in range(3)]
    texts = (_OPEN, _CLOSE) if box_level else ("앞 글이다.", "뒤 글이다.")
    text = [LLMOutput(element_id=i, corrected_text=t, render_mode="text_only", routing_tier="ZERO")
            for i, t in zip((ids[0], ids[2]), texts)]
    table = LLMOutput(element_id=ids[1], corrected_text="구분|2000년\n초혼|88.9",
                      render_mode="table_grid", routing_tier="ZERO")
    bos = TextBraille().translate(text)
    tb = TableBraille({ids[1]: box_level} if box_level else {}).translate([table])[0]
    lr = LayoutResult(page_id="p", elements=[
        BBoxItem(element_id=i, type=t, bbox=(0, 0, 0, 0), reading_order=k)
        for k, (i, t) in enumerate(zip(ids, ("text", "table", "text")), start=1)])
    return [bos[0], tb, bos[1]], lr, ids


def _contents(box_level: int) -> list[str]:
    bos, lr, ids = _outputs(box_level)
    flat = flatten_elements(bos, lr)
    return "".join(flat[i].text for i in ids).split("\n")


def _page(box_level: int) -> list[str]:
    bos, lr, _ = _outputs(box_level)
    d, cwd = tempfile.mkdtemp(), os.getcwd()
    os.chdir(d)
    try:
        LayoutBraille().layout(bos, page_no=1, job_id="t", layout_result=lr)
        return open(f"{d}/storage/jobs/t/temp/page_001/result/001_result.txt", encoding="utf-8").read().splitlines()
    finally:
        os.chdir(cwd)


def _around_table(lines: list[str], top: str, bot: str) -> tuple[str, str]:
    return lines[lines.index(top) - 1], lines[lines.index(bot) + 1]


L2_TOP, L2_BOT = "⠖" + "⠒" * 30 + "⠲", "⠓" + "⠒" * 30 + "⠚"


@pytest.mark.parametrize("render", [_contents, _page])
def test_상자_안_표는_위아래_빈_줄이_없다(render, monkeypatch):
    monkeypatch.delenv("INNER_TABLE_BLANKS", raising=False)
    above, below = _around_table(render(1), L2_TOP, L2_BOT)
    assert above.strip("⠀ ") and below.startswith("⠿⠶")      # 위는 상자 안 글 · 아래는 바로 바깥 상자 아래 테두리


@pytest.mark.parametrize("render", [_contents, _page])
def test_상자_밖_표와_끈_스위치는_종전대로_띈다(render, monkeypatch):
    monkeypatch.delenv("INNER_TABLE_BLANKS", raising=False)
    assert _around_table(render(0), _TBL_TOP, _TBL_BOT) == ("", "")
    monkeypatch.setenv("INNER_TABLE_BLANKS", "1")
    assert _around_table(render(1), L2_TOP, L2_BOT) == ("", "")
