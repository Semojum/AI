"""점자 태깅 목록표 한글 강조 둘 · 빈칸 이름 둘(#1382).

기대값은 「한국 점자 규정」 제56항 [붙임] 예문의 원문 BRF(재추출 2481~2482 · 2489~2490행)를 BRF ASCII 표로 옮긴 것이다
(번역기로 만들지 않는다). 원문은 32칸에서 접혀 있어, 접힌 자리를 잇고 줄머리 두 칸 · 줄 끝 채움을 뗐다.
"""
from app.ai.braille.translator import translate_tagged_text
from app.utils.braille_ascii import ascii_to_unicode


def _reg(brf: str) -> str:
    # 규정 텍스트의 백틱은 빈칸이다(추출 꼴). 코퍼스 .brl 의 백틱(⠈)과 다르다.
    return ascii_to_unicode(brf, backtick="space").replace(" ", "⠀")


def test_색강조는_제1점역자_정의_글자체표다():
    # 2480~2482행 "최명희 작가는 전라북도 전주 출신입니다." — '전라북도 전주' 가 색상으로 강조된 자리
    want = _reg(';ye}jw`.a$cz`"-.)"<~maiu`.).m-1`;&,qobcoi4')
    assert translate_tagged_text("최명희 작가는 <!색강조>전라북도 전주<!/색강조> 출신입니다.") == want


def test_취소선은_제2점역자_정의_글자체표다():
    # 2488~2490행 "금액 할인: 15,000원 14,500원" — 취소된 앞 금액
    want = _reg('@{5ra`j1q"1`@-#ae1jjjp3-a`#ad1ejjp3')
    assert translate_tagged_text("금액 할인: <!취소선>15,000원<!/취소선> 14,500원") == want


def test_목록표_빈칸_이름은_엔진_이름과_같은_점자다():
    # 제73항 — 밑줄 빈칸 ⠸⠤ · 네모 빈칸 ⠸⠦⠀⠴⠇. 교열이 내는 `<!밑줄>` · `<!네모>` 와 같아야 한다.
    for new, old in (("<!밑줄빈칸>", "<!밑줄>"), ("<!네모빈칸>", "<!네모>")):
        s = f"다음 {new}에 들어갈 말"
        assert translate_tagged_text(s) == translate_tagged_text(s.replace(new, old))
    assert "⠸⠤" in translate_tagged_text("다음 <!밑줄빈칸>에")
    assert "⠸⠦⠀⠴⠇" in translate_tagged_text("<!네모빈칸>에")
