"""단축형 before = bef(⠆⠋) (이슈 #1184).

「한국 점자 규정」 제28항(재추출 1329행) → 통일영어점자 단축형 목록. 종전 표는 ⠆⠿(be+for 를 이어 붙인 꼴)였다.
gold 영어책(holdout 제외) 홀로 선 ⠆⠋ 343 : ⠆⠿ 0.
"""
from app.ai.braille import eng_braille as E
from app.utils.braille_back import decode


def test_정방향_before():
    assert E.translate("before") == "⠆⠋"
    assert E.translate("beforehand") == "⠆⠋⠓⠯"     # gold EBS-E26-008 ans p0100


def test_역점역_before():
    """gold EBS-E26-008 ans p0004 `vote on the next book one week before` — 종전 `… week bef`."""
    assert decode("⠧⠕⠞⠑⠀⠕⠝⠀⠮⠀⠝⠑⠭⠞⠀⠃⠕⠕⠅⠀⠐⠕⠀⠺⠑⠑⠅⠀⠆⠋").endswith("week before")
