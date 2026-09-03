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


@pytest.mark.parametrize("text", [
    "『황명세법』을",
    "『대학』을 읽고",
])
def test_낫표_뒤_조사가_영어약자로_안_샌다(text):
    """제29항 — 로마자표는 낱말 앞에 온다. 낱말 중간 ⠴ 는 닫는 낫표다.

    이 조건이 없으면 `⠴⠆⠮` 가 be+the 로 3셀을 먹어 `『황명세법bethe` 가 나갔다.
    """
    assert decode(translate_plain(text)) == text


@pytest.mark.parametrize("text", ["pH 농도", "50%이다", "25%이므로", "MP4 Player 를", "℃ 단위"])
def test_어절_첫_로마자표는_그대로(text):
    assert decode(translate_plain(text)) == text


@pytest.mark.parametrize("text", ["국가」라는", "「보기」의 국가」"])
def test_닫는_홑낫표(text):
    """`」`(⠴⠂) 는 받침 ㅎ 음절이 목록에 있어도 낫표다.

    실측(전 코퍼스 1,131쪽): 점자 ⠴⠂ 187건 · 묵자 `」` 189건으로 사실상 1:1.
    """
    assert "」" in decode(translate_plain(text))


@pytest.mark.parametrize("text", ["좋다", "그것이 좋, 나쁨", "옳지", "놓고"])
def test_받침_ㅎ은_그대로(text):
    assert decode(translate_plain(text)) == text
