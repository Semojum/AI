"""UEB — be 약자 ⠆ 는 첫 음절을 이룰 때만 쓴다 (이슈 #1180).

「한국 점자 규정」 제28항(재추출 1329행)이 로마자를 통일영어점자에 맡긴다. 통일영어점자는 be·con·dis 를 첫 음절일
때만 쓴다(dis 는 #950 `dish`). gold 영어책(holdout 제외): because 263 · being 114 · become 81 은 ⠆,
been 246 · better 184 · best 122 · beard 79 는 풀어 쓴다.
"""
import pytest

from app.ai.braille import eng_braille as E


@pytest.mark.parametrize("word,cells", [
    ("been", "⠃⠑⠢"),            # gold MS-REF-T25-078 body p0107 `has been to`
    ("beard", "⠃⠑⠜⠙"),          # gold MS-REF-T25-078 body p0011
    ("better", "⠃⠑⠞⠞⠻"),
    ("beards", "⠃⠑⠜⠙⠎"),        # gold MS-REF-T25-078 body p0035
])
def test_첫_음절이_아니면_풀어_쓴다(word, cells):
    assert E.translate(word) == cells


@pytest.mark.parametrize("word,cells", [
    ("became", "⠆⠉⠁⠍⠑"),        # gold MS-REF-T25-078 body p0027 `became`
    ("believe", "⠆⠇⠊⠑⠧⠑"),
    ("being", "⠆⠬"),
    ("began", "⠆⠛⠁⠝"),
])
def test_첫_음절이면_약자(word, cells):
    assert E.translate(word) == cells


def test_역점역_EBAE_되짚기는_그대로():
    assert E.translate("been", ebae=True) == "⠆⠢"
