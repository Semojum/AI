"""화학식 대소문자 — 과학 점자 제2항.

규정은 화학식을 원소마다 대문자표(`,h` = ⠠⠓)로 적는데, 수식 디코더가 ⠠ 를 흘려
소문자로 냈다. 한 글자 꼴은 수학 변수가 대부분이라 건드리지 않는다.
"""
import pytest

from app.ai.braille.translator import translate_plain
from app.utils.braille_back import decode


@pytest.mark.parametrize("raw,want", [
    ("⠠⠎⠠⠕⠰⠼⠙⠘⠼⠃⠔", "SO_4^2-"),
    ("⠠⠉⠠⠕⠰⠼⠃", "CO_2"),
    ("⠠⠝⠠⠓⠰⠼⠉", "NH_3"),
])
def test_원소_조합은_대문자(raw, want):
    assert decode(raw) == want


@pytest.mark.parametrize("text", ["t_1 구간", "z_1 값"])
def test_한_글자는_변수라_그대로(text):
    """실측 3,332건 중 묵자가 소문자인 것이 1,707 로 더 많다 — 건드리면 나빠진다."""
    assert "_1" in decode(translate_plain(text)).lower()
    assert "T_1" not in decode(translate_plain(text))
