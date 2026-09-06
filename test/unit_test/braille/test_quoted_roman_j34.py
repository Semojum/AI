"""제34항 — 따옴표로 묶인 로마자에는 종료표가 없다 (2026-09-06).

규정 제34항: "로마자가 따옴표나 괄호 등으로 묶일 때에는 로마자 종료표를 적지 않는다."
그러면 여는 큰따옴표로 연 구간을 **닫는 것은 닫는 큰따옴표 ⠴** 인데, 그 셀이 로마자표와
같다. `_decode_line` 이 런을 끝낸 자리의 ⠴ 를 다시 로마자표로 읽어, 따옴표가 사라지고
뒤 한글이 로마자로 먹혔다 — `“that”은`(⠦⠴⠹⠁⠞⠴⠵) 이 `"thatz` 로 나갔다.

★ **다른 여는 부호에는 걸면 안 된다.** 닫는 쪽이 두 셀이라 이 자리에 안 온다
  (‘…’=⠠⠦…⠴⠄ · (…)=⠦⠄…⠠⠴ · 「…」=⠐⠦…⠴⠂). 넓게 걸었더니 `x km/h` 와
  `(Commonwealth` 의 **진짜 로마자표**가 막혀 깨졌다 — 그 둘을 회귀로 박아 둔다.
"""
from __future__ import annotations

import pytest

from app.utils.braille_back import decode


@pytest.mark.parametrize("cells, want", [
    # 규정 제34항 예문 — 문 앞에 “Open”이라고 쓰여 있었다.
    ("⠦⠴⠠⠕⠏⠢⠴⠕⠐⠣⠈⠥", '"Open”이라고'),
    # 실물(HS-REF-007 ans/p0017) — “that”은
    ("⠦⠴⠹⠁⠞⠴⠵", '"that”은'),
    # 실물(EBS 저작권 고지) — “EBS”와
    ("⠦⠴⠠⠠⠑⠃⠎⠴⠺", '"EBS”의'),
])
def test_closing_quote_is_not_a_roman_indicator(cells, want):
    assert decode(cells).strip() == want


@pytest.mark.parametrize("cells, want", [
    # 런 뒤 ⠴ 가 **진짜 로마자표(단위표)** 인 자리 — 막으면 안 된다.
    ("⠴⠰⠭⠴⠅⠍⠸⠌⠓⠲⠺", "xkm/h의"),
    # 여는 소괄호(⠦⠄)로 연 구간 — 닫는 쪽이 ⠠⠴ 라 이 가드에 안 걸린다.
    ("⠡⠚⠃⠦⠄⠴⠠⠉⠕⠴⠍⠍⠕⠝⠺⠂⠇⠹", "연합(Commonwealth"),
])
def test_real_roman_indicator_still_opens(cells, want):
    assert decode(cells).strip() == want
