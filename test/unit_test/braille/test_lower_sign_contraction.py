"""하단 약자(EBAE lower signs) — 낱말 처음·끝에 올 수 없다.

로마자 런 안의 쉼표 ⠂ 가 'ea' 로 읽혀 `Ⅲ, Ⅳ` 가 `IIIEA IV` 로 나갔다.
`in`(⠔)·`en`(⠢)은 낱말 끝에 올 수 있으므로 이 규칙에서 뺀다.
"""
import pytest

from app.ai.braille.translator import translate_plain
from app.utils.braille_back import decode


@pytest.mark.parametrize("text,want", [
    ("구간 Ⅲ, Ⅳ", "구간 III, IV"),        # 쉼표가 'ea' 로 새지 않는다
    ("세포 Ⅰ과 Ⅱ", "세포 I과 II"),
])
def test_쉼표가_약자로_새지_않는다(text, want):
    assert decode(translate_plain(text)) == want

# `main` 처럼 낱말 끝의 in(⠔)·en(⠢)은 그대로 약자다 — 기존
# test_back_roundtrip.py::test_로마자표_없는_영어줄을_읽는다[the main reason] 가 지킨다.
