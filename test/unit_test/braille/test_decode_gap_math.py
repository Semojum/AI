"""두 칸 뒤에 조사가 오는 토막은 수식으로 읽는다 (#1097, 수학 제11항).

규정 BRF 는 「한국 점자 규정」 재추출 행 번호. 백틱은 규정 원문 관례대로 칸 띄우기다.
- 제11항(3234행): 수식과 수학적 표기는 앞뒤를 두 칸씩 띄어 쓴다.
- 제11항 2호 예(3322행): `일반항 aₙ의 값` = `o1^3j7``a;n``w`$b'` — 수표가 없는 첨자 식.
"""
from app.utils.braille_ascii import ascii_to_unicode
from app.utils.braille_back import decode


def _brf(s: str) -> str:
    return ascii_to_unicode(s, backtick="space")


def test_수표_없는_첨자_식_뒤_조사():
    assert decode(_brf("o1^3j7``a;n``w`$b'")) == "일반항 a_n의 값"     # 3322행


def test_뒤에_조사가_없으면_종전대로():
    # 두 칸 사이에 섰어도 뒤가 조사가 아니면 자리 근거가 없다 — 한글 읽기를 그대로 둔다.
    assert "a_n" not in decode(_brf("o1^3j7``a;n``o1^3j7"))
