"""통일영어점자 대문자 구절표 · ble 폐지 (#946). 기대값은 「한국 점자 규정」 원문 BRF 그대로다."""
import pytest

from app.ai.braille import eng_braille
from app.ai.braille.translator import translate_body
from app.utils.braille_ascii import ascii_to_unicode


def _body(text: str) -> str:
    return "".join(translate_body(text)[0])


@pytest.mark.parametrize("src,brf", [
    ("WELCOME TO KOREA", ",,,welcome`to`korea,'"),        # 제28항 — 대문자 구절표 ⠠⠠⠠ … ⠠⠄
])
def test_규정_예문(src, brf):
    assert _body(src) == ascii_to_unicode(brf, backtick="space")


def test_ble_약자를_안_쓴다():
    # 제29항 예문 `Table of Contents` = 0,table`(`,3t5ts4 — table 이 t·a·b·l·e 로 풀려 있다
    assert _body("Table of Contents").startswith("⠠⠞⠁⠃⠇⠑")


@pytest.mark.parametrize("src", ["DNA, RNA, ATP", "KTX SRT", "A B C D E"])
def test_구절이_아닌_대문자_낱말은_종전대로(src):
    assert "⠠⠠⠠" not in eng_braille.translate(src)


def test_EBAE_되짚기는_낱말마다_대문자_단어표():
    assert eng_braille.translate("WELCOME TO KOREA", ebae=True).count("⠠⠠") == 3
