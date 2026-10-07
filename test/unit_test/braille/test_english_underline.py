"""영어 줄 밑줄 강조 → 통일영어점자 밑줄 표지 (이슈 #1204).

「한국 점자 규정」 제7·28항(영어는 통일영어점자) · 점역사 Q&A A13(영문 강조는 UEB 규정).
낱말 ⠸⠂ · 홑 글자 ⠸⠆ · 3낱말 이상 구절 ⠸⠶ … ⠸⠄ · 낱말 중간에서 끝나면 종료표 ⠸⠄.
기대값은 gold 영어책 줄을 그대로 옮겼다(책/부분/쪽 · 줄 번호는 쪽 안 0부터). 입력은 그 줄의 묵자에
추출 층이 넘기는 `<!강조>` 를 gold 표지 자리에 넣은 것이다.
"""
import pytest

from app.ai.braille.constants import ENGLISH_GRADE1
from app.ai.braille.translator import translate_body


def _br(text: str) -> str:
    return "".join(translate_body(text)[0]).strip("⠀")


@pytest.mark.parametrize("text,cells", [
    # HS-REF-007 ans p0018 줄 3 — 낱말표 ⠸⠂
    ("crowded city <!강조>of<!/강조> Paris and moved to the",
     "⠉⠗⠪⠙⠫⠀⠉⠰⠽⠀⠸⠂⠷⠀⠠⠏⠜⠊⠎⠀⠯⠀⠍⠕⠧⠫⠀⠞⠕⠀⠮"),
    # HS-REF-007 ans p0018 줄 32 — 대문자표는 표지 뒤, 쉼표는 태그 밖
    ("⑥ <!강조>Eventually<!/강조>, Picasso gathered",
     "⠼⠖⠀⠸⠂⠠⠑⠧⠢⠞⠥⠁⠇⠇⠽⠂⠀⠠⠏⠊⠉⠁⠎⠎⠕⠀⠛⠁⠮⠗⠫"),
    # HS-REF-007 ans p0018 줄 7 — 두 낱말은 낱말마다 ⠸⠂ (태그가 하나여도 같다)
    ("desperately <!강조>longed<!/강조> <!강조>for<!/강조> familiar",
     "⠙⠑⠎⠏⠻⠁⠞⠑⠇⠽⠀⠸⠂⠇⠰⠛⠫⠀⠸⠂⠿⠀⠋⠁⠍⠊⠇⠊⠜"),
    ("desperately <!강조>longed for<!/강조> familiar",
     "⠙⠑⠎⠏⠻⠁⠞⠑⠇⠽⠀⠸⠂⠇⠰⠛⠫⠀⠸⠂⠿⠀⠋⠁⠍⠊⠇⠊⠜"),
    # HS-REF-007 ans p0012 줄 93 — 3낱말 이상은 구절 ⠸⠶ … ⠸⠄, 태그 밖 마침표는 종료표 뒤
    ("<!강조>call the lost and found<!/강조>.",
     "⠸⠶⠉⠁⠇⠇⠀⠮⠀⠇⠕⠌⠀⠯⠀⠋⠨⠙⠸⠄⠲"),
    # MS-REF-T25-078 body p0147 줄 129
    ("<!강조>how long the mountain range is<!/강조>?",
     "⠸⠶⠓⠪⠀⠇⠰⠛⠀⠮⠀⠍⠨⠞⠁⠔⠀⠗⠁⠝⠛⠑⠀⠊⠎⠸⠄⠦"),
    # HS-REF-T24-136 body p0059 줄 63 — 홑 글자 낱말은 기호표 ⠸⠆
    ("③ <!강조>A<!/강조> Peterson is here to see",
     "⠼⠒⠀⠸⠆⠠⠁⠀⠠⠏⠑⠞⠻⠎⠕⠝⠀⠊⠎⠀⠐⠓⠀⠞⠕⠀⠎⠑⠑"),
    # HS-REF-T26-013 body p0011 줄 13(줄머리 문항 번호 `1` 은 뗐다) — 낱말 중간에서 끝나면 종료표 ⠸⠄
    ("Be mindful of your <!강조>possession<!/강조>s",
     "⠠⠆⠀⠍⠔⠙⠰⠇⠀⠷⠀⠽⠗⠀⠸⠂⠏⠕⠎⠎⠑⠎⠨⠝⠸⠄⠎"),
    # MS-REF-T25-078 body p0130 — 숫자 뒤 단위(제69항) 판정은 표지 너머 낱말을 본다
    ("30km <!강조>an<!/강조> hour near schools.",
     "⠼⠉⠚⠅⠍⠀⠸⠂⠁⠝⠀⠓⠳⠗⠀⠝⠑⠜⠀⠎⠡⠕⠕⠇⠎⠲"),
])
def test_영어_줄_밑줄(text, cells):
    assert _br(text) == cells


