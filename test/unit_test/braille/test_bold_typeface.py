"""굵은 글자체표 — 규정 제56항.

제56항은 강조를 두 갈래로 적는다.
· 드러냄표·밑줄 → `,-` … `-'` (⠠⠤ … ⠤⠄)
· 굵은 글자     → `;-` … `-2` (⠰⠤ … ⠤⠆)

역맵에 굵은 쪽이 없어 뜻 없는 ASCII 가 새어 나갔다(`_-어제도-;`).
"""
import pytest

from app.ai.braille.translator import translate_plain
from app.utils.braille_back import decode


def test_굵은_글자체표를_벗긴다():
    raw = "⠀⠀⠰⠤⠎⠨⠝⠊⠥⠤⠆⠀⠚⠐⠍⠄⠘⠢"
    assert decode(raw) == "  어제도 하룻밤"


@pytest.mark.parametrize("text", ["고복지-저부담", "(가)와 (나)", "근대화(1)"])
def test_붙임표_괄호_비회귀(text):
    """⠤ 는 붙임표와 같은 셀이다 — 짝일 때만 벗기므로 안 깨진다."""
    assert decode(translate_plain(text)) == text
