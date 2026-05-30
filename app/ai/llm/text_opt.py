"""PART 4-2 — 텍스트 점역 최적화 (HyperCLOVA X SEED Think 14B INT4, GPU 1).

ZERO     → LLM 호출 없음 (텍스트 그대로 반환)
STANDARD → HyperCLOVA X, 15초 제한
QUALITY  → HyperCLOVA X, 30초 제한
FALLBACK → GPT-5.x/o3 API, 45초 제한 (3회 연속 실패 후)
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Optional
from uuid import UUID

from app.ai.braille.regulations import make_rule
from app.core.config import config
from app.core.model_manager import model_manager
from app.schemas.content import ExtractedContent, LLMOutput, RuleApplication
from app.schemas.layout import LayoutResult

logger = logging.getLogger(__name__)

_STANDARD_TIMEOUT = 15.0
_QUALITY_TIMEOUT  = 30.0
_FALLBACK_TIMEOUT = 45.0

def _min_trail(text: str) -> list[RuleApplication]:
    """텍스트 점역 기본 원칙(KBR-0.1)을 태깅 텍스트 전체 범위로 emit."""
    return [make_rule("KBR-0.1", span_start=0, span_end=len(text))]

_PROMPT_STANDARD = """당신은 한국어 점역 전문가입니다.
다음 텍스트를 점역 직전 상태로 교정하세요.

규칙:
1. 확실한 맞춤법 오류만 교정 (추측 교정 금지)
2. 특수문자·수식·수치는 그대로 유지
3. 줄바꿈과 원문 구조 유지

텍스트:
{text}

교정된 텍스트만 반환하세요."""

_PROMPT_QUALITY = """당신은 한국어 점역 전문가입니다.
다음 텍스트를 점역 직전 상태로 정확히 교정하세요.

OCR 신뢰도: {ocr_confidence:.2f}
원문:
{text}

교정 지침:
1. OCR 오류를 문맥으로 추론하여 교정
2. 수식(LaTeX)은 원형 유지
3. [처리 불가: ...] 플레이스홀더는 그대로 유지

교정된 텍스트만 반환하세요."""


def _hcxt_generate_sync(prompt: str, max_new_tokens: int = 512) -> str:
    import torch
    model = model_manager.hcxt_model
    tokenizer = model_manager.hcxt_tokenizer
    inputs = tokenizer(prompt, return_tensors="pt").to("cuda:1")
    with torch.no_grad():
        out = model.generate(
            **inputs,
            max_new_tokens=max_new_tokens,
            do_sample=False,
            temperature=None,
            top_p=None,
            pad_token_id=tokenizer.eos_token_id,
        )
    generated = out[0][inputs["input_ids"].shape[1]:]
    return tokenizer.decode(generated, skip_special_tokens=True).strip()


async def _hcxt_optimize(text: str, ocr_confidence: float, timeout: float) -> str:
    if ocr_confidence >= config.ocr_confidence_threshold:
        prompt = _PROMPT_STANDARD.format(text=text)
    else:
        prompt = _PROMPT_QUALITY.format(text=text, ocr_confidence=ocr_confidence)
    try:
        return await asyncio.wait_for(
            asyncio.to_thread(_hcxt_generate_sync, prompt),
            timeout=timeout,
        )
    except asyncio.TimeoutError:
        logger.warning("HyperCLOVA X 타임아웃 (%.0fs)", timeout)
        raise


async def _fallback_optimize(text: str, ocr_confidence: float) -> str:
    if not config.openai_api_key:
        logger.error("FALLBACK: OPENAI_API_KEY 미설정")
        return text

    import openai
    client = openai.AsyncOpenAI(api_key=config.openai_api_key)
    try:
        resp = await asyncio.wait_for(
            client.chat.completions.create(
                model="gpt-4o",
                messages=[{"role": "user", "content": _PROMPT_QUALITY.format(
                    text=text, ocr_confidence=ocr_confidence
                )}],
                max_tokens=1024,
                temperature=0.0,
            ),
            timeout=_FALLBACK_TIMEOUT,
        )
        return resp.choices[0].message.content.strip()
    except Exception as exc:
        logger.error("FALLBACK API 실패: %s", exc)
        return text


class TextOpt:
    """ExtractedContent 목록 → LLMOutput 목록."""

    async def optimize(
        self,
        extracted: list[ExtractedContent],
        routing_tier: str,
        layout: Optional[LayoutResult] = None,
    ) -> list[LLMOutput]:
        tasks = [self._optimize_one(e, routing_tier) for e in extracted]
        return await asyncio.gather(*tasks)

    async def _optimize_one(
        self, ext: ExtractedContent, routing_tier: str
    ) -> LLMOutput:
        text = ext.corrected_text or ""
        start = time.monotonic()

        # ZERO Tier: LLM 호출 없음
        if routing_tier == "ZERO" or ext.ocr_confidence == 1.0:
            return LLMOutput(
                element_id=ext.element_id,
                corrected_text=text,
                render_mode="text_only",
                routing_tier="ZERO",
                processing_time_ms=0,
                rule_trail=_min_trail(text),
            )

        timeout = _QUALITY_TIMEOUT if ext.ocr_confidence < config.ocr_confidence_threshold else _STANDARD_TIMEOUT
        tier = "QUALITY" if ext.ocr_confidence < config.ocr_confidence_threshold else "STANDARD"

        fail_count = 0
        corrected = text
        while fail_count < 3:
            try:
                corrected = await _hcxt_optimize(text, ext.ocr_confidence, timeout)
                break
            except Exception as exc:
                fail_count += 1
                logger.warning("HyperCLOVA X 실패 #%d id=%s: %s", fail_count, ext.element_id, exc)
                if fail_count >= 3:
                    logger.warning("FALLBACK 전환 id=%s", ext.element_id)
                    corrected = await _fallback_optimize(text, ext.ocr_confidence)
                    tier = "FALLBACK"

        elapsed_ms = int((time.monotonic() - start) * 1000)
        return LLMOutput(
            element_id=ext.element_id,
            corrected_text=corrected or text,
            render_mode="text_only",
            routing_tier=tier,
            processing_time_ms=elapsed_ms,
            rule_trail=_min_trail(corrected or text),
        )
