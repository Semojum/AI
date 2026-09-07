"""부정 부등호 4종 — 수학 점자 제4항 3·5·7·9호.

긍정형 앞에 ⠨(폰트 ".")를 붙인다. 표에 아예 없어서 **기호가 통째로 사라졌다** —
`x \\ngtr 0` 이 `x0` 으로 나가 식의 뜻이 반대가 됐다.
"""
import pytest

from app.ai.braille.kor_math_rules import convert_latex
from app.utils.braille_ascii import unicode_to_ascii


def _brf(t: str) -> str:
    return unicode_to_ascii(convert_latex(t)).replace("`", "").strip()


@pytest.mark.parametrize("tex,want", [
    (r"x \ngtr 0", ".55"),    # 3호
    (r"x \nless y", ".99"),   # 5호
    (r"x \ngeq y", ".44"),    # 7호
    (r"x \nleq y", ".66"),    # 9호
])
def test_부정_부등호(tex, want):
    assert want in _brf(tex)


@pytest.mark.parametrize("uni,want", [("x≯0", ".55"), ("x≮y", ".99"),
                                      ("x≱y", ".44"), ("x≰y", ".66")])
def test_유니코드도_같은_점형(uni, want):
    assert want in _brf(uni)


@pytest.mark.parametrize("tex,want", [
    (r"a > b", "55"), (r"x < 0", "99"), (r"x \ge 5", "44"), (r"x \le 0", "66"),
])
def test_긍정형은_그대로(tex, want):
    got = _brf(tex)
    assert want in got and "." + want not in got
