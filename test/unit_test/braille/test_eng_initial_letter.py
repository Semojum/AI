"""영어 머리글자 약자(UEB 10.7)를 낱말 속에서도 쓴다 (이슈 #1216).

기대값은 gold 영어책(holdout 제외) 낱말 다수 꼴 — 괄호 안은 '그 꼴 수 / 그 낱말 전체 수 · 첫 출처(책/부분/쪽 · 줄)'.
"""
import pytest

from app.ai.braille.eng_braille import translate_word


@pytest.mark.parametrize("word,cells", [
    ("phone", "⠏⠓⠐⠕"),         # 56/57 · EBS-E26-008 ans p0002 93
    ("money", "⠍⠐⠕⠽"),         # 93/95 · EBS-E26-008 ans p0121 54
    ("never", "⠝⠐⠑"),          # 83/86 · EBS-E26-008 ans p0063 9
    ("bought", "⠃⠐⠳"),         # 71/72 · EBS-E26-008 ans p0015 122
    ("several", "⠎⠐⠑⠁⠇"),      # 38/39 · EBS-E26-008 ans p0002 96
    ("everyone", "⠐⠑⠽⠐⠕"),     # 41/44 · EBS-E26-008 ans p0004 90
    ("named", "⠐⠝⠙"),          # 35/35 · HS-REF-007 ans p0018 13 — name 은 뒤 d 여도 약자
])
def test_낱말_속_머리글자_약자(word, cells):
    assert translate_word(word) == cells


@pytest.mark.parametrize("word,cells", [
    ("postponed", "⠏⠕⠌⠏⠕⠝⠫"),   # 6/6 · EBS-E26-008 ans p0048 35 — one 의 e 가 ed 로
    ("gathered", "⠛⠁⠮⠗⠫"),      # 11/11 · EBS-E26-008 ans p0100 11 — there 의 e 가 er 로
    ("severe", "⠎⠑⠧⠻⠑"),        # 16/17 · HS-REF-007 ans p0089 58 — 예외 목록
    ("colonel", "⠉⠕⠇⠕⠝⠑⠇"),     # 3/3 · HS-TXT-K1343 body p0140 19 — 예외 목록
    ("coupon", "⠉⠳⠏⠕⠝"),        # 5/5 · EBS-E26-008 ans p0056 45 — ou 가 upon 보다 먼저
])
def test_겹침_자리는_풀어씀(word, cells):
    assert translate_word(word) == cells


@pytest.mark.parametrize("word,cells", [
    # there · where · here — 긴 약자가 먼저(here 를 안에서 다시 줄이지 않는다)
    ("there", "⠐⠮"),            # 164/167 · EBS-E26-008 ans p0003 15
    ("where", "⠐⠱"),            # 146/171 · EBS-E26-008 ans p0047 106
    ("here", "⠐⠓"),             # 39/40 · EBS-E26-008 ans p0042 134
    ("anywhere", "⠁⠝⠽⠐⠱"),      # 12/12 · EBS-E26-008 ans p0048 30
    ("somewhere", "⠐⠎⠐⠱"),      # 5/5 · EBS-E26-008 body p0100 35
    # today · day — 단축형이 먼저
    ("today", "⠞⠙"),            # 21/21 · EBS-E26-008 ans p0073 133
    ("day", "⠐⠙"),              # 110/114 · EBS-E26-008 ans p0003 89
    ("someday", "⠐⠎⠐⠙"),        # 2/2 · EBS-E26-008 ans p0105 60
    # every · ever — 낱말 약자가 먼저
    ("every", "⠑"),             # 129/130 · EBS-E26-008 ans p0002 105
    ("ever", "⠐⠑"),             # 46/46 · EBS-E26-008 body p0055 62
    ("however", "⠓⠪⠐⠑"),        # 3/3 · HS-REF-T24-136 body p0190 46
])
def test_우선순위(word, cells):
    assert translate_word(word) == cells
