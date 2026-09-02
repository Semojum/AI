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
