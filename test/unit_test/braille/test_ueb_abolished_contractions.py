"""UEB 가 폐지한 약자를 정방향이 쓰지 않는다 (이슈 #1167).

「한국 점자 규정」 제7항(재추출 99행)·제28항(1329행)·제32항(1650행)이 로마자를 「통일영어점자 규정」에
맡긴다. UEB 는 EBAE 의 to·into·by(아래칸 단어기호)와 com·dd 를 폐지했다.
gold 영어책 12권 영어 줄(holdout 제외): `to` 풀어씀 ⠞⠕ 6,777 : ⠖ 0 · `by` ⠃⠽ 929 : 0.
역점역은 옛 EBAE 책을 되짚어야 하므로 `ebae=True` 에서는 종전대로 쓴다(ble·ation 과 같은 처리).
"""
import pytest

from app.ai.braille import eng_braille as E


@pytest.mark.parametrize("word,cells", [
    ("to", "⠞⠕"),            # gold HS-REF-T24-136 body p0376 `subject to colds`
    ("by", "⠃⠽"),
    ("into", "⠔⠞⠕"),
    ("company", "⠉⠕⠍⠏⠁⠝⠽"),  # gold HS-REF-T24-136 body p0270
    ("middle", "⠍⠊⠙⠙⠇⠑"),
])
def test_정방향은_폐지_약자를_안_쓴다(word, cells):
    assert E.translate(word) == cells


def test_문장_속_to_by():
    assert E.translate("go to school by bus") == "⠛⠀⠞⠕⠀⠎⠡⠕⠕⠇⠀⠃⠽⠀⠃⠥⠎".replace("⠀", " ")


@pytest.mark.parametrize("word,cells", [
    ("to", "⠖"), ("by", "⠴"), ("into", "⠔⠖"), ("company", "⠤⠏⠁⠝⠽"), ("middle", "⠍⠊⠲⠇⠑"),
])
def test_역점역_EBAE_되짚기는_그대로(word, cells):
    assert E.translate(word, ebae=True) == cells
