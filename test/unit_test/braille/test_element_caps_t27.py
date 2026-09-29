"""T27 — 화학식은 원소마다 대문자표(과학 점자 제1·2항, 원장 C-129).

종전: `CO₂` → ⠴⠠⠉⠕⠰⠼⠃ = `Co₂`(코발트). 규정 예문 SO₄²⁻ = `,s,o;#d~#b9`(⠠⠎⠠⠕…).
2027 gold 생명과학 `CO₂` = ⠴⠠⠉⠠⠕⠰⠼⠃ (원소마다 56 : 겹 대문자표 1 : 첫 글자만 0).
"""
from app.ai.braille.kor_math_rules import convert_latex, element_formula
from app.ai.braille.translator import translate_body


def _b(text: str) -> str:
    return translate_body(text)[0][0]


def test_이산화탄소는_원소마다():
    assert _b("CO₂가").startswith("⠴⠠⠉⠠⠕⠰⠼⠃")
    assert "⠠⠉⠁⠠⠉⠠⠕⠰⠼⠉" in _b("CaCO₃는")          # Ca · C · O


def test_이온도_원소마다():
    assert _b("NO₃⁻이").startswith("⠠⠝⠠⠕⠰⠼⠉⠘⠔")
    assert _b("NH₄⁺이").startswith("⠠⠝⠠⠓⠰⠼⠙⠘⠢")
    assert convert_latex("SO_{4}^{2-}") == "⠠⠎⠠⠕⠰⠼⠙⠘⠼⠃⠔"   # 규정 제2항 예문


def test_두글자_원소는_그대로():
    assert convert_latex("KMnO_{4}").startswith("⠠⠅⠠⠍⠝⠠⠕")   # K · Mn · O


def test_화학식_아닌_것은_안_건드린다():
    assert not element_formula("AB_{2}")          # A 는 원소가 아니다
    assert not element_formula("x_{2}")
    assert not element_formula("CO")               # 첨자 없는 대문자 낱말(약어일 수 있다)
    assert not element_formula(r"\overline{BC_{1}}")   # 기하
    assert not element_formula("HCO_{3}^{-}")      # 3연은 제4항 구절표가 먼저 받는다
    assert _b("ATP를").startswith("⠴⠠⠠⠁⠞⠏")
