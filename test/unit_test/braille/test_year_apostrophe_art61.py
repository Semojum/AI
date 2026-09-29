"""「한글 점자」 제61항 — 연도 생략 아포스트로피 ’ = ⠄, 수표는 그 앞에 한 번만 (#939).

기대값은 규정 원문(재추출 2547~2552행) BRF 그대로다(생산 코드로 만들지 않았다).
"""
import pytest

from app.ai.braille.translator import translate_body
from app.utils.braille_ascii import ascii_to_unicode


def _body(text: str) -> str:
    return "".join(translate_body(text)[0])


@pytest.mark.parametrize("src,brf", [
    ("’22. 9. 7.", "#'bb4`#i4`#g4"),
    ("’88 서울 올림픽", "#'hh`,s&`u1\"o5doa"),
])
def test_제61항_규정_예문(src, brf):
    assert _body(src) == ascii_to_unicode(brf, backtick="space")


def test_연도_뒤_첫소리_ㄴ은_제44항대로_띄운다():
    assert _body("’88년") == "⠼⠄⠓⠓⠀⠉⠡"


@pytest.mark.parametrize("src,keep", [
    ("‘제목’ 88", "⠴⠄"),          # 짝 맞는 닫는 따옴표
    ("it’s 88", "⠭⠄⠎"),           # 로마자 아포스트로피(종전 규칙)
])
def test_연도가_아닌_자리는_그대로(src, keep):
    assert keep in _body(src)
