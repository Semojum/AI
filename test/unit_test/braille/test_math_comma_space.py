"""수식 쉼표 뒤는 늘 한 칸 (#1115, 원장 M-09).

규정 BRF 는 「한국 점자 규정」 재추출 행 번호(수학 점자). 백틱은 규정 원문 관례대로 칸 띄우기다.
- 제60항 2호 가(4092행): `{1,2,3}` = `7#A"`#B"`#C7`
- 3935행: `f(x,y)` = `F8X"`Y0`
원문 쉼표 뒤가 붙어 있어도 점자는 한 칸을 띈다. 자릿점(`1,000`)은 다른 갈래라 그대로다.
"""
import pytest

from app.ai.braille.kor_math_rules import convert_latex
from app.utils.braille_ascii import ascii_to_unicode


def _brf(s: str) -> str:
    return ascii_to_unicode(s.lower(), backtick="space")


@pytest.mark.parametrize("latex,brf", [
    (r"\{1,2,3\}", '7#A"`#B"`#C7'),      # 4092행
    (r"\{1, 2, 3\}", '7#A"`#B"`#C7'),
    (r"f(x,y)", 'F8X"`Y0'),             # 3935행
])
def test_쉼표_뒤_한_칸(latex, brf):
    assert convert_latex(latex) == _brf(brf)


def test_자릿점은_그대로():
    assert convert_latex("1,000") == "⠼⠁⠂⠚⠚⠚"
