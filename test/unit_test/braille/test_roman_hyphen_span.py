"""로마자 + 붙임표 + 로마자는 한 로마자 구간이다(「한글 점자」 제32항 → 통일영어점자).

제36항 예문(규정_텍스트 1792행) `그 책의 v-x쪽을 읽어 보세요.` = ``@[`;raw`0v-;x4,.x!`o1as`^u,n+4``.
붙임표 앞에서 종료표를 적지 않고 뒤에서 로마자표를 다시 열지 않는다. 제33항 [다만]의 "‘-’ 앞 종료표" 는
로마자와 **한글** 사이 자리다(`U-도서관` = ⠴⠠⠥⠲⠤…) — 그 자리는 그대로 둔다. 기대값은 규정 원문 BRF.
"""
from __future__ import annotations

import pytest

from app.ai.braille.translator import translate_body
from app.utils.braille_ascii import ascii_to_unicode


def _cells(s: str) -> str:
    return "".join(c for c in s if 0x2800 <= ord(c) <= 0x28FF and c != "⠀")


def _body(text: str) -> str:
    return _cells("".join(translate_body(text)[0]))


def test_규정_예문_v_x() -> None:
    assert _body("그 책의 v-x쪽을 읽어 보세요.") == _cells(ascii_to_unicode(
        "@[`;raw`0v-;x4,.x!`o1as`^u,n+4", backtick="space"))


@pytest.mark.parametrize("src,want", [
    ("CD-ROM을 샀다", "⠴⠰⠠⠠⠉⠙⠤⠠⠠⠗⠕⠍⠲"),     # 통일영어점자 5.7.2 예문 `CD-ROM` = ;,,cd-,,rom
    ("B-team이다", "⠴⠠⠃⠤⠞⠂⠍⠲"),
])
def test_붙임표로_이어진_로마자는_로마자표를_다시_열지_않는다(src: str, want: str) -> None:
    assert want in _body(src)


@pytest.mark.parametrize("src,want", [
    ("U-보트", "⠴⠠⠥⠲⠤"),        # 로마자와 한글 사이 — 제33항 [다만] 종료표 적음
    ("D-100일", "⠴⠠⠙⠤⠼⠁⠚⠚"),   # 로마자와 숫자 — 제35항 종료표 없음
])
def test_붙임표_뒤가_로마자가_아니면_종전대로(src: str, want: str) -> None:
    assert want in _body(src)
