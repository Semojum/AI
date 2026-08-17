"""규정이 붙여 적으라는 연산자에 원문 공백이 남던 문제 (2026-08-17).

규정 예시에 공백이 없다.
    제2항 붙임 곱셈점   6·9      #f"#i
    제4항 1호 같지않다   y≠0      y.33#j
반대로 제15항 일반연산(⊕⊖⊗∗∘)과 제29~32항 물결 계열은 "앞뒤를 한 칸씩 띄어 쓴다"이므로
건드리면 안 된다. 실측 공백 낀 붙임 대상 540건(cdot 282 · neq 225 · equiv 33).
"""
import pytest

from app.ai.braille.kor_math_rules import convert_latex
from app.ai.braille.translator import translate_tagged_text


@pytest.mark.parametrize("latex,expected", [
    (r"a \cdot b", "⠁⠐⠃"),        # 제2항 붙임
    (r"a \cdot 3", "⠁⠐⠼⠉"),
    (r"a \neq b", "⠁⠨⠒⠒⠃"),       # 제4항 1호
    (r"y \neq 0", "⠽⠨⠒⠒⠼⠚"),
])
def test_붙임_연산자는_공백을_지운다(latex, expected):
    assert convert_latex(latex) == expected


@pytest.mark.parametrize("latex,expected", [
    (r"x \oplus y", "⠭⠀⠸⠢⠀⠽"),    # 제15항 "기호의 앞뒤를 한 칸씩 띄어 쓴다"
    (r"a \circ b", "⠁⠀⠸⠴⠀⠃"),
    (r"a \approx b", "⠁⠀⠈⠔⠈⠔⠀⠃"),  # 제29항 "그 앞뒤를 한 칸씩 띄어 쓴다"
    (r"A \cap B", "⠠⠁⠀⠩⠀⠠⠃"),
])
def test_규정이_띄우라는_칸은_지킨다(latex, expected):
    assert convert_latex(latex) == expected


@pytest.mark.parametrize("text", ["사회·문화", "가·나·다"])
def test_한글_가운뎃점은_안_건드린다(text):
    """실측 14,031건이다 — 곱셈점과 같은 문자라 넓게 잡으면 본문이 깨진다."""
    assert translate_tagged_text(text) == translate_tagged_text(text.replace("·", "·"))
    assert "⠐⠆" in translate_tagged_text(text)
