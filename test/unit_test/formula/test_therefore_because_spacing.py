"""#906 — ∴·∵ 앞뒤를 두 칸씩 띈다(「수학 점자」 제65항 2·3호).

  2. 그러므로(∴)는 ,*으로 적고, 그 앞뒤를 두 칸씩 띄어 쓴다.
  3. 왜냐하면(∵)은 @/으로 적고, 그 앞뒤를 두 칸씩 띄어 쓴다.

수식 경로가 한 칸씩만 띄었다. 15단계의 다중 공백 접기가 둘레 칸을 뭉갰다.
식 머리·꼬리의 두 칸은 제11항(수식 앞뒤 두 칸)이 본문 쪽에서 이미 내므로 뗀다.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[3]))

from app.ai.braille.kor_math_rules import convert_latex  # noqa: E402
from app.ai.braille.translator import translate_body  # noqa: E402
from app.utils.braille_ascii import ascii_to_unicode  # noqa: E402


def _brf(s: str) -> str:
    """규정 원문 BRF → 유니코드. 규정 원문의 백틱은 빈칸이다(backtick="space")."""
    return ascii_to_unicode(s, backtick="space")


def _body(text: str) -> str:
    return "\n".join(translate_body(text)[0])


def test_규정_예문_2호_그러므로():
    assert convert_latex(r"x+y=xy+2 \therefore xy=x+y-2") == \
        _brf("x5y33xy5#b``,*``xy33x5y9#b")


def test_규정_예문_3호_왜냐하면():
    assert convert_latex(r"y=x+2 \because y=n+2") == _brf("y33x5#b``@/``y33n5#b")


def test_한글_뒤_인라인_왜냐하면은_두_칸이지_네_칸이_아니다():
    """규정 예문 그대로(`y=x+2는 정수 ∵y=n+2`). 제11항 경계 두 칸과 겹치면 네 칸이 된다."""
    assert _body(r"정수 $\because y=n+2$") == _brf(".},m``@/``y33n5#b")


def test_식_머리의_그러므로는_앞에_빈칸이_없다():
    out = convert_latex(r"\therefore x = 1")
    assert out.startswith("⠠⠡⠀⠀")


def test_식_꼬리의_그러므로는_뒤에_빈칸이_없다():
    assert convert_latex(r"x = 1 \therefore").endswith("⠀⠀⠠⠡")


def test_수식_안의_유니코드_그러므로도_두_칸():
    assert convert_latex("a=1 ∴ b=2") == _brf("a33#a``,*``b33#b")


def test_행_병기는_그대로_두_칸():
    """같은 sentinel 을 쓰는 행 구분이 안 바뀌었는지."""
    assert convert_latex(r"\begin{cases} x=1 \\ y=2 \end{cases}") == _brf("7'x33#a``y33#b,7")
