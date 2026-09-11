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
    # [C] 인자 **사이**의 칸 `} {` (#871). 여기가 안 닫혀 \frac 이 통째로 사라졌다.
    (r"\frac { 1 } { 2 }", r"\frac{1}{2}"),
    (r"\frac { \pi } { 6 }", r"\frac{\pi}{6}"),
    (r"\frac { x + 1 } { x - 2 }", r"\frac{x+1}{x-2}"),
    (r"\frac { 1 } { 1 6 }", r"\frac{1}{16}"),
])
def test_토큰_공백이_있어도_같게_점역된다(spaced, tight):
    assert convert_latex(spaced) == convert_latex(tight)


@pytest.mark.parametrize("latex", [r"\frac { 3 } { 4 }", r"\frac {3}{4}", r"\frac{3}{4}"])
def test_띄어_쓴_분수도_분수표로_나간다(latex):
    """「수학 점자」 제7항 1호(규정 재추출 3141~3145행) — 분모·분수표·분자 순, 분수표는 `/`.

    규정 예문 3/4 = `#d/#c`. MinerU 꼴 `\frac { 3 } { 4 }` 는 #871 전에는 분수표가
    아예 없이 `⠼⠉⠀⠼⠙`("3 4") 로 나가 **다른 수**로 읽혔다.
    """
    assert convert_latex(latex) == "⠼⠙⠌⠼⠉"


@pytest.mark.parametrize("latex,expected", [
    (r"\sin x", "⠖⠎⠭"),          # 붙이면 \sinx가 되어 통째로 사라진다
    (r"x \oplus y", "⠭⠀⠸⠢⠀⠽"),   # 제15항 "앞뒤를 한 칸씩 띄어 쓴다"
    (r"A \cap B", "⠠⠁⠀⠩⠀⠠⠃"),
    (r"X \to Y", "⠠⠭⠀⠒⠕⠀⠠⠽"),    # 제10항 붙임
    # 집합 표기 `\{ … \}` 는 중괄호가 아니라 **문자**다 — `} {` 규칙에 걸리면 안 된다.
    (r"\{ 1 \} \{ 2 \}", "⠶⠼⠁⠶⠀⠶⠼⠃⠶"),
])
def test_명령과_규정상_한_칸은_안_건드린다(latex, expected):
    """공백을 넓게 지우면 명령이 사라지거나 규정이 요구하는 칸이 없어진다."""
    assert convert_latex(latex) == expected
