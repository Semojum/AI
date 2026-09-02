r"""순환소수·소수점 — 수학 점자 제8항.

1호 소수점은 ⠲. 정수부가 없으면 **수표 뒤 바로 소수점**이다(`.47` = `#4dg`).
2호 순환마디는 그 **앞에 ⠈ 를 한 번만** 적는다. 마디가 둘로 떨어져 있어도 여는 자리에만.

종전에는 결합 점(U+0307)도 `\dot{}` 명령도 몰라 미지문자로 샜다 — 규정 예시 6건이
전부 틀렸다.
"""
import pytest

from app.ai.braille.kor_math_rules import convert_latex
from app.utils.braille_ascii import unicode_to_ascii


def _brf(t: str) -> str:
    return unicode_to_ascii(convert_latex(t)).replace("`", "").strip()


@pytest.mark.parametrize("src,want", [
    ("0.17", "#j4ag"),          # 1호
    ("0.6̇", "#j4@f"),     # 2호 — 결합 점
    ("0.73̇9̇", "#j4g@ci"),
    ("0.1̇234"[:4] + "̇" + "23̇", "#j4@abc"),
])
def test_규정_예시(src, want):
    assert _brf(src) == want


@pytest.mark.parametrize("src,want", [
    (r"0.\dot{6}", "#j4@f"),
    (r"0.7\dot{3}\dot{9}", "#j4g@ci"),
    (r"0.\dot{1}2\dot{3}", "#j4@abc"),
    (r".\dot{9}", "#4@i"),
])
def test_dot_명령도_같다(src, want):
    assert _brf(src) == want


@pytest.mark.parametrize("src,want", [("0.5", "#j4e"), ("3.14", "#c4ad")])
def test_평범한_소수는_그대로(src, want):
    assert _brf(src) == want
