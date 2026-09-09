"""로마자표 없는 영문 문단(제29항 [다만])의 아래칸·낱자 단어 약자 역점역.

BRF 줄은 전부 정답 도서(수능특강 외국어·수학2) 실물이다. 이 표들이 없으면 낱말 하나가
문장 부호로 깎여 빈 껍데기가 되고, `_english_line` 이 그 한 낱말 때문에 **줄 전체를
버려** 영어 지문이 통째로 뜻 없는 한글로 샜다 — 전 코퍼스 1,251쪽 실측으로
`scarf might be pulled …` 이 `어냐카 우다얼 ; 워오사사가 …` 로 나가던 자리다.
"""
from app.utils.braille_ascii import ascii_to_unicode
from app.utils.braille_back import decode


def _dec(brf: str) -> str:
    return decode(ascii_to_unicode(brf, backtick="cell"))


def test_아래칸_단어약자가_홀로_선다():
    """`2`(⠆)=be · `0`(⠴)=was · `8`(⠦)=his — 제37항 [붙임]을 뒤집은 것."""
    assert "might be pulled" in _dec(r"SC>F MI<T 2 PULL$ \ (A DON,N BAG")
    assert "recognition was given" in _dec("HONOR OR RECOGNI;N 0 GIV5 6!M4")
    assert "on his team" in _dec("6SAY T HE WD N H A MAN ON 8 T1M")


def test_낱자_단어기호를_편다():
    """`T`=that · `H`=have · `N`=not · `Z`=as — eng_braille.WORDSIGNS 뒤집기."""
    assert "say that he would not have a man" in _dec(
        "6SAY T HE WD N H A MAN ON 8 T1M")
    assert "twice as many" in _dec("SOLV$ AB TWICE Z _M ANAGRAMS 9")


def test_낱말_첫머리_TO_와_DIS():
    """`6`(⠖)+낱말 = `to`(붙여 적는 단어기호) · `4`(⠲)+낱말 = `dis`(첫머리 음절 약자)."""
    assert "to focus on the things" in _dec("6FOCUS ON ! ?+S Y NE$ 6A3OMPLI%4")
    assert "cancer discovered today" in _dec("! BODY4 ,A C.ER 4COV]$ TD IS !")


def test_답지_머리_괄호는_영어_낱말로_안_샌다():
    """`7,A7 7,B7 7,C7` = `(A) (B) (C)` — 대문자 낱자는 단어기호로 펴지 않는다."""
    out = _dec("  7,A7  7,B7  7,C7")
    assert "But" not in out and "Can" not in out


def test_수식_표_한_줄은_영어로_안_샌다():
    """수학2 p016 실물 — 한 칸짜리 약자만 선 줄은 영어 줄이 못 된다."""
    out = _dec("  X33#A      5  #J  9  #J")
    assert "in" not in out and "enough" not in out
