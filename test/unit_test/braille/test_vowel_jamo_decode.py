"""모음 낱자 역점역 — 규정 제7항.

온표 ⠿ 는 약자 '옹'이기도 하다. 자음 낱자(㉠=⠿⠁)는 뒤 셀이 음절 첫소리와 안 겹쳐
무조건 펴도 되지만, 모음은 겹친다. 그래서 양옆이 경계일 때만 편다.
"""
import pytest

from app.ai.braille.translator import translate_plain
from app.utils.braille_back import decode


@pytest.mark.parametrize("text", [
    "ㅏ ㅓ ㅗ ㅜ ㅡ ㅣ",
    "ㅑ ㅕ ㅛ ㅠ ㅒ ㅖ ㅘ ㅙ ㅝ ㅞ ㅢ",
    "‘ㅐ, ㅔ’",
    "모음 ㅑ ㅕ ㅛ",
    "자음 ㄱ, ㄴ, ㄷ",
])
def test_낱자_왕복(text):
    assert decode(translate_plain(text)) == text


@pytest.mark.parametrize("text", ["옹알이", "나무 옹이가"])
def test_약자_옹은_안_건드린다(text):
    assert decode(translate_plain(text)) == text
