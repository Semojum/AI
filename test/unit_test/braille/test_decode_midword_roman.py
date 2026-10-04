"""낱말 가운데 로마자 역점역 (#1097, 「한글 점자」 제29항).

규정 BRF 는 「한국 점자 규정」 재추출 행 번호. 백틱은 규정 원문 관례대로 칸 띄우기다.
- 제29항(1496행): 국어 문장 안의 로마자는 앞에 로마자표 ⠴, 뒤에 종료표 ⠲.
- 수학 제24항 예(3643행): `제n항까지의` = `.n0n4j7,$.ow`.
"""
from app.utils.braille_ascii import ascii_to_unicode
from app.utils.braille_back import decode


def test_제n항():
    assert decode(ascii_to_unicode(".n0n4j7,$.ow", backtick="space")) == "제n항까지의"   # 3643행


def test_받침_ㅎ_낱말은_종전대로():
    # ⠴ 는 받침 ㅎ 이기도 하다 — `않는다.)` 는 같은 셀 꼴이지만 실재하는 낱말이라 손대지 않는다.
    assert decode("⠣⠒⠴⠉⠵⠊⠲⠠⠴") == "않는다.)"
