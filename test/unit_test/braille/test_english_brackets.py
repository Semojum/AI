"""한글 없는 영어 산문 줄의 괄호는 통일영어점자 꼴(#1224, 원장 B-30 · C-165 A-1).

「한국 점자 규정」 제32항(재추출 1650~1651행): 로마자표와 종료표 사이는 「통일영어점자 규정」에 따른다.
예(1664~1666행) `모음에는 (a), (e) …` = `0"<a">1`"<;e">1…` — 소괄호 ⠐⠣ ⠐⠜.
대괄호 ⠨⠣ ⠨⠜ 는 gold 영어책 264 : 한글 꼴 191(그중 189 가 HS-REF-T26-013 한 권).
"""
from app.ai.braille.translator import translate_tagged_text

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


def test_홑_글자_보기_표지는_종전대로() -> None:
    # C-165 A-2 판정 보류 — gold 가 EBAE ⠶a⠶ 801 · 한글 꼴 92 로 갈린다
    assert translate_tagged_text("(a) the hair or nails").startswith("⠦⠄⠁⠠⠴")


def test_한글_줄은_종전대로() -> None:
    assert "⠦⠄" in translate_tagged_text("사과(apple)를 먹었다.")


def test_번호_머리와_한글_꼴_기호_줄은_종전대로() -> None:
    # gold MS-REF-007 body p0004 `1) - Check-up Test` = ⠼⠁⠠⠴… · 단어장 어원 줄 `dis(= not) +` 은 한글 문맥(⠦⠄⠒⠒ · ⠢)
    assert translate_tagged_text("1) - Check-up Test").startswith("⠼⠁⠠⠴")
    assert "⠦⠄⠒⠒" in translate_tagged_text("(Voca+) dis(= not) +")
