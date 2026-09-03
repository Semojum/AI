"""하단 약자(EBAE lower signs) — 낱말 처음·끝에 올 수 없다.

로마자 런 안의 쉼표 ⠂ 가 'ea' 로 읽혀 `Ⅲ, Ⅳ` 가 `IIIEA IV` 로 나갔다.
`in`(⠔)·`en`(⠢)은 낱말 끝에 올 수 있으므로 이 규칙에서 뺀다.
"""
import pytest

from app.ai.braille.translator import translate_plain
from app.utils.braille_back import decode


@pytest.mark.parametrize("text,want", [
    ("구간 Ⅲ, Ⅳ", "구간 III, IV"),        # 쉼표가 'ea' 로 새지 않는다
    ("세포 Ⅰ과 Ⅱ", "세포 I과 Ⅱ"),   # Ⅰ 은 변수 I 와 셀이 같아 ASCII 로 남는다
])
def test_쉼표가_약자로_새지_않는다(text, want):
    assert decode(translate_plain(text)) == want

# `main` 처럼 낱말 끝의 in(⠔)·en(⠢)은 그대로 약자다 — 기존
# test_back_roundtrip.py::test_로마자표_없는_영어줄을_읽는다[the main reason] 가 지킨다.


@pytest.mark.parametrize("text", [
    "점 A, B, C를",
    "세 직선 OP, OR, OQ의",
    "두 수 m, n은 자연수",
    "함수 f, g의",
])
def test_로마자_나열이_쉼표에서_안_끊긴다(text):
    """제32항 구간은 종료표까지다 — 쉼표에서 끊으면 뒤 글자가 한글로 읽힌다."""
    assert decode(translate_plain(text)) == text
