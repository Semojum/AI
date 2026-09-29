"""1종 지시자 ⠰ — 한국어 문장 속 로마자 구간에서 약자로 읽힐 낱자·낱자열 앞(원장 C-99).

「한글 점자」 제32항(규정_텍스트 1649행)이 로마자표와 종료표 사이를 통일영어점자에 맡기고,
통일영어점자는 홀로 선 낱자·낱자열이 약자와 같은 셀이면 앞에 ⠰ 를 적는다(V = very · CD = could).
규정 예문과 2027 gold 가 같은 세 갈래다:
  ① 로마자표 바로 뒤 첫 홑 낱자에는 안 적는다      (제36항 표 V · `v-x` 의 v)      gold 0/4,896
  ② 구간 안에서 이어지는 약자꼴 홑 낱자에는 적는다  (`a, b, c` 의 b·c · George V)  gold 347/347
  ③ 두 글자 이상 약자꼴은 로마자표 바로 뒤라도 적는다(`CD 1장`)                   gold 100/102
⚠ 구판 gold 는 셋 다 안 적는다(판본 역전). 기대값은 규정 원문 BRF 를 옮겼다(backtick="space").
"""
from __future__ import annotations

import pytest

from app.ai.braille import eng_braille
from app.ai.braille.translator import translate_body
from app.utils.braille_ascii import ascii_to_unicode


def _cells(s: str) -> str:
    return "".join(c for c in s if 0x2800 <= ord(c) <= 0x28FF and c != "⠀")


def _body(text: str) -> str:
    return _cells("".join(translate_body(text)[0]))


@pytest.mark.parametrize("src,brf", [
    ("세 점 A, B, C가 있다.", ",n`.s5`0,a1`;,b1`;,c4$`o/i4"),                       # 수학 제12항 3호
    ("다음 a, b, c의 값으로 옳은 것을 고르시오.",
     "i<{5`0a1`;b1`;c4w`$b'{\"u`u10z`_s!`@u\"{,ou4"),                              # 제32항 1651행
    ("CD 1장을 구하려 합니다.", "0;,,cd`#a.7!`@mj\":`jbcoi4"),                        # 제35항 1743행
    ("1차 세계 대전 당시 영국의 왕은 George V였다.",
     "#a;<`,n@/`ir.)`i7,o`}@maw`v7z`0,george`;,v4:/i4"),                             # 제36항 1789행
])
def test_규정_예문(src: str, brf: str) -> None:
    assert _body(src) == _cells(ascii_to_unicode(brf, backtick="space"))


@pytest.mark.parametrize("src", ["점 P에서", "x좌표와 y좌표", "V였다", "A와 B는 다르다"])
def test_로마자표_바로_뒤_첫_홑_낱자는_안_적는다(src: str) -> None:
    assert "⠴⠰" not in _body(src)


def test_약자가_아닌_a_i_o_와_약자꼴_아닌_낱자열은_안_적는다() -> None:
    out = _body("모음 A, I, O와 DNA, ATP가 있다.")
    assert "⠰" not in out
    assert "⠴⠠⠁⠂⠠⠊⠂⠠⠕" in out


def test_순수_로마자_줄과_옛_책_되짚기는_그대로다() -> None:
    # 한글 없는 줄(제29항 [다만])은 실측 전이라 켜지 않는다 · ebae 는 역점역 왕복용.
    assert eng_braille.translate("A, B, C") == eng_braille.translate("A, B, C", grade1="")
    assert "⠰" not in eng_braille.translate("George V", ebae=True, grade1="cont")


def test_낱말_안쪽_대문자는_약자꼴이_아니다() -> None:
    # 2027 gold 001 p0115 유전자형 `AB, Ab, aB, ab` = ⠰⠠⠠⠁⠃ ⠰⠠⠁⠃ ⠁⠠⠃ ⠰⠁⠃
    assert eng_braille._looks_contracted("AB") and eng_braille._looks_contracted("Ab")
    assert eng_braille._looks_contracted("ab") and not eng_braille._looks_contracted("aB")
