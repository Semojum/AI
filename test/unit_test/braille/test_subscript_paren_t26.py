"""T26 — 첨자가 든 괄호 `(F₁)`·`(CO₂)` 는 제49항 소괄호(판본 역전).

종전에는 구판 생물 gold 관행(붙임표 25 : 0)대로 ⠤…⠤ 로 감쌌다. 2027 gold(dev·val)는
소괄호 94 : 붙임표 0 이다. 생명과학 E26-001 ans p0007 gold `(d₁)` = ⠦⠄⠙⠰⠼⠁⠠⠴.
"""
from app.ai.braille.translator import translate_body


def _b(text: str) -> str:
    return translate_body(text)[0][0]


def test_첨자_괄호는_소괄호():
    out = _b("잡종 1대(F₁)에서")
    assert "⠦⠄⠴⠠⠋⠰⠼⠁⠠⠴" in out and "⠤" not in out
    assert "⠦⠄⠴⠠⠉⠠⠕⠰⠼⠃⠠⠴" in _b("이산화 탄소(CO₂)가")   # C·O 원소마다(#977) = gold


def test_원문_붙임표는_그대로():
    assert "⠤⠴⠠⠕⠰⠼⠃⠤" in _b("산소-O₂-와")
