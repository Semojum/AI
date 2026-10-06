"""영어 교재 역점역 — 빈칸 ⠨⠤ · 문맥 번짐 가드 · 점자 쪽 머리줄.

영어 줄 넷은 EBS-E26-006 body p0117 gold 그대로다(로마자표 없는 영어 지문, 제29항 [다만]).
"""
import re

import pytest

from app.utils import braille_back as B
from app.utils.braille_back import decode

_ENG = [
    "⠠⠞⠑⠞⠇⠕⠉⠅⠀⠑⠭⠁⠍⠔⠫⠀⠮⠀⠎⠏⠑⠑⠡⠑⠎⠀⠍⠁⠙⠑",
    "⠃⠽⠀⠏⠕⠇⠊⠉⠽⠍⠁⠅⠻⠎⠀⠔⠧⠕⠇⠧⠫⠀⠔",
    "⠇⠂⠙⠻⠎⠀⠷⠞⠢⠀⠋⠁⠇⠇⠀⠃⠁⠉⠅⠀⠕⠝⠀⠕⠧⠻⠇⠽",
    "⠎⠊⠍⠏⠇⠊⠋⠊⠫⠀⠊⠍⠁⠛⠑⠎⠀⠷⠀⠮⠀⠸⠺⠲⠀⠠⠙⠥⠗⠬⠀⠮",
    "⠠⠉⠕⠇⠙⠀⠠⠺⠜⠀⠆⠞⠀⠮⠀⠠⠥⠝⠊⠞⠫⠀⠠⠌⠁⠞⠑⠎⠀⠯⠀⠮",
    "⠎⠊⠍⠏⠇⠑⠀⠊⠍⠁⠛⠑⠎⠀⠷⠀⠮⠀⠒⠋⠇⠊⠉⠞⠀⠶",
]


@pytest.mark.parametrize("br, want", [
    # EBS-E26-006 body p0087 — 빈칸 채우기 보기
    ("⠨⠤⠀⠊⠎⠀⠓⠊⠣⠇⠊⠣⠞⠫⠀⠔⠀⠁⠀⠌⠥⠙⠽", "___ is highlighted in a study"),
    # ES-REF-T26-007 body p0018 — 로마자표로 연 줄, 마침표가 붙은 빈칸
    ("⠀⠀⠴⠠⠞⠓⠊⠎⠀⠊⠎⠀⠁⠀⠨⠤⠲", "  This is a ___."),
])
def test_빈칸이_영어_줄을_막지_않는다(br, want):
    assert decode(br) == want


def test_문맥_번짐이_한국어_문장을_뒤집지_않는다(monkeypatch):
    page = "\n".join(_ENG[:3] + ["⠠⠠⠪⠠⠕⠥⠲"] + _ENG[3:])       # 쓰시오.
    assert decode(page).split("\n")[3] == "쓰시오."
    monkeypatch.setattr(B, "_CTX_KIWI_GUARD", False)              # 가드가 없으면 `OWOU.`
    assert decode(page).split("\n")[3] == "OWOU."


def test_로마자표_머리줄은_문맥_영어가_안_된다(monkeypatch):
    head = "⠉⠼⠁⠋⠋⠀⠀⠀⠴⠠⠐⠏⠀⠠⠠⠊⠊⠲⠀⠀⠼⠃⠚⠀⠀⠀⠀⠀⠼⠉⠛⠑"        # 점자 쪽 · 단원 · 묵자 쪽
    page = "\n".join(_ENG + [head])
    assert decode(page).split("\n")[-1] == "c166   Part II  20     375"
    monkeypatch.setattr(B, "_BRAILLE_PAGE_HEAD_RE", re.compile("(?!x)x"))
    assert decode(page).split("\n")[-1] == "c166   Part Ⅱ.  20     375"
