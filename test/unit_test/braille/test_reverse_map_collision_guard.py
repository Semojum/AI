"""본문 기호 역맵이 한글을 먹지 않게 지키는 가드 (#1112).

역방향은 다대일이라, 정방향만 보고 기호를 넣으면 흔한 한글 점형을 가로챈다
(0903 실측 10종 · 501쪽, `마을을` → `마∬`). 본문 기호 역맵(`_SYMBOL_REV`)의 점형이
한글 음절 역맵(`_SYLLABLE_REV`)만으로 끝까지 쪼개지면 겹침이다.
겹치는데도 남겨야 하면 아래 허용 목록에 **사유와 gold 실측**을 달고 넣는다.
"""
import re

from app.utils import braille_back as B

# 겹치지만 지금 한글을 먹지 않는 것(gold 전권 18,892쪽, 2026-10-05 실측).
# `_WORD_ONLY_SYMBOLS` 에 든 것은 홀로 선 낱말일 때만 기호로 읽으므로 따로 허용한다.
ALLOWED = {
    "⠠⠨⠙": "Δ — gold 481회 모두 극한 · 증분식(lim_Δx), 본문 `짜파` 0회",
    "⠠⠨⠇": "Λ — gold 0회",
    "⠠⠨⠋": "Φ — gold 0회",
    "⠪⠶⠕": "⇄ — gold 셀 3,921회지만 역점역에 ⇄ 로 나온 것 0회(앞단 가드)",
    "⠨⠨⠨": "⋱ — gold 0회",
    "⠨⠨⠢": "∄ — gold 0회",
}
_HANGUL = re.compile(r"^[가-힣]+$")


def _as_hangul(cells: str, memo: dict = {}) -> str | None:
    if cells in memo:
        return memo[cells]
    if not cells:
        return ""
    for ln in range(min(len(cells), 6), 0, -1):
        if cells[:ln] in B._SYLLABLE_REV:
            rest = _as_hangul(cells[ln:])
            if rest is not None:
                memo[cells] = B._SYLLABLE_REV[cells[:ln]] + rest
                return memo[cells]
    memo[cells] = None
    return None


def test_본문_기호_역맵은_한글과_안_겹친다():
    clash = {}
    for cells, sym in B._SYMBOL_REV.items():
        if cells in B._SYLLABLE_REV:
            continue                               # 음절이 이긴다(_COMBINED 순서)
        ko = _as_hangul(cells)
        if (ko is not None and _HANGUL.match(ko) and cells not in ALLOWED
                and cells not in B._WORD_ONLY_SYMBOLS):
            clash[cells] = f"{sym} ↔ {ko}"
    assert not clash, f"한글로도 읽히는 기호 점형: {clash} — 사유와 gold 실측을 달아 ALLOWED 에 넣거나 빼라"


def test_한글을_먹던_넷은_낱말_안에서_한글로_읽는다():
    assert B.decode("⠑⠣⠮⠮") == "마을을"                      # gold `마을을` 이 `마∬` 였다
    assert B.decode("⠠⠨⠑⠅⠰⠍⠎") .startswith("짜")           # `짜맞추어` 가 `Εk추어` 였다
    assert B.decode("⠮⠮") == "∬"                           # 홀로 선 낱말이면 기호
