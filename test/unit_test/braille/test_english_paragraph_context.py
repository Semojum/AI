"""로마자표 없는 영문 문단 — #842 잔여분 (2026-09-12, 원장 R-77).

#846 뒤에도 영어 지면 245쪽에서 로마자 148,401자(53%)가 한글로 샜다. `_english_line` 이
None 을 돌려주는 줄을 부류별로 세어 큰 것부터 고쳤다(동결 코퍼스 1,251쪽 gold BRF 전수).

1. 낱말 **중간**의 첫글자 약자(⠐⠑ ever · ⠐⠳ ought · ⠸⠍ many)에서 런이 끊겼다 — `however`.
2. 낱말 안 하이픈 ⠤(`high-profile`)·빗금 ⠸⠌(`prevent/protect`)에서 런이 끊겼다.
3. 낱말 중간 ⠠⠝·⠠⠽ 가 ation·ally(EBAE 끝글자 약자)가 아니라 대문자로 읽혀 가드에 걸렸다.
4. 낱말 앞 로마자표 ⠴·이탤릭표 ⠨·대문자표 붙은 홑 약자(⠠⠦ His)·작은따옴표 ⠠⠦ ⠴⠄ 를 못 뗐다.
5. **증거 게이트** — 낱말은 다 읽히는데 기능어가 둘이 안 되는 줄(2,940줄·66,000셀)이 가장 컸다.
   제29항 [다만]의 단위는 문단이다. 앞뒤 줄이 영어로 읽힌 줄은 문맥으로 받는다(`_english_ctx`).
   한글 줄이 끌려오지 않게 영어 음운 거르개(`_ENG_JUNK_RE`)를 둔다.
6. BRF 의 쪽 나눔 `\\f` 가 첫 낱말에 붙어 줄 판정을 막았다.

측정(두 팔 같은 커밋): 영어 지면 로마자 회수율 45.9% → 89.5%(쪽 단위 역점역), 한글 우세
1,006쪽의 로마자 21,817 → 21,953자(+136). 문맥으로 뒤집힌 한글 줄 4(전수).
"""
from __future__ import annotations

import pytest

from app.utils.braille_ascii import ascii_to_unicode
from app.utils.braille_back import _english_line, decode


@pytest.mark.parametrize("cells, expected", [
    # 이슈 #842 본문의 대표 줄(gold 외국어 p016) — ⠐⠑(ever)가 낱말 중간에 온다
    (ascii_to_unicode(',:5 ! PA9T+S 7 F/ 4COV]$1 H["E1', backtick="cell"),
     "When the paintings were first discovered, however,"),
    ("⠞⠀⠭⠀⠝⠐⠑⠀⠕⠒⠥⠗⠗⠫⠀⠖⠓⠍⠀⠖⠇⠕⠕⠅⠀⠿", "that it never occurred to him to look for"),
    ("⠮⠀⠞⠗⠕⠕⠏⠎⠀⠷⠀⠠⠛⠻⠸⠍⠀⠯⠀⠠⠋⠗⠁⠝⠉⠑", "the troops of Germany and France"),
    # 낱말 안 하이픈
    ("⠁⠎⠎⠕⠉⠊⠁⠞⠑⠀⠮⠍⠧⠎⠀⠾⠀⠓⠊⠣⠤⠏⠗⠕⠋⠊⠇⠑", "associate themselves with high-profile"),
    # 낱말 중간 ⠠⠝ = ation (EBAE) — 종전 `informN`
    ("⠏⠗⠕⠧⠊⠙⠑⠎⠀⠽⠀⠾⠀⠧⠁⠇⠥⠁⠼⠀⠔⠿⠍⠠⠝⠀⠁⠃", "provides you with valuable information about"),
    # 낱말 앞 로마자표(제29항)는 벗긴다 · 대문자표 붙은 홑 약자 · 작은따옴표 ⠠⠦ ⠴⠄
    ("⠴⠠⠎⠉⠜⠉⠑⠀⠠⠗⠑⠎⠳⠗⠉⠑⠎⠀⠷⠀⠮⠀⠑⠜⠹", "Scarce Resources of the earth"),
    ("⠠⠦⠀⠋⠁⠮⠗⠀⠺⠁⠎⠀⠁⠀⠞⠂⠡⠻⠲", "His father was a teacher."),
    ("⠮⠀⠺⠕⠗⠙⠀⠠⠦⠕⠧⠻⠃⠕⠕⠅⠴⠄⠀⠔⠀⠮⠀⠏⠁⠎⠎⠁⠛⠑", "the word ‘overbook’ in the passage"),
])
def test_로마자표_없는_영문_줄이_끝까지_읽힌다(cells, expected):
    assert decode(cells) == expected


def test_이웃_줄이_영어면_기능어_없는_줄도_문맥으로_읽는다():
    """`Controlling Idea.` 는 기능어가 하나도 없어 홀로는 영어가 아니다(제29항 [다만]은 문단 단위)."""
    line = "⠠⠒⠞⠗⠕⠇⠇⠬⠀⠠⠊⠙⠑⠁⠲"
    assert _english_line(line) is None
    assert _english_line(line, ctx=True) == "Controlling Idea."
    para = ("⠠⠍⠁⠝⠥⠋⠁⠉⠞⠥⠗⠬⠀⠉⠕⠌⠎⠀⠩⠗⠁⠝⠅⠀⠞⠺⠢⠞⠽\n"
            "⠏⠻⠉⠢⠞⠀⠔⠀⠮⠀⠋⠊⠗⠌⠀⠽⠑⠜⠀⠷⠀⠮⠀⠏⠇⠁⠝⠲\n" + line)
    assert decode(para).split("\n") == [
        "Manufacturing costs shrank twenty",
        "percent in the first year of the plan.",
        "Controlling Idea.",
    ]


def test_영어_줄_옆의_한글_줄은_문맥에_끌려오지_않는다():
    """발문 꼬리 `적절한 것은?`(gold 외국어 p052)은 영어로도 끝까지 읽히지만 음운이 영어가 아니다."""
    para = "⠏⠻⠉⠢⠞⠀⠔⠀⠮⠀⠋⠊⠗⠌⠀⠽⠑⠜⠀⠷⠀⠮⠀⠏⠇⠁⠝⠲\n" + ascii_to_unicode(".?.TJ3 _SZ8", backtick="cell")
    assert decode(para).split("\n")[1] == "적절한 것은?"


@pytest.mark.parametrize("cells, expected", [
    ("⠚⠻⠕⠀⠴⠠⠭⠤⠠⠽⠲⠕⠑⠡", "형이 X-Y이면"),        # 하이픈 뒤 ⠠⠽ 는 ally 가 아니다
    ("⠚⠻⠕⠀⠴⠠⠗⠗⠠⠽⠽⠲⠕⠝", "형이 RrYy이에"),      # 로마자표 런의 낱말 중간 대문자는 진짜다(유전 기호)
    ("⠴⠇⠁⠞⠑⠀⠼⠁⠊⠙⠚⠎⠂⠀⠞⠕⠲", "late 1940s, to"),  # 낱말 앞 ⠴ 는 by 가 아니라 로마자표(R-77)
])
def test_로마자표로_연_런은_종전대로다(cells, expected):
    assert decode(cells).strip() == expected


def test_쪽_나눔_form_feed_는_줄_경계다():
    brf = "! PA9T+S T ADORN$ ! WALLS\f! PA9T+S T ADORN$ ! WALLS"
    cells = ascii_to_unicode(brf, backtick="cell")
    assert "\f" in cells and "[?" not in cells
    assert decode(cells).split("\n") == ["the paintings that adorned the walls"] * 2
