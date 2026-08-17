"""MinerU 토큰 공백이 뒤 판정을 빗나가게 하던 문제 (2026-08-17).

MinerU는 LaTeX를 토큰마다 띄어 내보낸다. 그 공백은 조판이 아니라 토큰 구분인데,
남으면 뒤 판정이 통째로 빗나간다.

    \\frac {3}{2} a ^ {2}     숫자 뒤 로마자 구분점(제12항)이 안 들어간다
    \\frac {2 a b}{c ^ {2}}   곱 묶음 판정(제7항 3호)이 '영숫자 덩어리'로 안 본다

실측 닫는 중괄호 뒤 1,803건 · 영숫자만 든 중괄호 안 953건. eval 정렬 진단 [A]·[B-2].
"""
import pytest

from app.ai.braille.kor_math_rules import convert_latex


@pytest.mark.parametrize("spaced,tight", [
    (r"\frac {3}{2} a ^ {2}", r"\frac{3}{2}a^{2}"),      # [A] 구분점
    (r"\frac {2 a b}{c ^ {2}}", r"\frac{2ab}{c^{2}}"),   # [B-2] 곱 묶음
])
def test_토큰_공백이_있어도_같게_점역된다(spaced, tight):
    assert convert_latex(spaced) == convert_latex(tight)


@pytest.mark.parametrize("latex,expected", [
    (r"\sin x", "⠖⠎⠭"),          # 붙이면 \sinx가 되어 통째로 사라진다
    (r"x \oplus y", "⠭⠀⠸⠢⠀⠽"),   # 제15항 "앞뒤를 한 칸씩 띄어 쓴다"
    (r"A \cap B", "⠠⠁⠀⠩⠀⠠⠃"),
    (r"X \to Y", "⠠⠭⠀⠒⠕⠀⠠⠽"),    # 제10항 붙임
])
def test_명령과_규정상_한_칸은_안_건드린다(latex, expected):
    """공백을 넓게 지우면 명령이 사라지거나 규정이 요구하는 칸이 없어진다."""
    assert convert_latex(latex) == expected
