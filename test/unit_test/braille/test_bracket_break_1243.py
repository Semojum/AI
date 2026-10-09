"""여는 괄호 · 따옴표 바로 뒤, 부호가 붙은 닫는 괄호 · 따옴표 앞은 끊을 자리가 아니다(이슈 #1243).

「한국 점자 규정」 제54항(재추출 2406행) 여는 따옴표와 여는 괄호 뒤, 닫는 따옴표와 닫는 괄호 앞은 붙여 쓴다.
#1240 이 문장 부호 앞을 막자 dev · val 응답 접기에서 `되었다(1861‖).` · `들리시나요?‖’,` · `영상(‖https://…` 이 골라졌다.
뒤가 빈칸인 닫는 괄호 앞(`(1861‖) 한편`)은 종전대로 둔다(수식 줄 강제분리, `_NO_BREAK_BEFORE` 의 까닭).
"""
from __future__ import annotations

import pytest

from app.ai.braille.translator import _break_offsets, translate_tagged_text


def _cut_before(src: str, head: str) -> bool:
    """`src` 를 점역한 줄에서 `head` 뒤(그 다음 글자 앞)가 끊을 자리인가."""
    return len(translate_tagged_text(head)) in _break_offsets(src, translate_tagged_text(src))


BLOCKED = [
    ("수입되었다(1861). 한편", "수입되었다(1861"),        # 닫는 괄호 뒤 마침표
    ("잘 들리시나요?’, ‘네", "잘 들리시나요?"),           # 물음표 뒤 닫는 따옴표 뒤 쉼표
    ("어간 ‘얻-’, ‘솟-’", "어간 ‘얻-"),                  # 붙임표 뒤 닫는 따옴표 뒤 쉼표
    ("보여 주는 영상(https://q7rx.kr)", "보여 주는 영상("),  # 여는 괄호 바로 뒤
    ("대립유전자(Aa, Bb)", "대립유전자("),
    ("“여러분! 시작이다.”라고", "“"),                    # 여는 따옴표 바로 뒤
]


@pytest.mark.parametrize("src,head", BLOCKED)
def test_괄호_붙여_쓰는_자리는_안_끊는다(src, head):
    assert not _cut_before(src, head)


@pytest.mark.parametrize("src,head", BLOCKED)
def test_스위치를_끄면_종전(monkeypatch, src, head):
    monkeypatch.setenv("BREAK_BRACKET_ATTACH", "0")
    assert _cut_before(src, head)


def test_뒤가_빈칸인_닫는_괄호_앞과_여는_괄호_앞은_그대로():
    assert _cut_before("수입되었다(1861) 한편", "수입되었다(1861")
    assert _cut_before("스며들다[스며 나오다]", "스며들다")
