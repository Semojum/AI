"""수식 토큰에서 기호 뒤 변수를 한글로 읽지 않는다 — 「수학 점자」 제12항.

이 파일이 지키는 것: 수식 구역에서 **로마자표 없이 쓴 변수**(제12항)가 한글 음절로
새지 않는 것. `_korean_tail`(꼬리가 통째로 한글로 풀리면 한글 디코더에 넘긴다)이 먼저
걸려 `a^(2-x)` 가 `a^(2-옥언` 으로, `|x|` 가 `|옥열` 로 나갔다.

**순환검증 금지**: 어느 앞 셀까지 '뒤는 변수'로 볼지는 규정 정답쌍 312건 셀별 귀속과
실물 1,180쪽 A/B 로 갈랐다. ⠳(절댓값 제21항) 4:0 · ⠷(여는 괄호 제6항) 5:1 ·
⠔(뺄셈 제2항) 1:0 만 넣고, ⠌(분수)·⠦·⠐·닫는 괄호는 뒤에 한글이 실재해 뺐다.
"""
from __future__ import annotations

import pytest

from app.utils.braille_back import decode


@pytest.mark.parametrize("cells, expected", [
    ("⠳⠭⠳", "|x|"),                    # 절댓값 — `|옥열` 이었다
    ("⠁⠘⠷⠼⠃⠔⠭⠾", "a^(2-x)"),          # 여는 괄호·뺄셈 — `a^(2-옥언` 이었다
])
def test_기호_뒤_변수는_로마자로(cells, expected):
    assert decode(cells, math=True) == expected


@pytest.mark.parametrize("cells, expected", [
    # 분수 ⠌ 뒤에는 한글이 실재한다 — 규정 정답쌍의 `…분의이다.` 가 그 자리다.
    ("⠼⠃⠌⠼⠁⠕⠊⠲", "2분의1이다."),
])
def test_한글_꼬리는_그대로_한글이다(cells, expected):
    assert decode(cells, math=True) == expected


def test_한글표_뒤는_한글이다():
    """⠷ 는 여는 괄호이자 **한글표 ⠸⠷(제39항)의 뒷 셀**이다.

    ⠸ 가 앞에 붙으면 한글표라 뒤도 한글이다(`1_(이라도` → `1_(o·아도` 로 깨지던 자리).
    전 코퍼스에 ⠸⠷ 가 2,305회·336쪽 나온다 — 가드가 실제로 걸리는 자리다.
    """
    assert "ㅗ" not in decode("⠸⠷⠕⠐⠣⠊⠥", math=True)
