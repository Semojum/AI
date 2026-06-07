"""PART 4-2 — 텍스트 점역 최적화 (HyperCLOVA X SEED Think 14B INT4, GPU 1).

ZERO     → LLM 호출 없음 (텍스트 그대로 반환)
STANDARD → LLM 호출 없음 (OCR 품질 충분 — 교정 불필요)
QUALITY  → HyperCLOVA X, 90초 제한 (저신뢰 스캔 OCR 오류 교정만)
FALLBACK → GPT-4o API, 45초 제한 (3회 연속 실패 후)

공통 추론·폴백·재시도는 base_opt — 여기서는 텍스트에 최적화된 프롬프트·후처리만 정의한다.
추출 텍스트는 rule-based로 그대로 옮기는 것이 원칙이므로, LLM은 저신뢰 스캔의 OCR 오류
교정에만 개입한다(내용 재작성·교정 금지).
"""

from __future__ import annotations

import logging
import re
import time

from app.ai.braille.regulations import make_rule
from app.ai.llm.base_opt import BaseOpt, generate_with_retry
from app.core.config import config
from app.core.model_manager import model_manager  # noqa: F401 (단위 테스트가 이 네임스페이스를 patch)
from app.schemas.content import ExtractedContent, LLMOutput, RuleApplication

logger = logging.getLogger(__name__)

_QUALITY_TIMEOUT = 90.0


def _min_trail(text: str) -> list[RuleApplication]:
    """텍스트 점역 기본 원칙(KBR-0.1) — 요소 전체(line_no=-1, 포괄 규칙)."""
    return [make_rule("KBR-0.1")]

# QUALITY 티어(저신뢰 스캔)에서만 호출 — OCR 오류 교정. 프롬프트 잔재('신뢰도/입력/출력'
# 라벨)가 출력에 새지 않도록 라벨을 넣지 않고 결과만 받도록 지시한다(누출 버그 방지).
_PROMPT_QUALITY = """다음 텍스트의 OCR 오류(깨진 글자·잘못된 띄어쓰기·오인식)만 교정해 교정된 텍스트만 출력하세요. 설명·머리말·따옴표 없이 결과만.

{text}"""

# 답변을 `교정된 텍스트: `로 프리필 — Think 모델이 "원본 텍스트에서 오류를 발견했습니다…" 식
# 설명을 늘어놓지 않고 곧바로 교정문을 내도록 시작을 강제(시각 opt 프리필과 동일 기법).
# 프리필 스캐폴드는 _extract에서 제거하므로 최종 출력엔 라벨이 남지 않는다.
_PREFILL = "교정된 텍스트: "

# 모델이 프롬프트 라벨을 복창한 경우 선두에서 제거(방어적 후처리).
_ARTIFACT_RE = re.compile(r"^\s*(신뢰도|입력|출력|교정(된)?\s*텍스트|결과)\s*[:：].*$")


def _clean_output(text: str) -> str:
    """LLM 출력에서 프롬프트 잔재(선두 라벨 줄)·감싼 따옴표 제거."""
    raw = text or ""
    lines = raw.splitlines()
    while lines and (not lines[0].strip() or _ARTIFACT_RE.match(lines[0])):
        lines.pop(0)
    cleaned = "\n".join(lines).strip().strip("\"'`「」“”").strip()
    return cleaned or raw.strip()


def _extract(resp: str) -> str:
    """프리필 스캐폴드 제거 + 첫 문단만 취해(설명 꼬리 차단) 교정문을 뽑는다."""
    t = resp[len(_PREFILL):] if resp.startswith(_PREFILL) else resp
    t = _clean_output(t)
    return t.splitlines()[0].strip() if t.strip() else t


class TextOpt(BaseOpt):
    """ExtractedContent 목록 → LLMOutput 목록."""

    async def _optimize_one(self, ext: ExtractedContent, routing_tier: str) -> LLMOutput:
        text = ext.corrected_text or ""
        start = time.monotonic()

        # ZERO / STANDARD Tier: LLM 호출 없음 — 텍스트 원문 보존
        # STANDARD(신뢰도 ≥ threshold)는 OCR 품질이 충분해 교정 불필요.
        # HCXT는 QUALITY(신뢰도 < threshold, 저화질 스캔)에서만 호출.
        if routing_tier in ("ZERO", "STANDARD") or ext.ocr_confidence >= config.ocr_confidence_threshold:
            return LLMOutput(
                element_id=ext.element_id,
                corrected_text=text,
                render_mode="text_only",
                routing_tier=routing_tier if routing_tier in ("ZERO", "STANDARD") else "STANDARD",
                processing_time_ms=0,
                rule_trail=_min_trail(text),
            )

        # 입력 텍스트 길이 기반 max_new_tokens: 한글 1자 ≈ 1~2토큰, 여유분 30% 추가
        max_new_tokens = min(512, max(64, int(len(text) * 1.3)))
        response, used_fb = await generate_with_retry(
            _PROMPT_QUALITY.format(text=text),
            timeout=_QUALITY_TIMEOUT, element_id=ext.element_id, kind="텍스트",
            prefill=_PREFILL, max_new_tokens=max_new_tokens, fallback_max_tokens=1024,
            transform=_extract,
        )
        tier = "FALLBACK" if used_fb else "QUALITY"

        corrected = response or text
        elapsed_ms = int((time.monotonic() - start) * 1000)
        return LLMOutput(
            element_id=ext.element_id,
            corrected_text=corrected,
            render_mode="text_only",
            routing_tier=tier,
            processing_time_ms=elapsed_ms,
            rule_trail=_min_trail(corrected),
        )
