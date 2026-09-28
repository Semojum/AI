"""정방향 영어는 통일영어점자(UEB)다 — EBAE 전용 약자 ation·ally 를 쓰지 않는다(#932).

「한국 점자 규정」 제28항: 로마자는 「통일영어점자 규정」에 따라 적는다. UEB 는 ation(⠠⠝)·
ally(⠠⠽)를 폐지했다. 기대값은 2027 gold 실물이다(생산 코드로 만들지 않았다).
  · val-2027 EBS-E26-014 body p0161 `세계화(globalization)` · `localization`
  · val-2027 EBS-E26-014 body p0162 `(paternalistically)`
역점역은 옛 EBAE 책을 읽어야 하므로 `ebae=True` 로 되짚을 수 있어야 한다.
"""
import pytest

from app.ai.braille import eng_braille


@pytest.mark.parametrize("word,gold", [
    ("globalization", "⠛⠇⠕⠃⠁⠇⠊⠵⠁⠰⠝"),
    ("localization", "⠇⠕⠉⠁⠇⠊⠵⠁⠰⠝"),
    ("paternalistically", "⠏⠁⠞⠻⠝⠁⠇⠊⠌⠊⠉⠁⠇⠇⠽"),
])
def test_정방향은_ation_ally_약자를_안_쓴다(word, gold):
    assert eng_braille.translate(word) == gold


def test_역점역_왕복용_EBAE_는_살아_있다():
    assert eng_braille.translate("donation", ebae=True) == "⠙⠕⠝⠠⠝"
