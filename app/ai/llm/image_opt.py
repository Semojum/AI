"""PART 7-2 — 이미지 점역 최적화 (HyperCLOVA X SEED Think 14B INT4, GPU 1).

GPT-4o 캡션 → HyperCLOVA X → 점역사주 TN 최적화
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Optional

from app.core.config import config
from app.core.model_manager import model_manager
from app.schemas.content import ExtractedContent, LLMOutput, RuleApplication
from app.schemas.layout import LayoutResult

logger = logging.getLogger(__name__)

_STANDARD_TIMEOUT = 15.0
_QUALITY_TIMEOUT  = 30.0
_FALLBACK_TIMEOUT = 45.0

_MIN_RULE_TRAIL = [RuleApplication(
    rule_id="KBR-6.4.1",
    source="점자 교과서 제작 지침",
    section="6.4.1",
    title="이미지 점역사주 원칙",
    excerpt="사진·삽화는 피사체, 배경, 주요 특징을 간결하게 기술한다.",
    priority="primary",
)]

_PROMPT = """당신은 시각장애 학생용 점자 교과서 점역 전문가입니다.
다음 이미지 설명을 점역자 주([점역사주])로 최적화하세요.

## 점역자 주 형식 (점자 자료 제작 지침 §6.3.4)
- 반드시 "[점역사주] 시각자료유형: 설명문" 형식으로 작성
- 유형 명시 필수 — 사진, 그림, 삽화, 지도, 도표, 도형 중 하나
- [점역사주]로 시작 (필수)

## 설명문 작성 원칙 (§6.1.4)
- 간결: 최소 단어로 핵심만, 점자 1줄(32칸) 이내 목표, 최대 2문장
- 단계적: 전체 윤곽(피사체+행위) → 세부 공간 관계 → 배경(필요 시만)
- 명료: 한 번 읽어도 이해 가능하도록
- 객관적: 주관적 형용사(아름다운, 인상적인) 대신 구체적 묘사(위치·수량·상태)

## 금지 사항
- 원본 설명에 없는 수치·고유명사 추가 금지
- "그림은", "이미지는" 으로 시작 금지
- 색상만 언급하고 형태/위치 생략 금지
- 수치는 아라비아 숫자 그대로 (변환 금지)

## 출력 예시
입력: "수소원자와 탄소원자 구조를 나란히 비교한 그림. 수소원자는 양성자 1개와 전자 1개, 탄소원자는 양성자 6개, 중성자 6개, 전자 6개."
출력: [점역사주] 그림: 수소원자와 탄소원자 구조 비교. 수소원자는 양성자 1개·전자 1개, 탄소원자는 양성자 6개·중성자 6개·전자 6개.

원본 설명:
{caption}

최적화된 점역자 주만 반환하세요. 다른 설명 없이 [점역사주]로 시작하는 문장만."""


def _hcxt_generate_sync(prompt: str, max_new_tokens: int = 256) -> str:
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


async def _hcxt_optimize(caption: str, timeout: float) -> str:
    prompt = _PROMPT.format(caption=caption)
    try:
        return await asyncio.wait_for(
            asyncio.to_thread(_hcxt_generate_sync, prompt), timeout=timeout
        )
    except asyncio.TimeoutError:
        logger.warning("HyperCLOVA X 이미지 최적화 타임아웃 (%.0fs)", timeout)
        raise


async def _fallback_optimize(caption: str) -> str:
    if not config.openai_api_key:
        logger.error("FALLBACK: OPENAI_API_KEY 미설정")
        return caption
    import openai
    client = openai.AsyncOpenAI(api_key=config.openai_api_key)
    try:
        resp = await asyncio.wait_for(
            client.chat.completions.create(
                model="gpt-4o",
                messages=[{"role": "user", "content": _PROMPT.format(caption=caption)}],
                max_tokens=256,
                temperature=0.0,
            ),
            timeout=_FALLBACK_TIMEOUT,
        )
        return resp.choices[0].message.content.strip()
    except Exception as exc:
        logger.error("FALLBACK 이미지 최적화 실패: %s", exc)
        return caption


class ImageOpt:
    """ExtractedContent 목록 → LLMOutput 목록 (이미지)."""

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
        caption = ext.corrected_text or ""
        start = time.monotonic()

        if not caption.strip():
            return LLMOutput(
                element_id=ext.element_id,
                corrected_text="[처리 불가: 이미지 캡션 없음]",
                render_mode="narrative",
                routing_tier="FALLBACK",
                processing_time_ms=0,
                rule_trail=list(_MIN_RULE_TRAIL),
            )

        if routing_tier == "ZERO":
            tn = f"[점역사주] {caption[:120]}"
            return LLMOutput(
                element_id=ext.element_id,
                corrected_text=caption,
                render_mode="narrative",
                tn_text=tn,
                routing_tier="ZERO",
                processing_time_ms=0,
                rule_trail=list(_MIN_RULE_TRAIL),
            )

        timeout = _QUALITY_TIMEOUT if ext.ocr_confidence < config.ocr_confidence_threshold else _STANDARD_TIMEOUT
        tier = "QUALITY" if ext.ocr_confidence < config.ocr_confidence_threshold else "STANDARD"

        fail_count = 0
        tn_text = caption
        while fail_count < 3:
            try:
                tn_text = await _hcxt_optimize(caption, timeout)
                break
            except Exception as exc:
                fail_count += 1
                logger.warning("HyperCLOVA X 이미지 실패 #%d id=%s: %s", fail_count, ext.element_id, exc)
                if fail_count >= 3:
                    logger.warning("FALLBACK 전환 id=%s", ext.element_id)
                    tn_text = await _fallback_optimize(caption)
                    tier = "FALLBACK"

        if not tn_text.startswith("[점역사주]"):
            tn_text = f"[점역사주] {tn_text}"

        elapsed_ms = int((time.monotonic() - start) * 1000)
        return LLMOutput(
            element_id=ext.element_id,
            corrected_text=caption,
            render_mode="narrative",
            tn_text=tn_text,
            routing_tier=tier,
            processing_time_ms=elapsed_ms,
            rule_trail=list(_MIN_RULE_TRAIL),
        )
