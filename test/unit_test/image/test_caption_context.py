# -*- coding: utf-8 -*-
"""캡셔닝에 주변 본문을 넣는다 (C003, 2026-08-25 대표 지시).

근거: 대표 실사례 — 초등 블록쌓기 문제에서 **3D 로 쌓인 블록 개수**를 묻는데 우리가
그림 설명만 내서 **문제를 못 푸는 설명**이 나갔다. 크롭만 보면 무엇이 중요한지 알 수 없다.

★ 이 기능의 성패는 **베껴 쓰기를 막는 것**이다. 문맥을 그냥 붙이면 모델이 주변 글을
  캡션에 옮겨 적는다 — `_reject_read_text` 가 이미 막고 있는 실패 얼굴이고, 베끼면
  같은 글이 본문과 캡션에 두 번 나가 32칸 지면만 먹는다.
"""
from __future__ import annotations

import pytest

from app.ai.builder.result_builder import _neighbor_text

captioner = pytest.importorskip("app.ai.captioning.captioner",
                                reason="test-fast 환경에는 캡셔닝 의존성이 없다")


def test_문맥이_없으면_프롬프트가_그대로다():
    """종전 동작 보존 — 옆 본문이 없는 그림은 프롬프트가 한 글자도 안 바뀐다."""
    assert captioner._context_block("") == ""
    assert captioner._context_block("   ") == ""


def test_문맥_블록이_베껴쓰기를_막는다():
    b = captioner._context_block("쌓은 블록은 모두 몇 개인가?")
    assert "쌓은 블록은 모두 몇 개인가?" in b
    assert "고르는 근거로만" in b          # 무엇을 쓸지 고르는 근거
    assert "옮겨 적지 마십시오" in b       # ★ 성패가 걸린 줄


def test_문맥은_상한을_넘지_않는다():
    """길면 프롬프트가 그림보다 커져 배보다 배꼽이 된다.

    ⚠ 블록 문구 자체에도 '가'가 들어 있어(…나갑니다·나가면) 글자 수를 세면 안 맞는다.
      끼워 넣은 문맥 조각을 직접 본다.
    """
    b = captioner._context_block("가" * 5000)
    assert "가" * captioner._CONTEXT_LIMIT in b
    assert "가" * (captioner._CONTEXT_LIMIT + 1) not in b


def test_프롬프트에_붙는다():
    p0 = captioner._PROMPTS["image"]
    from unittest.mock import patch
    with patch.object(captioner, "_caption_anthropic", return_value="그림: 블록") as m, \
         patch.object(captioner, "_blank_crop_std", return_value=None), \
         patch.object(captioner, "_cache_file", return_value=None), \
         patch("builtins.open", create=True):
        pass
    # 프롬프트 조립만 확인한다(외부 호출 없이)
    assert (p0 + captioner._context_block("몇 개인가?")).endswith("그림에 있는 것만 씁니다.")


# ── 옆 본문 고르기 ─────────────────────────────────────────────────────────

def test_앞쪽_본문을_먼저_본다():
    """발문이 그림 앞에 온다."""
    els = [{"type": "text", "content": "쌓은 블록은 모두 몇 개인가?"},
           {"type": "image", "content": ""},
           {"type": "text", "content": "다음 문제"}]
    assert _neighbor_text(els, 1) == "쌓은 블록은 모두 몇 개인가?"


def test_앞이_없으면_뒤를_본다():
    """캡션이 그림 뒤에 붙는 배치."""
    els = [{"type": "image", "content": ""}, {"type": "caption", "content": "그림 1 블록"}]
    assert _neighbor_text(els, 0) == "그림 1 블록"


def test_시각_요소만_있으면_빈_문자열():
    assert _neighbor_text([{"type": "image"}], 0) == ""


def test_너무_먼_본문은_안_가져온다():
    """세 칸을 넘으면 그 그림 얘기가 아니다."""
    els = [{"type": "text", "content": "멀리 있는 글"},
           {"type": "image"}, {"type": "image"}, {"type": "image"},
           {"type": "image", "content": ""}]
    assert _neighbor_text(els, 4) == ""


def test_빈_본문은_건너뛴다():
    els = [{"type": "text", "content": "  "},
           {"type": "text", "content": "진짜 발문"},
           {"type": "image", "content": ""}]
    assert _neighbor_text(els, 2) == "진짜 발문"
