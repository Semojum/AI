"""말머리·글머리 뒤 영어 몸통 역점역 — 줄 머리 토막을 한글로, 몸통을 영어 줄 판정으로 읽는다.

기대값은 gold 줄 그대로다. 몸통의 영어 약자 해독(`Th` = this 등)은 이 시험의 대상이 아니라
머리가 한글 경로로 남고 몸통이 영어로 읽히는지만 단언한다.
"""
import pytest

from app.utils.braille_back import decode


@pytest.mark.parametrize("br, head, body", [
    # EBS-E26-006 ans p0002 — 글머리 •
    ("⠀⠀⠸⠲⠀⠠⠹⠀⠏⠗⠕⠧⠊⠙⠑⠎⠀⠌⠥⠙⠢⠞⠎⠀⠾⠀⠁⠝", "  • ", "provides students with an"),
    # EBS-E26-006 body p0159 — 번호
    ("⠀⠀⠼⠁⠲⠀⠠⠋⠗⠩⠊⠏⠎⠀⠁⠉⠗⠀⠉⠥⠇⠞⠥⠗⠑⠎⠀⠓⠑⠇⠏", "  1. ", "across cultures help"),
    # ES-REF-T26-007 body p0075 — 쌍점으로 끝나는 한글 말머리
    ("⠀⠀⠑⠂⠙⠍⠶⠠⠾⠐⠂⠀⠴⠠⠺⠓⠁⠞⠀⠊⠎⠀⠞⠓⠊⠎⠦", "  말풍선: ", "What is this?"),
    # HS-REF-T24-136 body p0040 — 글머리 □
    ("⠀⠀⠸⠶⠀⠠⠞⠑⠇⠇⠀⠍⠑⠀⠱⠑⠮⠗⠀⠓⠑⠀⠊⠎⠀⠁⠞⠀⠓⠕⠍⠑", "  □ ", "Tell me whether he is at home"),
])
def test_머리_뒤_영어(br, head, body):
    got = decode(br)
    assert got.startswith(head) and got.endswith(body), got


def test_로마자_구간을_닫고_한글이_이어지면_자르지_않는다():
    # EBS-E26-006 body p0044 단어장 — `⠴retail⠲` 뒤 뜻풀이는 한글이다
    assert decode("⠀⠀⠸⠶⠀⠴⠗⠑⠞⠁⠊⠇⠲⠀⠠⠥⠑⠗") == "  □ retail 소매"


def test_한글_낱말_머리는_자르지_않는다():
    # 비영어 책에서 몸통이 기능어 둘을 우연히 채우는 한국어 줄 — 머리 목록에 한글 낱말은 없다
    from app.utils import braille_back as B
    assert not B._head_ok("⠘⠒⠠⠕⠁")        # 한글 낱말(`반식`)
    assert not B._head_ok("⠠⠄⠈⠪⠐⠕⠢⠐⠂")   # 점역자주 표를 품은 말머리
