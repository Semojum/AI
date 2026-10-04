"""계수 뒤 함수 이름은 붙여 쓴다 (#1096).

규정 BRF 는 「한국 점자 규정」 재추출 행 번호(수학 점자).
- 제46항(3812행): `2log7` = `#B_#G`
- 제47항(3865행): `2cosx` = `#b6cx`
LaTeX 의 빈칸은 뜻이 없다. MinerU 가 `2 \\log 7` 처럼 띄워 적어도 점자는 붙인다.
"""
import pytest

from app.ai.braille.kor_math_rules import convert_latex
from app.utils.braille_ascii import ascii_to_unicode


def _brf(s: str) -> str:
    return ascii_to_unicode(s.lower(), backtick="space")


@pytest.mark.parametrize("latex,brf", [
    (r"2 \log 7", "#B_#G"),        # 3812행
    (r"2\log 7", "#B_#G"),
    (r"2 \cos x", "#b6cx"),        # 3865행
    (r"2\cos x", "#b6cx"),
])
def test_계수_뒤_함수_이름은_붙인다(latex, brf):
    assert convert_latex(latex) == _brf(brf)


def test_연산_명령_뒤는_종전대로():
    # `\times` 는 계수가 아니라 연산이다 — 앞 토막이 LaTeX 명령이면 손대지 않는다.
    assert convert_latex(r"2 \times \log 7") == convert_latex(r"2\times\log 7")
