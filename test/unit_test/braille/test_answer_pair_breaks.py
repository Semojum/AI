"""#1353 정답 목록 줄은 쌍 안(번호와 답 사이 한 칸)에서 접지 않는다.

엔진 · FE 는 응답 `breaks` 에서 32칸을 접는다. 쌍 안 빈칸이 목록에 있으면 `1 ②  2 ⑤  3 ⑤  4 ④  5` / `③  6 ②` 처럼
쌍이 갈린다(2027 dev · val 70곳). gold 는 쌍 사이 두 칸에서만 접는다(`01 ⑤  02 ③  03 ②  04 ④` / `05 ⑤ …`).
"""
from uuid import uuid4

import pytest

from app.ai.braille.text_braille import TextBraille
from app.ai.braille.translator import translate_body
from app.schemas.content import LLMOutput


def _breaks(src: str) -> tuple[str, list[int]]:
    out = TextBraille().translate([LLMOutput(element_id=uuid4(), corrected_text=src, render_mode="text_only",
                                             routing_tier="ZERO", processing_time_ms=0)])[0]
    return out.braille_lines[0], out.break_points[0]


@pytest.mark.parametrize("src", [
    "1 ②  2 ⑤  3 ⑤  4 ④  5 ③  6 ②",               # 동아시아사 해설 p8 꼴
    "01 ①  02 ③  03 ④  04 ③  05 ②  06 ④  07 ⑤  08 ①",
    "1 ⑤  2 ⑤  3 ②  4 ⑤  5 100  6 5  7 ⑤",         # 수학 띠 — 숫자 답이 섞인다
])
def test_정답_쌍_안에서는_안_접는다(src):
    line, br = _breaks(src)
    pairs = src.split("  ")
    at = 0
    for p in pairs:                                  # 점자에서 쌍마다 첫 빈칸 자리를 찾아 그 자리와 다음 칸이 목록에 없는지
        blank = line.index("⠀", at)
        assert blank not in br and blank + 1 not in br, (p, blank)
        nxt = line.find("⠀⠀", blank)
        if nxt < 0:
            break
        assert nxt in br or nxt + 1 in br or nxt + 2 in br   # 쌍 사이 두 칸에서는 접을 수 있다
        at = nxt + 2


def test_수학_선택지는_그대로():
    src = "① 1  ② 2  ③ 3"
    assert _breaks(src)[1] == translate_body(src)[1][0]
