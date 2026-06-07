"""체인 내부 요소 격리.

6개 점역 모듈의 translate는 요소 목록을 순회한다. 한 요소의 점역이 예외를 던지면
(예: braillify가 거부하는 문자) 같은 체인의 다른 요소까지 모두 잃는 구조였다 —
6-체인 단위 gather 격리(`return_exceptions=True`)는 있으나 체인 *내부* 격리는 없었다.
safe_translate는 요소별로 예외를 가두고, 실패한 요소만 `[처리 불가]` placeholder로
대체한다(불변 규칙 1: 빈 결과 금지). 다른 요소는 정상 점역된다.
"""

from __future__ import annotations

import logging
from typing import Callable, Iterable

from app.schemas.content import BrailleOutput, LLMOutput

logger = logging.getLogger(__name__)


def safe_translate(
    optimized: Iterable[LLMOutput],
    translate_one: Callable[[LLMOutput], BrailleOutput],
) -> list[BrailleOutput]:
    """요소별 격리 점역. translate_one(opt)이 던지면 그 요소만 placeholder로 대체."""
    results: list[BrailleOutput] = []
    for opt in optimized:
        try:
            results.append(translate_one(opt))
        except Exception as exc:  # noqa: BLE001 — 요소 격리(한 요소 실패가 체인 전체를 막지 않음)
            logger.warning(
                "요소 점역 실패(격리) id=%s: %s: %s",
                getattr(opt, "element_id", "?"), type(exc).__name__, exc,
            )
            results.append(_placeholder(opt))
    return results


def _placeholder(opt: LLMOutput) -> BrailleOutput:
    """실패 요소 → [처리 불가] (기존 placeholder 관례 = 리터럴 줄, 비어있지 않게)."""
    return BrailleOutput(
        element_id=opt.element_id,
        braille_lines=["[처리 불가: 점역 오류]"],
    )
