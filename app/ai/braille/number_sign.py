"""⠼ 한 점형의 두 뜻을 가르는 판정기 — 수표(제40항) vs 영어 약자 ble(EBAE).

**왜 필요한가**: 3456점(⠼)은 한국 점자에서 숫자 앞의 수표이고(제40항), 로마자표와
종료표 사이에 적는 영어 점자에서는(제32항 → 통일영어점자 위임, 표는 EBAE 관행)
약자 'ble'이다. 같은 셀이라 `possible`은 ⠏⠕⠎⠎⠊⠼로 적힌다. 그래서 "출력에 ⠼가
있다"만으로는 수표가 있는지 알 수 없다 — C5(수표 누락) 런타임 스캐너와 규정 패널이
둘 다 이 구분을 필요로 한다.

**판정 근거 — 수표 불변량**: 수표 뒤에는 반드시 숫자 셀이 온다(제40항, 규정_텍스트.txt
1911행 "숫자는 수표 #을 앞세워 적는다"). kor_math_rules._stage11_numbers도 같은 불변량을
docstring에 명시한다. 반대로 ble의 ⠼ 뒤에는 알파벳 셀·문장부호·공백이 온다.
코퍼스 실측(2026-07-27, `V2/temp/i2_wordshape.py`): -ble 낱말이 만든 ⠼ 중
뒤가 숫자 셀인 것은 val 6/266 · dev 1/42뿐이고, 그 잔여는 `contraction_lookalikes`가 센다.

**제64항 원문자(⠼ + 한 단 내린 숫자 셀)는 수표로 세지 않는다.** 두 가지 이유다.
  (1) `possible.`의 꼬리가 ⠼⠲인데 ⠲는 내린 숫자 4의 셀이라, 내림 셀을 받아들이면
      마침표로 끝나는 -ble 낱말이 전부 수표로 오인된다(코퍼스에서 가장 흔한 형태다).
  (2) 원문자는 원문에 ①로 들어오지 아라비아 숫자로 들어오지 않아, C5 게이트([0-9])가
      애초에 열리지 않는다. LaTeX `\\textcircled{N}`로 들어오는 자리만 이론상 걸리는데
      코퍼스 전체에서 dev 2 · val 4요소이고 전부 본문에 다른 숫자를 함께 갖는다
      (`V2/temp/i2_textcircled.py`로 확인).
"""
from __future__ import annotations

import re

from app.ai.braille.eng_braille import iter_words, translate_word
from app.ai.braille.kor_math_rules import _DIGIT_MAP

NUMBER_SIGN = "⠼"
# 숫자 셀 1~0 — kor_math_rules의 정본 맵을 그대로 쓴다(중복 정의로 갈리지 않게).
_DIGIT_CELLS = frozenset(_DIGIT_MAP.values())
# 인라인 태그(<!이름>) — 점역 대상이 아니라 낱말 세기에서 뺀다(text_braille와 같은 형태).
_TAG_TOKEN_RE = re.compile(r"<!(/?)([^>]+)>")


def number_sign_indices(cells: str) -> list[int]:
    """셀열에서 **수표로 볼 수 있는** ⠼ 위치 목록 (뒤에 숫자 셀이 오는 것만)."""
    out: list[int] = []
    i = cells.find(NUMBER_SIGN)
    while i != -1:
        if i + 1 < len(cells) and cells[i + 1] in _DIGIT_CELLS:
            out.append(i)
        i = cells.find(NUMBER_SIGN, i + 1)
    return out


def contraction_lookalikes(source: str) -> int:
    """원문의 영어 낱말이 만들어 낼 **수표 모양 ble ⠼** 개수.

    `number_sign_indices`가 못 거르는 잔여(-bled·-bler처럼 ble 뒤 글자가 a~j인 낱말)의
    개수다. eng_braille로 실제 점역해 세므로 약자표가 바뀌면 자동으로 따라간다.
    """
    clean = _TAG_TOKEN_RE.sub("", source or "")
    return sum(len(number_sign_indices(translate_word(w))) for w in iter_words(clean))


def has_number_sign(source: str, cells: str) -> bool:
    """이 요소 점자에 진짜 수표가 하나라도 있는가 (C5 런타임 스캐너용).

    영어 약자가 만든 ⠼는 빼고 센다 — 안 그러면 `possible`의 ⠼가 스캐너를 대신
    만족시켜 진짜 수표 누락을 못 잡는다.
    """
    return len(number_sign_indices(cells)) > contraction_lookalikes(source)
