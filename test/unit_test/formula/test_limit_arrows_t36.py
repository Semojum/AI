"""eval 규정 전수 과제 A — 수학 제51항 극한 · 제10항 대각 화살표. 기대값은 「한국 점자 규정」 재추출 원문.

코퍼스(2027 dev·val)에 lim·↖·↙ 가 0곳이라 A/B 로는 안 잡힌다. 규정 예문으로만 지킨다.
"""
from app.ai.braille.kor_math_rules import convert_latex


def test_극한은_화살표를_적는다():
    # 제51항(3902~3910행) `LIM;X`3o`B`G8X0` · `LIM;X`3o`=`F8X0` — 원장 M-07 규정 채택(09-30)
    assert convert_latex(r"\lim_{x\to b} g(x)") == "⠇⠊⠍⠰⠭⠀⠒⠕⠀⠃⠀⠛⠦⠭⠴"
    assert convert_latex(r"\lim_{x\to\infty} f(x)") == "⠇⠊⠍⠰⠭⠀⠒⠕⠀⠿⠀⠋⠦⠭⠴"


def test_범위가_둘이면_변수마다_아래첨자표():
    # 제51항 [붙임](3931~3935행) `LIM;X 3o`A`;Y`3o`B`F8X"`Y0` — 종전에는 `_` 가 점자에 샜다
    out = convert_latex(r"\lim_{\substack{x\to a\\y\to b}} f(x,y)")
    assert out.startswith("⠇⠊⠍⠰⠭⠀⠒⠕⠀⠁⠀⠰⠽⠀⠒⠕⠀⠃⠀⠋")
    assert "_" not in out


def test_왼쪽_대각_화살표가_사라지지_않는다():
    # 제10항(3200·3202행) ↖ `[5` · ↙ `[9`
    assert "⠪⠢" in convert_latex(r"a \nwarrow b")
    assert "⠪⠔" in convert_latex(r"a \swarrow b")
