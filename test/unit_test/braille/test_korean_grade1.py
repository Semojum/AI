"""한글 1급(정자 점자) 옵션 — 약자·약어 없이 자모대로 (이슈 #1191).

「점자 자료 제작 지침」 1.1.2(재추출 240~242행): 한글 점자의 약자는 초등학교 2학년용 교재부터 적용한다.
끄는 범위는 「한국 점자 규정」 제2장 약자와 약어(제13~18항). gold 에 정자로 적힌 책이 없어 기대값은 규정 원문에서
자모 표(제1·2·3·6·7항)를 조합해 적었다. 행 번호는 `한국 점자 규정_재추출.txt`.
옵션을 끄면(기본) 종전과 같아야 한다 — 마지막 두 시험.
"""
import pytest

from app.ai.braille.constants import KOREAN_GRADE1
from app.ai.braille.translator import translate_body


def _br(text: str, grade1: bool = True) -> str:
    tok = KOREAN_GRADE1.set(grade1)
    try:
        return "".join(translate_body(text)[0])
    finally:
        KOREAN_GRADE1.reset(tok)


@pytest.mark.parametrize("text,cells", [
    ("가", "⠈⠣"),                # 제13항 약자 ⠫ 대신 ㄱ(제1항 ⠈) + ㅏ(제6항 ⠣)
    ("나다", "⠉⠣⠊⠣"),
    ("까", "⠠⠈⠣"),              # 제16항 약자 대신 된소리표(제2항 ⠠) + ㄱ + ㅏ
    ("것", "⠈⠎⠄"),              # 제15항 약자 ⠸⠎ 대신 ㄱ + ㅓ + 받침 ㅅ(제3항 ⠄)
    ("성", "⠠⠎⠶"),              # 제17항 ㅅ+영 약자 ⠠⠻ 대신 ㅅ + ㅓ + 받침 ㅇ
    ("은", "⠪⠒"),               # 제15항 약자 ⠵ 대신 ㅡ + 받침 ㄴ
    ("그래서", "⠈⠪⠐⠗⠠⠎"),       # 제18항 약어 ⠁⠎ 를 안 쓴다
    ("있었다", "⠕⠌⠎⠌⠊⠣"),      # 받침 ㅆ ⠌ 는 제1장 제4항(303행) 자모 규정 — 그대로
])
def test_약자_약어_없이_자모대로(text, cells):
    assert _br(text) == cells


@pytest.mark.parametrize("text,cells", [
    ("아예", "⠣⠤⠌"),              # 제11항 예문(538~541행) `<-/`
    ("서예", "⠠⠎⠤⠌"),             # 제11항 예문 `,s-/`
    ("소화액", "⠠⠥⠚⠧⠤⠗⠁"),        # 제12항 예문(552~557행) `,ujv-ra`
])
def test_모음_연쇄_구분표(text, cells):
    assert _br(text) == cells


def test_숫자_뒤_헷갈리는_첫소리는_띄운다():
    """제44항 [다만](2005~2006행) — 예문 `1년` = #a`c* 의 띄움은 그대로, 연 약자 ⠡ 만 풀린다."""
    assert _br("1년") == "⠼⠁⠀⠉⠱⠒"
    assert _br("3개") == "⠼⠉⠈⠗"            # ㄱ 은 대상 아님(제44항 본문 `5 개`·`2권` 꼴)


@pytest.mark.parametrize("text,cells", [
    ("2도", "⠼⠃⠀⠊⠥"),            # 제44항 [다만] 예문(2009행) `#b`iu` — ㄷ 띄움
    ("3명", "⠼⠉⠀⠑⠱⠶"),          # 예문 `#c`e]` 의 영 약자 ⠻ 만 풀린다(ㅁ ⠑ + ㅕ ⠱ + 받침 ㅇ ⠶)
    ("5월", "⠼⠑⠏⠂"),            # 제44항 본문 예문 `#ep1` — ㅇ 첫소리는 붙인다(ㅝ ⠏ + 받침 ㄹ ⠂)
])
def test_숫자_뒤_경계(text, cells):
    assert _br(text) == cells


def test_영어_구간_경계():
    """제29항 로마자표 ⠴ … 종료표 ⠲ 뒤 조사. 2급이면 `는` = ⠉⠵(은 약자)."""
    assert _br("Korea는") == "⠴⠠⠅⠕⠗⠑⠁⠲⠉⠪⠒"


@pytest.mark.parametrize("text,cells", [
    ("가, 나.", "⠈⠣⠐⠀⠉⠣⠲"),                  # 쉼표 ⠐ · 마침표 ⠲ (제49항)
    ("(가)", "⠦⠄⠈⠣⠠⠴"),                       # 소괄호 ⠦⠄ … ⠠⠴
    ("「점자」", "⠐⠦⠨⠎⠢⠨⠣⠴⠂"),               # 낫표
    ("가?", "⠈⠣⠦"),
])
def test_문장_부호_앞뒤(text, cells):
    assert _br(text) == cells


def test_따옴표_짝과_문장_부호는_그대로():
    assert _br('"사과"라고') == "⠦⠠⠣⠈⠧⠴⠐⠣⠈⠥"
    assert _br("가.") == "⠈⠣⠲"


def test_끄면_종전대로_2급():
    assert _br("가나다", grade1=False) == "⠫⠉⠊"
    assert _br("그래서", grade1=False) == "⠁⠎"


def test_기본값은_끔():
    assert KOREAN_GRADE1.get() is False