@pytest.mark.parametrize("text,cells", [
    # HS-REF-007 ans p0016 (두 줄 이음) — 표지 앞 쉼표는 통일영어점자 ⠂ 그대로(세그를 끊으면 한글 ⠐ 가 된다)
    ("car, <!강조>wondering who had the nerve to make the legendary artist wait<!/강조>.",
     "⠉⠜⠂⠀⠸⠶⠺⠕⠝⠙⠻⠬⠀⠱⠕⠀⠸⠓⠀⠮⠀⠝⠻⠧⠑⠀⠞⠕⠀⠍⠁⠅⠑⠀⠮⠀⠇⠑⠛⠢⠙⠜⠽⠀⠜⠞⠊⠌⠀⠺⠁⠊⠞⠸⠄⠲"),
    # EBS-E26-008 ans p0069 (두 줄 이음) — 표지 앞 쌍점은 ⠒ 그대로
    ("Debora: <!강조>How should I get ready for the design competition?<!/강조>",
     "⠠⠙⠑⠃⠕⠗⠁⠒⠀⠸⠶⠠⠓⠪⠀⠩⠙⠀⠠⠊⠀⠛⠑⠞⠀⠗⠂⠙⠽⠀⠿⠀⠮⠀⠙⠑⠎⠊⠛⠝⠀⠉⠕⠍⠏⠑⠞⠊⠰⠝⠦⠸⠄"),
])
def test_표지_밖_부호는_그대로(text, cells):
    assert _br(text) == cells


@pytest.mark.parametrize("text,cells", [
    # ES-REF-T26-007 body p0020 줄 6 — 1급 줄은 로마자표가 표지 앞
    ("<!강조>This Is My Book.<!/강조>", "⠴⠸⠶⠠⠞⠓⠊⠎⠀⠠⠊⠎⠀⠠⠍⠽⠀⠠⠃⠕⠕⠅⠲⠸⠄"),
    # ES-REF-T26-007 body p0066 줄 6
    ("<!강조>Two<!/강조> <!강조>Fingers<!/강조>.", "⠴⠸⠂⠠⠞⠺⠕⠀⠸⠂⠠⠋⠊⠝⠛⠑⠗⠎⠲"),
])
def test_영어_1급_줄(text, cells):
    tok = ENGLISH_GRADE1.set(True)
    try:
        assert _br(text) == cells
    finally:
        ENGLISH_GRADE1.reset(tok)


@pytest.mark.parametrize("text", [
    "<!강조>A<!/강조>",                 # 홀로 선 라벨(val 윤리 14곳) — 오검출
    "<!강조>an<!/강조>",                # 수열 a_n 조각
    "Sn= <!강조>n(a+l)<!/강조>",         # 분수 분자(분수선 오인)
    "a <!강조>1<!/강조> b",
    "<!강조>Hello<!/강조>!",             # 한 낱말 줄은 오검출과 못 가른다 — 종전대로 걷는다
])
def test_오검출_방어는_종전대로(text):
    assert _br(text) == _br(text.replace("<!강조>", "").replace("<!/강조>", ""))


def test_한글_줄은_종전대로():
    assert _br("나는 <!강조>사과<!/강조>다.") == "⠉⠉⠵⠀⠠⠤⠇⠈⠧⠤⠄⠊⠲"       # 제56항 드러냄표
    assert _br("나는 <!강조>apple<!/강조>을 먹었다.") == _br("나는 apple을 먹었다.")
