"""eval 규정 전수 과제 A 12 — 점역자 삽입 묶음 괄호 누락 셋. 기대값은 「한국 점자 규정」 재추출 원문."""
from app.ai.braille.kor_math_rules import convert_latex


def test_근수가_곱이면_묶는다():
    assert convert_latex(r"\sqrt[mn]{y}") == "⠷⠍⠝⠾⠻⠽"          # 제22항 [붙임 2] 3620행 ` (mn)]y`
    assert convert_latex(r"\sqrt[3]{x}") == "⠼⠉⠻⠭"               # 홑 근수는 그대로


def test_켤레_복소수_가로바_아래_다항식은_묶는다():
    assert convert_latex(r"\overline{a+bi}") == "⠷⠁⠢⠃⠊⠾⠈⠉"    # 제23항 1호 가 3629행 `(a5bi)@c`
    assert convert_latex(r"\overline{x}") == "⠭⠈⠉"


def test_범위_없는_시그마_뒤_분수는_묶는다():
    assert convert_latex(r"\sum\frac{1}{n}") == "⠠⠨⠎⠷⠝⠌⠼⠁⠾"   # 제25항 3659행 `,.S(N/#A)`
