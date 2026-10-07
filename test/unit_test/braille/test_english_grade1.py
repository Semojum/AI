"""영어 1급 옵션 — 약자 없이 글자대로, 한글 없는 줄도 로마자표 ⠴ … 종료표 ⠲ (이슈 #1189 · 원장 B-27).

「점자 자료 제작 지침」 1.1.2(재추출 240~242행): 영어 점자의 약자는 중학교 2학년용 교재부터 적용한다.
「점자 도서 제작 지침」 제2장 제4절 1.1)(1): 초급자 학습 자료의 영어 문단은 로마자표·종료표를 생략하지 않는다.
기대값은 gold 초등 두 권(ES-TXT-KA0107 영어 5 · ES-REF-T26-007 초등 영단어)에서 옮겼다.
옵션을 끄면(기본) 종전과 같아야 한다 — 마지막 두 시험.
"""
import pytest

from app.ai.braille import eng_braille
from app.ai.braille.constants import ENGLISH_GRADE1
from app.ai.braille.translator import translate_body


def _br(text: str, grade1: bool = True) -> str:
    tok = ENGLISH_GRADE1.set(grade1)
    try:
        return "".join(translate_body(text)[0])
    finally:
        ENGLISH_GRADE1.reset(tok)


@pytest.mark.parametrize("text,cells", [
    ("Read and Write", "⠴⠠⠗⠑⠁⠙⠀⠁⠝⠙⠀⠠⠺⠗⠊⠞⠑⠲"),                       # KA0107 body p0058
    ("Chant and Do.", "⠴⠠⠉⠓⠁⠝⠞⠀⠁⠝⠙⠀⠠⠙⠕⠲"),                        # 마침표가 종료표 자리(제33항 [다만])
    ("How About Your Day?", "⠴⠠⠓⠕⠺⠀⠠⠁⠃⠕⠥⠞⠀⠠⠽⠕⠥⠗⠀⠠⠙⠁⠽⠦"),
    ("Kyle: Where is the toy store?", "⠴⠠⠅⠽⠇⠑⠒⠀⠠⠺⠓⠑⠗⠑⠀⠊⠎⠀⠞⠓⠑⠀⠞⠕⠽⠀⠎⠞⠕⠗⠑⠦"),
    ("Q: Can I <!밑줄>?", "⠴⠠⠟⠒⠀⠠⠉⠁⠝⠀⠠⠊⠀⠨⠤⠦"),                     # 짧은 줄 쌍점도 UEB ⠒
    ("LESSON 9", "⠴⠠⠠⠇⠑⠎⠎⠕⠝⠀⠼⠊"),                                     # 제35항 숫자 앞 종료표 없음
])
def test_한글_없는_줄은_로마자표로_연다(text, cells):
    assert _br(text) == cells


@pytest.mark.parametrize("text,cells", [
    ("This <!밑줄> is <!밑줄>.", "⠴⠠⠞⠓⠊⠎⠀⠨⠤⠀⠊⠎⠀⠨⠤⠲"),                 # KA0107 body p0153 — 빈칸을 넘어 한 구간
    ("bedroom - many books", "⠴⠃⠑⠙⠗⠕⠕⠍⠀⠤⠀⠍⠁⠝⠽⠀⠃⠕⠕⠅⠎⠲"),             # 줄표를 넘어 한 구간
    ("Unit  Title  Page", "⠴⠠⠥⠝⠊⠞⠀⠀⠠⠞⠊⠞⠇⠑⠀⠀⠠⠏⠁⠛⠑⠲"),              # 두 칸 뒤 영어 = 같은 구간
    ("1 ① swim  ② jump high", "⠼⠁⠀⠼⠂⠀⠴⠎⠺⠊⠍⠲⠀⠀⠼⠆⠀⠴⠚⠥⠍⠏⠀⠓⠊⠛⠓⠲"),   # T26-007 ans p0039 — 두 칸 뒤 번호면 끊는다
])
def test_구간은_항목_구분에서만_끊는다(text, cells):
    assert _br(text) == cells


def test_한글_섞인_줄은_제29항_그대로_약자만_없다():
    """KA0107 body p0136 `공룡 캐릭터: Okay. Please go …` 의 앞부분."""
    assert _br("A 그림에") == "⠴⠠⠁⠲⠀⠈⠪⠐⠕⠢⠝"
    assert _br("공룡 캐릭터: Okay.").endswith("⠴⠠⠕⠅⠁⠽⠲")


@pytest.mark.parametrize("word,cells", [
    ("the", "⠞⠓⠑"), ("and", "⠁⠝⠙"), ("reading", "⠗⠑⠁⠙⠊⠝⠛"), ("Kyle", "⠠⠅⠽⠇⠑"), ("PARK", "⠠⠠⠏⠁⠗⠅"),
    ("It's", "⠠⠊⠞⠄⠎"),
])
def test_낱말은_글자대로(word, cells):
    assert eng_braille.translate(word, uncontracted=True) == cells


def test_끄면_종전대로_2급():
    assert _br("Read and Write", grade1=False) == "⠠⠗⠂⠙⠀⠯⠀⠠⠺⠗⠊⠞⠑"
    assert _br("A 그림에", grade1=False) == "⠴⠠⠁⠲⠀⠈⠪⠐⠕⠢⠝"


def test_기본값은_끔():
    assert ENGLISH_GRADE1.get() is False
    assert eng_braille.translate("the") == "⠮"
