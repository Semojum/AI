"""PART 8-2 — 만화/그림 점역 최적화 (HyperCLOVA X SEED Think 14B INT4, GPU 1).

GPT-4o 캡션 (말풍선·컷 순서) → HyperCLOVA X → 점역사주 TN 최적화
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
    rule_id="KBR-6.4.2",
    source="점자 교과서 제작 지침",
    section="6.4.2",
    title="만화·그림 점역사주 원칙",
    excerpt="만화는 컷 순서, 등장인물, 대화 내용을 순서대로 기술한다.",
    priority="primary",
)]

_PROMPT = """당신은 시각장애 학생용 점자 교과서 점역 전문가입니다.
다음 만화/그림 설명을 점역자 주([점역사주])로 최적화하세요.

## 만화 점역자 주 형식 (점자 자료 제작 지침 §5.3)
- "[점역사주] 만화: 장면구성" 형식으로 작성
- [점역사주]로 시작 (필수)

## 장면 기술 원칙 (§5.3.1~5.3.3)
- 여러 장면: "장면 1." "장면 2." 순서대로 번호 명시 필수
- 인물 대화: "인물명: 대사내용" 형식, 쌍점(:)으로 구분
- 인물 행동·표정: "인물명: (행동 설명)" 괄호 사용, 객관적 묘사
- 화자 불명: "말풍선: 내용" 으로 표기
- 한 장면 만화: 장면 설정 설명 추가, "장면 1." 생략 가능
- 전체 최대 3문장

## 금지 사항
- 대화 내용에 따옴표(" ") 사용 금지
- 등장인물 감정 주관적 해석 금지 (표정·행동 객관적 묘사만)
- 원본에 없는 인물명·대화 추가 금지
- 장면 번호 없이 여러 장면 뒤섞기 금지

## 출력 예시
입력: "두 컷 만화. 첫째 컷: 선생님이 학생에게 오늘 준비됐냐고 묻는다. 둘째 컷: 학생이 고개를 끄덕이며 웃는다."
출력: [점역사주] 만화: 장면 1. 선생님: 오늘 준비됐나요? 장면 2. 학생: (고개를 끄덕이며 웃음)

원본 설명:
{caption}

최적화된 점역자 주만 반환하세요. 다른 설명 없이 [점역사주]로 시작하는 문장만."""


def _hcxt_generate_sync(prompt: str, max_new_tokens: int = 300) -> str:
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
        logger.warning("HyperCLOVA X 만화 최적화 타임아웃 (%.0fs)", timeout)
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
                max_tokens=300,
                temperature=0.0,
            ),
            timeout=_FALLBACK_TIMEOUT,
        )
        return resp.choices[0].message.content.strip()
    except Exception as exc:
        logger.error("FALLBACK 만화 최적화 실패: %s", exc)
        return caption


class CartoonOpt:
    """ExtractedContent 목록 → LLMOutput 목록 (만화)."""

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
                corrected_text="[처리 불가: 만화 캡션 없음]",
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
                logger.warning("HyperCLOVA X 만화 실패 #%d id=%s: %s", fail_count, ext.element_id, exc)
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
