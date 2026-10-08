"""한글 없는 영어 산문 줄의 괄호는 통일영어점자 꼴(#1224, 원장 B-30 · C-165 A-1).

「한국 점자 규정」 제32항(재추출 1650~1651행): 로마자표와 종료표 사이는 「통일영어점자 규정」에 따른다.
예(1664~1666행) `모음에는 (a), (e) …` = `0"<a">1`"<;e">1…` — 소괄호 ⠐⠣ ⠐⠜.
대괄호 ⠨⠣ ⠨⠜ 는 gold 영어책 264 : 한글 꼴 191(그중 189 가 HS-REF-T26-013 한 권).
"""
from app.ai.braille.translator import translate_body, translate_tagged_text

_BRF = " A1B'K2L@CIF/MSP\"E3H9O6R^DJG>NTQ,*5<-U8V.%[$+X!&;:4\\0Z7(_?W]#Y)="


def _u(brf: str) -> str:
    return "".join(chr(0x2800 + _BRF.index(c.upper())) for c in brf)


def test_대괄호는_통일영어점자_꼴() -> None:
    # EBS-E26-008 ans p0018 10행
    assert translate_tagged_text("Just a minute. [Pause] Here it is.") == _u(',J A M9UTE4 .<,PAUSE.> ,"H X IS4')


def test_낱말_소괄호는_통일영어점자_꼴() -> None:
    # 괄호 꼴은 제32항 예 `"<a">`(⠐⠣ ⠐⠜) — gold 영어책은 이 꼴을 안 쓴다(원장 C-165, 규정 우선)
    out = translate_tagged_text("Read (Sample) carefully, please.")
    assert "⠐⠣⠠⠎⠁⠍⠏⠇⠑⠐⠜" in out
    assert "⠦⠄" not in out and "⠠⠴" not in out


def test_홑_낱자_보기_표지는_EBAE_괄호() -> None:
    # C-165 A-2(#1229) — 표지 903곳 중 로마자표 구간 밖 807 이라 관행 ⠶ … ⠶(801, 6권). HS-REF-007 ans p0039 12행
    # 밑줄(#1207)은 본문 경로(translate_body)가 적는다
    assert translate_body("(a) <!강조>him<!/강조> about a Spanish barber")[0] == [_u("7a7 _1hm ab a ,spani% b>b]")]
    # a · i · o 밖의 낱자는 1급 기호 ⠰ — gold `(b)` = ⠶⠰⠃⠶ 286
    assert "⠶⠰⠃⠶" in translate_tagged_text("his home (b) the old one")


def test_숫자_보기_표지는_한글_소괄호() -> None:
    # gold 숫자 표지 `(1)` 은 한글 소괄호 87
    assert translate_tagged_text("See (1) and (2) here please").count("⠦⠄") == 2


def test_한글_줄은_종전대로() -> None:
    assert "⠦⠄" in translate_tagged_text("사과(apple)를 먹었다.")


def test_번호_머리와_한글_꼴_기호_줄은_종전대로() -> None:
    # gold MS-REF-007 body p0004 `1) - Check-up Test` = ⠼⠁⠠⠴… · 단어장 어원 줄 `dis(= not) +` 은 한글 문맥(⠦⠄⠒⠒ · ⠢)
    assert translate_tagged_text("1) - Check-up Test").startswith("⠼⠁⠠⠴")
    assert "⠦⠄⠒⠒" in translate_tagged_text("(Voca+) dis(= not) +")
