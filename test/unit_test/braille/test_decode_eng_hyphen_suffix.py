"""역점역: 낱말 머리 ⠤ 는 EBAE com 이 아니라 붙임표다 (이슈 #1178).

UEB 는 com 약자를 폐지했다(#1167, 「한국 점자 규정」 제28항 재추출 1329행 → 통일영어점자).
gold 전권(holdout 제외)에서 낱말 머리 ⠤+글자 153곳을 열어 진짜 com 약자는 0이었다 — 전부 `-ing`·`-s`·`-est`·`-ship`.
"""
from app.utils.braille_back import decode


def test_접미사_앞_붙임표():
    """gold HS-REF-007 ans p0022 `upon -ing:` — 종전 `upon coming:`."""
    assert decode("⠒⠕⠀⠴⠠⠘⠥⠀⠓⠑⠜⠬⠲⠵⠀⠴⠘⠥⠀⠤⠔⠛⠐⠂").endswith("upon -ing:")


def test_한글_줄_속_접미사():
    """gold HS-REF-007 ans p0030 `∘ 접미사 -ship` — 종전 `comship`."""
    assert decode("⠸⠴⠀⠨⠎⠃⠑⠕⠇⠀⠴⠤⠩⠊⠏⠲") == "∘ 접미사 -ship"


def test_풀어쓴_com_은_그대로():
    """UEB 는 company 를 풀어 쓴다(⠉⠕⠍⠏⠁⠝⠽). 그 글자는 붙임표와 상관없다."""
    assert "company" in decode("⠴⠉⠕⠍⠏⠁⠝⠽⠲")
