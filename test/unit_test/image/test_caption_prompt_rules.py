"""캡셔닝 요청·프롬프트 불변식 (2026-08-08 QA 16번).

두 가지를 고정한다. 둘 다 실측으로 잡은 것이라, 지우면 조용히 되돌아간다.

1. **사고(thinking)를 꺼서 호출한다.** `claude-sonnet-5`는 `thinking`을 안 주면 적응형
   사고가 기본이고, `max_tokens`는 사고+본문 합계 상한이다. 그래서 복잡한 그림에서
   500토큰을 사고가 다 먹고 **빈 캡션**이 돌아왔다 — 지침 예3-50(순서도) 실측:
   `stop_reason=max_tokens`, `thinking_tokens=499`, text 블록 0개.
   규정 정답 22건 중 3건(14%)이 이 경로였다.

2. **정답에서 뽑은 금지 어휘가 프롬프트에 남아 있다.** 「점자 도서 제작 지침」 3장 2절
   정답 24건에 색·음영어 1건(대사 인용), 장식·도형어 0건, 화면 위치어 0건, 메타서술
   0건이다. 이 넷을 금지하는 문장이 공통 프롬프트에서 빠지면 캡션이 다시 길어진다.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from app.ai.captioning import captioner


class _Block:
    type = "text"
    text = "그림: 확대경"


class TestThinkingDisabled:
    def test_anthropic_호출에_thinking_disabled가_붙는다(self) -> None:
        resp = MagicMock(content=[_Block()], usage=MagicMock(input_tokens=1, output_tokens=1))
        client = MagicMock()
        client.messages.create.return_value = resp
        with patch("anthropic.Anthropic", return_value=client), \
             patch("app.ai.captioning.captioner.llm_limiter", create=True), \
             patch("app.core.limits.llm_limiter"), \
             patch("app.utils.req_log.inc_gpt4o"):
            captioner._caption_anthropic("Zm9v", "image/png", "설명하세요")
        kwargs = client.messages.create.call_args.kwargs
        assert kwargs["thinking"] == {"type": "disabled"}, (
            "사고가 켜지면 max_tokens를 사고가 다 먹고 캡션이 빈 문자열로 돌아온다")


class TestGoldDerivedBans:
    """정답 실측에서 빈도 0(또는 1)이라 금지한 어휘가 공통 프롬프트에 남아 있는가."""

    @pytest.mark.parametrize("needle", ["색·음영", "도형·장식", "화면 위치", "보인다"])
    def test_공통_프롬프트에_금지_문장이_있다(self, needle: str) -> None:
        assert needle in captioner._COMMON

    def test_그래프는_추세를_쓰지_않는다(self) -> None:
        # 정답 그래프 6건(예3-32~3-36·3-45)에 추세 문장 0건.
        assert "추세" in captioner._PROMPTS["chart"] and "붙이지 마세요" in captioner._PROMPTS["chart"]

    def test_조직도는_화살표가_아니라_위계_번호다(self) -> None:
        # 정답 화살표 2/24건은 둘 다 과정 도식(예3-22·3-51). 조직도(예3-46)는 0개.
        assert "위계 번호" in captioner._PROMPTS["diagram"]

    def test_대상이_하나면_이름만_적는다(self) -> None:
        # 예3-26 '퍼킨스 점자 타자기' · 예3-90 '고추장찌개' · 예3-18 '파르테논 신전'.
        assert "이름만" in captioner._PROMPTS["image"]

    def test_만화_대본_형식은_그대로다(self) -> None:
        # 오늘 §5.3.3(3)로 고친 것 — 이번 변경이 되돌리지 않았는지 확인.
        p = captioner._PROMPTS["cartoon"]
        assert "장면 1" in p and "인물명: 대사" in p and "§5.3.3(2)" in p
