"""도형 반복 틀 역규칙 + 본문 충돌 기호 제거 회귀 가드.

이 파일이 지키는 것: `⠸ + 같은 셀 xN + ⠇` 를 도형 N개로 읽는 것.
종전에는 `⠸⠶⠶⠇` 가 `⟨2838⟩≡사`(미지셀 ⠸ + ⠶⠶=≡ + ⠇=사)로 깨졌다. 정방향은 이 틀을
이미 내는데(translator._box_blank_repl · _HIDDEN_X_RUN_RE) 역맵에 반복 규칙만 없었다.

**순환검증 금지**: 기대값은 「한국 점자 규정」 제57·58항 **예문 자체**다(규정_텍스트.txt
2506~2532행). 예문의 점자를 그대로 넣어 묵자가 그대로 나오는지 본다.
  제57항 숨김표  김○○ 씨 `@o5_00l ,,o` · 이 ×××야! `o _xxxl>6` · △△도서관 `_++liu,s@v3`
  제57항 [붙임]  제1~3 점역자 정의 숨김표 `_9l`·`_5l`·`_ol` (☆·◇·◆)
  제58항 빠짐표  □□□의 석 자다. `_777lw ,? .i4`
어느 글자로 펴는지는 코퍼스 실측으로 갈랐다 — 쪽 안 등장 순서로 짝지어
⠴=○ 117/123 · ⠶=□ 36/39 · ⠬=△ 24/27 · ⠢=◇ 17/17 · ⠭=× 15/15.
"""
from __future__ import annotations

import pytest

from app.utils.braille_ascii import ascii_to_unicode
from app.utils.braille_back import decode


@pytest.mark.parametrize("brf, expected", [
    ("@o5_00l`,,o", "김○○ 씨"),          # 제57항 숨김표 ○
    ("o`_xxxl>6", "이 ×××야!"),           # 제57항 숨김표 × (끝의 ⠖ 는 느낌표)
    ("_++liu,s@v3", "△△도서관"),          # 제57항 숨김표 △
    ("_777lw`,?`.i4", "□□□의 석 자다."),  # 제58항 빠짐표 □ (끝의 ⠲ 는 마침표)
])
def test_규정_예문_그대로_돌아온다(brf, expected):
    assert decode(ascii_to_unicode(brf, backtick="space")) == expected


@pytest.mark.parametrize("cells, expected", [
    ("⠸⠴⠇", "○"), ("⠸⠴⠴⠇", "○○"), ("⠸⠶⠶⠇", "□□"),
    ("⠸⠬⠬⠇", "△△"), ("⠸⠢⠢⠇", "◇◇"),
])
def test_도형_개수만큼_편다(cells, expected):
    assert decode(cells) == expected


def test_정의_숨김표_제1_제3은_아직_안_편다():
    """⠔(☆)·⠕(◆)는 실측이 각각 2건·3건뿐이고 ⠕ 는 규정 예시와 어긋난다.

    근거 없이 펴지 않고 미지셀로 남긴다 — 뜻이 책마다 다른 '점역자 정의' 자리다.
    """
    assert "☆" not in decode("⠸⠔⠔⠇")


@pytest.mark.parametrize("cells, expected", [
    ("⠲", "."),        # ∋ 였다 — 묵자 재추출 전수에 ∋ 0회, 마침표는 흔하다
    ("⠖", "!"),        # ∈ 였다 — 묵자에 ∈ 0회, `!` 2,596회
])
def test_본문에서_기호로_읽지_않는다(cells, expected):
    assert decode(cells) == expected
