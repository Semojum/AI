"""PART 8-2 — 만화/그림 점역 최적화 (HyperCLOVA X SEED Think 14B INT4, GPU 1).

GPT-4o 캡션 (말풍선·컷 순서) → HyperCLOVA X → 점역사주 TN 최적화
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Optional

from app.ai.llm.draft_utils import parse_labeled_drafts, single_draft
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
다음 만화/그림 설명을 점역자 주로, **서로 다른 3가지 방식**으로 각각 작성하세요.
(점자 자료 제작 지침 §5.3)

## 3가지 방식 (반드시 구성이 다르게)
[방식1] 장면+대사 통합: 장면 배경과 대사를 읽는 순서대로 함께 (기본)
[방식2] 대사 중심: "인물명: 대사" 위주로, 장면 설명은 최소화
[방식3] 장면별 개조식: "장면 1." "장면 2." 위계로 정리 (여러 장면일 때 특히)

## 공통 규칙
- 각 줄을 "[방식N] [점역사주] 만화: 내용" 형식으로
- 인물 대화는 "인물명: 대사" (쌍점 구분), 화자 불명은 "말풍선: 내용"
- **대사·말풍선 내부 텍스트는 원문 그대로** (요약·변형 금지), 따옴표("") 사용 금지
- 행동·표정은 "(객관 묘사)", 감정 주관 해석 금지
- 인물 지칭: 이름·성별 없으면 성별 구분하지 말 것; 직업 특정 시 '직업·나이·성별(또는 번호)'
- 원본에 없는 인물명·대화 추가 금지

## 출력 예시
입력: "두 컷 만화. 첫째 컷: 선생님이 오늘 준비됐냐고 묻는다. 둘째 컷: 학생이 고개를 끄덕이며 웃는다."
[방식1] [점역사주] 만화: 장면 1. 선생님: 오늘 준비됐나요? 장면 2. 학생: (고개를 끄덕이며 웃음)
[방식2] [점역사주] 만화: 선생님: 오늘 준비됐나요? 학생: (끄덕임)
[방식3] [점역사주] 만화: 장면 1. 선생님이 질문. 장면 2. 학생이 끄덕이며 웃음.

원본 설명:
{caption}

[방식1]/[방식2]/[방식3] 세 줄만 반환하세요. 다른 설명 없이."""


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


# 초안 3안 방식 (stage4_complex.md 'T4-2 공통 규약' — 만화=구성 방식)
_CARTOON_METHODS = [
    ("narrative", "장면+대사 통합"),
    ("narrative", "대사 중심"),
    ("narrative", "장면별 개조식"),
]


class CartoonOpt:
    """ExtractedContent 목록 → LLMOutput 목록 (만화). 3안 생성."""

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
            return self._build(ext.element_id, single_draft(caption[:120], "narrative", "원본"), "ZERO", 0)

        timeout = _QUALITY_TIMEOUT if ext.ocr_confidence < config.ocr_confidence_threshold else _STANDARD_TIMEOUT
        tier = "QUALITY" if ext.ocr_confidence < config.ocr_confidence_threshold else "STANDARD"

        fail_count = 0
        response = ""
        while fail_count < 3:
            try:
                response = await _hcxt_optimize(caption, timeout)
                break
            except Exception as exc:
                fail_count += 1
                logger.warning("HyperCLOVA X 만화 실패 #%d id=%s: %s", fail_count, ext.element_id, exc)
                if fail_count >= 3:
                    logger.warning("FALLBACK 전환 id=%s", ext.element_id)
                    response = await _fallback_optimize(caption)
                    tier = "FALLBACK"

        drafts = parse_labeled_drafts(response, _CARTOON_METHODS)
        if not drafts:
            drafts = single_draft(response or caption[:120], "narrative", "장면+대사 통합")

        elapsed_ms = int((time.monotonic() - start) * 1000)
        return self._build(ext.element_id, drafts, tier, elapsed_ms)

    @staticmethod
    def _build(element_id, drafts, tier, elapsed_ms) -> LLMOutput:
        return LLMOutput(
            element_id=element_id,
            corrected_text=drafts[0].text,
            render_mode=drafts[0].render_mode,
            tn_text=drafts[0].text,
            routing_tier=tier,
            processing_time_ms=elapsed_ms,
            rule_trail=list(_MIN_RULE_TRAIL),
            drafts=drafts,
            selected_idx=0,
        )
