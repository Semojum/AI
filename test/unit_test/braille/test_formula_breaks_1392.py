"""#1392 — 수식 요소 끊을 자리: 「한국 점자 규정」 수학 점자 제66항(재추출 4287~4288행)
"한 수식이 두 줄 이상 이어질 경우에는 사칙연산, 등호, 분수표 뒤에서 줄바꿈을 하고 …"."""
import uuid

import app.ai.braille.translator  # noqa: F401 — 제품처럼 convert_latex 마지막 그물(_w2c)을 켠다
from app.ai.braille.formula_braille import FormulaBraille
from app.ai.braille.kor_math_rules import BREAK_MARK, convert_latex
from app.ai.braille.layout_braille import _wrap_line
from app.schemas.content import LLMOutput
from app.utils.braille_ascii import ascii_to_unicode


def _formula(latex: str):
    bo = FormulaBraille()._translate_one(LLMOutput(element_id=uuid.uuid4(), corrected_text=latex, routing_tier="STANDARD"))
    return bo.braille_lines[0], bo.break_points[0]


def test_제66항_예문대로_덧셈_뒤에서_접는다():
    # 재추출 4289~4300행 예문(두 칸 들여 첫 줄). 줄 끝 채움 백틱은 칸 띄우기라 뗐다.
    line1 = ascii_to_unicode("(8x5#a08x5#b08x5#c0)/#a5")
    line2 = ascii_to_unicode("(x5#b)/#a")
    cells, breaks = _formula(r"\frac{1}{(x+1)(x+2)(x+3)}+\frac{1}{x+2}")
    assert cells == line1 + line2                          # 셀은 그대로다
    assert len(line1) in breaks                            # 맨 바깥 + 뒤
    assert _wrap_line(cells, breaks, width=32, first_width=30) == ([line1, line2], 0)


def test_부호와_첨자_안_기호_뒤는_끊지_않는다():
    cells, breaks = _formula(r"y = - 3 ^ {- 1} + \frac {3}{2}")
    assert cells.startswith("⠽⠒⠒⠔⠼⠉⠘⠔⠼⠁⠢")
    assert 3 in breaks and 11 in breaks                    # = 뒤 · + 뒤
    assert 4 not in breaks and 8 not in breaks             # = 다음 부호 − · 위첨자 안 −


def test_표시_글자가_점자에_남지_않는다():
    cells, breaks = _formula(r"a + b = \frac {c}{d}")
    assert BREAK_MARK not in cells and BREAK_MARK not in convert_latex(r"a + b = \frac {c}{d}")
    assert breaks


def test_배열_행_머리_등호_앞_빈칸에서_끊지_않는다():
    # #1394 — 유도 사슬 행 머리 등호 앞 행 구분 빈칸(⠀⠀)에서 접으면 등호가 줄 머리로 간다. 제66항은 등호 뒤에서 끊는다.
    cells, breaks = _formula(r"\begin{array}{l} a + b \\ = c + d \\ = e \end{array}")
    heads = [i for i in range(2, len(cells)) if cells[i - 2:i] == "⠀⠀" and cells.startswith("⠒⠒", i)]
    assert len(heads) == 2
    for i in heads:
        assert i - 2 not in breaks and i - 1 not in breaks      # 행 구분 빈칸
        assert i + 2 in breaks                                   # 행 머리 등호 바로 뒤
    for width in range(4, len(cells)):
        lines, forced = _wrap_line(cells, breaks, width=width, first_width=width)
        if not forced:                                           # 칸이 좁아 강제로 자른 폭은 뺀다
            assert not any(ln.lstrip("⠀").startswith("⠒⠒") for ln in lines[1:]), width


def test_연립식_행_머리_부호_앞은_그대로_끊는다():
    # 행 머리 − 는 부호라(둘째 식의 머리) 행 구분 빈칸이 끊을 자리로 남는다.
    cells, breaks = _formula(r"\left\{ \begin{array}{l} x + y = 1 \\ - x + y = 3 \end{array} \right.")
    i = cells.index("⠀⠀⠔")
    assert i in breaks and i + 1 in breaks
