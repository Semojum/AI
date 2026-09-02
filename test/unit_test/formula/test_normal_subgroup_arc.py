r"""정규부분군·호 — 수학 점자 제33·36항.

표에 없어 기호가 사라졌다. `G \rhd N` 이 `⠠⠛⠠⠝` 으로 나갔다.
호는 `\overparen` 계열만 알아서 `\overset{\frown}{AB}` 표기를 못 읽었다.
"""
import pytest

from app.ai.braille import translator as _t  # noqa: F401 — \text{한글} 훅 등록
from app.ai.braille.kor_math_rules import convert_latex


def _b(t: str) -> str:
    return convert_latex(t).replace("⠀", "")


@pytest.mark.parametrize("tex,want", [
    (r"G \rhd N", "⠸⠜"),      # 제33항
    (r"N \lhd G", "⠸⠣"),
    ("G ▷ N", "⠸⠜"),
    ("N ◁ G", "⠸⠣"),
])
def test_정규부분군(tex, want):
    assert want in _b(tex)


@pytest.mark.parametrize("tex", [r"\overset{\frown}{AB}", r"\overparen{AB}"])
def test_호(tex):
    assert "⠈⠪" in _b(tex)


@pytest.mark.parametrize("tex,want", [
    (r"x \ngtr 0", "⠭⠨⠢⠢⠼⠚"),               # 제4항 3호 — 여러 칸 관계 기호도 붙임
    (r"x \nleq y", "⠭⠨⠖⠖⠽"),                 # 제4항 9호
    ("10 : 3 = 5 : x", "⠼⠁⠚⠐⠂⠼⠉⠒⠒⠼⠑⠐⠂⠭"),   # 제9항 비례
    (r"\sqrt{3} \fallingdotseq 1.732", "⠜⠼⠉⠐⠒⠒⠼⠁⠲⠛⠉⠃"),  # 제20항 근사
    (r"\frac{dy}{dt} \cdot \frac{dt}{du}", "⠙⠞⠌⠙⠽⠐⠙⠥⠌⠙⠞"),  # 제2항 [붙임]
    (".47", "⠼⠲⠙⠛"),                          # 제8항 1호 — 수표 하나
])
def test_붙임과_소수(tex, want):
    assert convert_latex(tex).strip() == want
