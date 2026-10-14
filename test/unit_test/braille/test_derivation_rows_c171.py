"""유도 사슬(등호로 시작하는 배열 행)은 앞 행에 붙여 잇는다(원장 C-171).

규정은 배열 행을 한 줄에 이어 적을 때의 폭을 정하지 않는다(수학 제6항은 연립식 괄호와 행 정렬만 예시). 관행을 따른다.
gold 수학 Ⅰ(dev 009) 행 머리 등호 251행이 전부 등호 앞뒤 0칸이다. 그래서 유도 사슬은 같은 식을 한 줄로 적은 것과 같아야 한다.
연립식(⠶⠄…⠠⠶)의 행 병기 두 칸과 등호로 시작하지 않는 행은 그대로다.
"""
from __future__ import annotations

import app.ai.braille.translator  # noqa: F401  (convert_latex 마지막 그물이 import 로 켜진다)
from app.ai.braille.kor_math_rules import convert_latex


def test_유도_사슬은_한_줄_식과_같다():
    chain = r"\begin{array}{l} y = (x+1)^{2} \\ = x^{2} + 2x + 1 \end{array}"
    assert convert_latex(chain) == convert_latex(r"y = (x+1)^{2} = x^{2} + 2x + 1")


def test_정렬_꼴_유도_사슬도_한_줄_식과_같다():
    assert convert_latex(r"\begin{aligned} a &= b + c \\ &= d \end{aligned}") == convert_latex("a = b + c = d")


def test_연립식_행_사이는_두_칸_그대로():
    assert "⠀⠀" in convert_latex(r"\left\{ \begin{array}{l} x + y = 3 \\ x - y = 1 \end{array} \right.")


def test_등호로_시작하지_않는_행은_두_칸_그대로():
    assert "⠀⠀" in convert_latex(r"\begin{array}{l} x + y = 3 \\ x - y = 1 \end{array}")
