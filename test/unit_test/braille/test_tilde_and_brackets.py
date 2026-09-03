"""물결표·겹낫표 역점역.

물결표는 재추출 묵자 전수에서 `~` 832회 · `∼` 1회다 — ASCII 쪽으로 편다.
겹낫표 닫는 `』`(⠴⠆)는 받침 ㅎ 가드가 ⠴ 를 닫는 큰따옴표로 굳혀 사라졌다.
"""
import pytest

from app.ai.braille.translator import translate_plain
from app.utils.braille_back import decode


@pytest.mark.parametrize("text", [
    "『천연론』 출간",
    "『삼국사기』를",
    "~1895",
    "400~600",
    "고1~2",
])
def test_왕복(text):
    assert decode(translate_plain(text)) == text


@pytest.mark.parametrize("text", ["[목]", "좋다", "옳지", "그의 말이 좋다"])
def test_받침_ㅎ와_대괄호는_그대로(text):
    """⠴ 를 한 칸 물러 읽게 했으니 받침 ㅎ·대괄호가 안 깨지는지 지킨다."""
    assert decode(translate_plain(text)) == text
