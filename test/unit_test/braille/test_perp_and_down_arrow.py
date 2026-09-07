"""수직 ⊥(「수학 점자」 제41항) · 아래쪽 화살표 ↓(「한글 점자」 제70항) 역점역 가드.

**순환검증 금지**: 기대값은 규정 예문 그 자체다(재추출본 행 번호를 함께 적는다).
  제41항 3775~3777행  `AB⊥DE` = `,,AB0',,DE`
  제70항 2773·2779행  아래쪽 화살표 = `^3o`

두 규칙 다 **좁게** 걸었다. 셀이 본문과 겹치기 때문이다.
  ⠴⠄ 는 전권 31,132회인데 사실상 전부 닫는 홑따옴표 `’` 다 → 양옆이 대문자 단어표일 때만
  ⠘⠒⠕ 는 약자 `반`+`이` 와 같은 셀이다 → 줄 전체가 그 토큰 하나뿐일 때만
"""
from __future__ import annotations

import pytest

from app.utils.braille_ascii import ascii_to_unicode
from app.utils.braille_back import decode


def test_수직_규정예문():
    assert decode(ascii_to_unicode(",,AB0',,DE", backtick="space")) == "AB⊥DE"


@pytest.mark.parametrize("cells", [
    "⠠⠦⠠⠕⠴⠄⠕⠊⠲",      # ‘O’이다.  — 전권 7,446회 꼴
    "⠠⠠⠁⠛⠁⠞⠴⠄",         # ‘AGAT’    — 전권 218회 꼴(앞만 대문자 단어표)
])
def test_수직으로_안_읽는_자리(cells):
    assert "⊥" not in decode(cells)


def test_아래쪽_화살표_줄_전체():
    assert decode("⠀⠀⠘⠒⠕").strip() == "↓"


def test_문장_안에서는_화살표로_안_읽는다():
    """`거래를 반이` — 전권 127회 중 여섯 이상이 진짜 한글이라 손대지 않는다."""
    assert "↓" not in decode("⠈⠎⠐⠗⠐⠮ ⠘⠒⠕")
