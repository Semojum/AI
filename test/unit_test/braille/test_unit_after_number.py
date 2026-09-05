# -*- coding: utf-8 -*-
"""숫자 뒤 단위표 — 역점역이 `%` 를 로마자로 읽어 뒤 한글까지 삼키던 문제.

규정 [붙임2]: 비로마자 단위 기호는 **숫자 + 단위표 0 + 기호**로 적는다(50%=⠼⠑⠚⠴⠏).
로마자표는 반대로 **런 앞**에 온다(제35항 A4=⠴⠠⠁⠼⠙ · MP3). 숫자 뒤에 붙는 ⠴ 를
로마자표로 읽을 자리가 규정에 없다.

가드가 없으면 종료표 ⠲ 가 마침표와 같은 셀이라 로마자 런이 뒤 한글까지 통째로 삼킨다.
실측(코퍼스 900쪽 표본): `%` 뒤가 한글인 줄 118건 중 69건(58%)이 깨졌다.
"""
from __future__ import annotations

import pytest

from app.ai.braille.translator import translate_tagged_text as T
from app.utils.braille_back import decode


@pytest.mark.parametrize("src", [
    "50%",
    "증가율은 50%이다.",
    "자녀가 정상일 확률은 25%이다.",
    "5%이므로",
    "25℃에서",
    "30°이다",
    "물가가 3%p 올랐다",
])
def test_숫자_뒤_단위는_왕복한다(src):
    assert decode(T(src)) == src


@pytest.mark.parametrize("src", ["A4용지", "MP3 파일", "pH 농도"])
def test_로마자표는_그대로_읽힌다(src):
    """⠴ 가 **런 앞**에 오는 자리는 종전대로 로마자다(제35항)."""
    assert decode(T(src)) == src


def test_퍼센트포인트가_역표에_있다():
    """규정 [붙임2] `%p` = `0pp` = ⠴⠏⠏. 정방향은 내는데 역표에 없어 `pp` 로 읽혔다."""
    assert T("%p") == "⠴⠏⠏"
    assert decode("⠼⠉⠴⠏⠏") == "3%p"


@pytest.mark.parametrize("src,want", [
    ("2n", "⠼⠃⠝"),            # 소문자 k~z — 셀이 숫자와 안 겹친다
    ("2P", "⠼⠃⠠⠏"),           # 대문자 — 대문자표 ⠠ 가 이미 가른다
    ("H2O", "⠠⠓⠼⠃⠠⠕"),        # 화학식(과학 점자 제7항 1호)
    ("12L", "⠼⠁⠃⠠⠇"),
])
def test_수_뒤_로마자에_헛칸이_안_붙는다(src, want):
    """「수학 점자」[다만]·[붙임] — 숫자와 로마자 사이를 띄우지 않는다.

    gold 실측(수 바로 뒤 로마자표·대문자표, 붙임:띄움) dev 445:28 · val 1,669:228.
    실물: 생물 val p142 `2n` → gold ⠤⠼⠃⠝⠤ · 외국어 val p113 `2P` → gold ⠠⠏⠼⠃⠠⠏.
    """
    assert T(src) == want


def test_소문자_a부터_j는_칸을_지킨다():
    """C5 방어 — 셀이 숫자와 겹치는 a~j 는 칸을 빼면 숫자로 읽힌다(⠼⠃⠑ = "25")."""
    assert T("2e") == "⠼⠃⠀⠑"
    assert T("3ab") == "⠼⠉⠀⠁⠃"
