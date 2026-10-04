r"""삼각함수 인수 묶음 — 수학 제47항 [붙임](재추출 3857~3872행), 원장 M-08 · #1057.

각이 곱·다항식이면 묶음 괄호로 묶는다. 한 글자 각은 안 묶는다. book 모드(기본)에서도 묶는다 —
2027 gold 가 규정형이다(수학 I 묶음 76 : 안 묶음 8). 기대값 표기는 우리 BRF 표(⠘ = `~`),
규정 원문 BRF 는 ⠘ 를 `^` 로 적는다. 규정 예문의 `sin―6 / x` 는 분모가 ― 줄에 오는 쌓은 분수라
x/6 이다(제7항 3142행 `―4 / 3` = `#d/#c` 와 같은 꼴).
"""
import pytest

from app.ai.braille.kor_math_rules import convert_latex
from app.utils.braille_ascii import unicode_to_ascii


def _brf(t: str) -> str:
    return unicode_to_ascii(convert_latex(t)).replace("`", "").strip()


@pytest.mark.parametrize("src,want", [
    (r"\sin 3x", "6s(#cx)"),
    (r"\sin xy", "6s(xy)"),
    (r"\sin\frac{x}{6}", "6s(#f/x)"),
    (r"2\cos x", "#b6cx"),                       # 한 글자 각은 안 묶는다
    (r"\sin^{2}x+\cos^{2}x=1", "6s~#bx56c~#bx33#a"),
    (r"\sin^{3}x", "6s~#cx"),
    (r"\sin x^{3}", "6sx~#c"),
])
def test_규정_예문(src, want):
    assert _brf(src) == want


@pytest.mark.parametrize("src,want", [
    (r"\sin\frac{3}{4}\pi", "6s(#d/#c.p)"),      # 분수 뒤 π 까지 한 각 — 2027 gold
    (r"\sin\pi x", "6s(.px)"),                    # 그리스로 시작하는 곱 — gold ans p18
    (r"\cos(\alpha+\beta)", "6c8.a5.b0"),         # 묵자 괄호는 그대로 소괄호
])
def test_2027_gold_범위(src, want):
    assert _brf(src) == want
