"""한글 없는 영어 줄의 로마자표 다시 열기(#1223, 원장 C-164 · B-29).

- C-164: 한글 꼴 화살표 ⠒⠕ 뒤 영어는 로마자표 ⠴ 를 다시 연다. gold 영어책 274/288(95%, 4권).
- B-29: 띄어 쓴 줄표 · 빈칸 뒤에는 ⠴ 를 덧붙이지 않는다. gold 빈칸 뒤 0/2,261 · 줄표 뒤 12/385.
기대값은 gold BRF 원문 줄을 그대로 옮긴 것이다(BRF ASCII → 유니코드 점자).
"""
import pytest

from app.ai.braille.translator import translate_tagged_text

_BRF = " A1B'K2L@CIF/MSP\"E3H9O6R^DJG>NTQ,*5<-U8V.%[$+X!&;:4\\0Z7(_?W]#Y)="


def _u(brf: str) -> str:
    return "".join(chr(0x2800 + _BRF.index(c.upper())) for c in brf)


@pytest.mark.parametrize("text,gold", [
    # MS-REF-007 ans p0087 174행
    ("→ If you turn to the left, you will", "3o 0,if y turn to ! left1 y w"),
    # HS-REF-007 ans p0016 27행
    ("→ wondering who had the nerve to", "3o 0wond]+ :o _h ! n]ve to"),
])
def test_화살표_뒤_로마자표를_다시_연다(text: str, gold: str) -> None:
    assert translate_tagged_text(text) == _u(gold)


@pytest.mark.parametrize("text,gold", [
    # MS-REF-007 body p0016 11행
    ("<!밑줄> at history, and she is interested", ".- at hi/ory1 & %e is 9t]e/$"),
    # MS-REF-007 body p0004 50행
    ("might, must, should - Check-up Test.", "mi<t1 m/1 %d - ,*eck-up ,te/4"),
])
def test_띄어_쓴_빈칸_줄표_뒤에_로마자표를_안_붙인다(text: str, gold: str) -> None:
    assert translate_tagged_text(text) == _u(gold)


def test_붙인_붙임표_뒤는_종전대로_연다() -> None:
    # 한글 줄 `-UN-` = ⠤⠴⠠⠠⠥⠝⠤ (사회문화 p100 · 108 관행, _emit_mixed 주석)
    assert "⠤⠴⠠⠠⠥⠝⠤" in translate_tagged_text("사과 -UN- 기구")


def test_원소_반응식_화살표는_안_연다() -> None:
    # 과학 점자 제1항 꼴(test_back_roundtrip.TestBareElementLine) — 영어 산문 줄이 아니다
    assert "⠴" not in translate_tagged_text("H, Cl → HCl")
