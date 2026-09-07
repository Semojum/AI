"""삼각함수 역맵 — 규정 제47항.

sin=⠖⠎ · cos=⠖⠉ · tan=⠖⠞ · sec=⠖⠤ · csc=⠖⠣ · cot=⠖⠳ 가 역맵에 통째로 없어
`tan x` 가 `∈얼옥` 으로 깨졌다. 규정 제11항 예시에서 바로 재현된다.

★ 표는 **정방향 `kor_math_rules._TRIG` 를 뒤집어** 만든다 — 손으로 적으면 어긋난다.
"""
import pytest

from app.utils.braille_ascii import ascii_to_unicode
from app.utils.braille_back import decode


@pytest.mark.parametrize("brf,expect", [
    ("6sx", "sin"), ("6cx", "cos"), ("6tx", "tan"),
])
def test_삼각함수를_읽는다(brf, expect):
    assert expect in decode(ascii_to_unicode(brf, backtick="space"), math=True)


def test_규정_제11항_예시():
    # tan x의 값은 (3+√5)/2 이다.
    d = decode(ascii_to_unicode("``6tx``w`$b'z``#b/(#c5>#e)``oi4`", backtick="space"))
    assert "tan" in d and "분의" in d and "√" in d, d


def test_정방향_표를_그대로_뒤집는다():
    from app.ai.braille.kor_math_rules import _TRIG
    from app.utils.braille_back import _MATH_REV_MULTI
    for name, cells in _TRIG.items():
        assert _MATH_REV_MULTI.get(cells) == name, f"{name} 이 역맵과 어긋난다"
