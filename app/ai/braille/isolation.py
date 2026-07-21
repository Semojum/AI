"""체인 내부 요소 격리.

6개 점역 모듈의 translate는 요소 목록을 순회한다. 한 요소의 점역이 예외를 던지면
(예: braillify가 거부하는 문자) 같은 체인의 다른 요소까지 모두 잃는 구조였다 —
6-체인 단위 gather 격리(`return_exceptions=True`)는 있으나 체인 *내부* 격리는 없었다.
safe_translate는 요소별로 예외를 가두고, 실패한 요소만 `[처리 불가]` placeholder로
대체한다(불변 규칙 1: 빈 결과 금지). 다른 요소는 정상 점역된다.

★ 예외 없는 소실도 같이 막는다(2026-07-21). 점역 경로는 변환 못 하는 글자를 조용히
  버리는 폴백을 여러 겹 갖고 있어(translator._safe_to_unicode), 원문이 통째로 미지
  글자면 **예외 없이 빈 문자열**이 나온다. 전 코퍼스 실측 63요소가 이 경로였고,
  페이지에 구멍이 난 채로 나갔다. 예외가 안 났으니 위 격리도 안 걸렸다.
"""

from __future__ import annotations

import logging
import re
from typing import Callable, Iterable

from app.ai.braille.regulations import make_rule
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
            out = translate_one(opt)
        except Exception as exc:  # noqa: BLE001 — 요소 격리(한 요소 실패가 체인 전체를 막지 않음)
            logger.warning(
                "요소 점역 실패(격리) id=%s: %s: %s",
                getattr(opt, "element_id", "?"), type(exc).__name__, exc,
            )
            results.append(_placeholder(opt))
            continue
        lost = _w2c_lost_source(opt, out)
        if lost is not None:
            logger.warning(
                "요소 점역 소실(무예외) id=%s: 원문 %r → 점자 0셀",
                getattr(opt, "element_id", "?"), lost[:30],
            )
            out = _placeholder(opt, f"점역 불가 문자 {lost[:12]}")
        results.append(out)
    return results


# 내용 없음 판정 — 공백·점자 빈칸(⠀ U+2800)·제어문자는 '내용'이 아니다.
# ⚠ 제어문자를 빼먹으면 원문이 \x00 하나뿐인 요소(추출기가 남기는 빈 블록, 실측 10건)를
#   '내용 있음'으로 보고 멀쩡한 빈칸 출력을 placeholder로 덮어쓴다.
_W2C_BLANK_RE = re.compile(r"[\s\x00-\x1f\x7f-\x9f⠀]+")


def _w2c_empty(text) -> bool:
    if isinstance(text, str):
        return not _W2C_BLANK_RE.sub("", text)
    return not any(_W2C_BLANK_RE.sub("", ln or "") for ln in (text or []))


def _w2c_lost_source(opt: LLMOutput, out: BrailleOutput) -> str | None:
    """원문은 있는데 출력이 비었으면 그 원문을 돌려준다(아니면 None).

    판정은 **불변 규칙 1 그대로 '빈 결과'**만 본다(점자 셀 유무가 아니라). 점자가 아닌
    줄도 정당한 출력이 있다 — placeholder 리터럴이 그렇고, 그걸 다시 placeholder로
    덮으면 사유가 지워진다.
    시각자료는 선택 초안이 비어도 다른 초안에 내용이 있으면 소실이 아니므로 함께 본다.
    원문이 애초에 공백뿐이면(구분용 빈 요소) 소실이 아니다.
    """
    src = (opt.corrected_text or "") or (opt.tn_text or "")
    if _w2c_empty(src):
        return None
    if not _w2c_empty(out.braille_lines):
        return None
    for d in out.drafts or []:
        if not _w2c_empty(d.braille_lines):
            return None
    return src.strip()


def _placeholder(opt: LLMOutput, reason: str = "점역 오류") -> BrailleOutput:
    """실패 요소 → [처리 불가] (placeholder 관례 = 리터럴 줄, 비어있지 않게).

    불변 규칙 2(rule_trail 필수): 실패 요소도 포괄 규정(KBR-0.1)을 달아 응답 계약을 지킨다.
    사유에 원문 조각을 실어 점역사가 무엇이 빠졌는지 바로 보게 한다. quality_checker가
    "[처리 불가" 접두로 C2를 올리므로 접두는 바꾸지 않는다.
    """
    return BrailleOutput(
        element_id=opt.element_id,
        braille_lines=[f"[처리 불가: {reason}]"],
        rule_trail=[make_rule("KBR-0.1")],
    )
