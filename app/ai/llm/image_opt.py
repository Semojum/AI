"""PART 7-2 — 이미지 점역 최적화 (HyperCLOVA X SEED Think 14B INT4, GPU 1).

GPT-4o 캡션 → HyperCLOVA X → 점역사주 TN 최적화
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Optional

from app.ai.braille.regulations import make_rule
from app.ai.llm.draft_utils import parse_labeled_drafts, single_draft
from app.core.config import config
from app.core.model_manager import model_manager
from app.schemas.content import ExtractedContent, LLMOutput, RuleApplication
from app.schemas.layout import LayoutResult

logger = logging.getLogger(__name__)

_STANDARD_TIMEOUT = 15.0
_QUALITY_TIMEOUT  = 30.0
_FALLBACK_TIMEOUT = 45.0

def _min_trail(text: str) -> list[RuleApplication]:
    """시각자료 일반 사항(BBPG-3.2.1) — 요소 전체(line_no=-1)."""
    return [make_rule("BBPG-3.2.1")]

_PROMPT = """당신은 시각장애 학생용 점자 교과서 점역 전문가입니다.
다음 이미지 설명을 점역자 주로, **서로 다른 3가지 방식**으로 각각 작성하세요.
(점자 자료 제작 지침 §6.1·§6.3.4, 점역사 지침 기준)

## 3가지 방식 (반드시 초점이 다르게 — 거의 같으면 안 됨)
[방식1] 상황 중심: 무엇이 있고 무엇을 하는지(주요 객체·행위)를 객관적으로
[방식2] 위치 중심: 구성 요소의 공간 배치·위치 관계를 중심으로
[방식3] 요약: 핵심만 1~2문장으로 최대한 압축

## 공통 규칙
- 각 줄을 "[방식N] [점역사주] 시각자료유형: 설명문" 형식으로 (유형: 사진/그림/삽화/지도/도표/도형 중)
- 간결·객관 (주관적 형용사·분위기·작가 의도 추측 금지, 객관적 사실만)
- 원본에 없는 수치·고유명사 추가 금지, **이미지 내부 텍스트·레이블·수치는 원문 그대로** (변형 금지)
- 인물 지칭: 이름·성별이 없으면 성별 구분하지 말 것; 직업이 특정되면 '직업·나이·성별(또는 번호)' 순
- "그림은/이미지는"으로 시작 금지

## 출력 예시
입력: "교실에서 선생님이 칠판 앞에 서 있고 학생 3명이 앉아 듣고 있는 그림."
[방식1] [점역사주] 그림: 교실에서 선생님이 칠판 앞에 서서 설명하고, 학생 3명이 앉아 듣는다.
[방식2] [점역사주] 그림: 칠판 앞 가운데 선생님, 그 앞에 학생 3명이 나란히 앉아 있다.
[방식3] [점역사주] 그림: 교실 수업 장면. 선생님 1명, 학생 3명.

원본 설명:
{caption}

[방식1]/[방식2]/[방식3] 세 줄만, 각 줄을 `[방식N] [점역사주]`로 시작해 서로 다르게 작성하세요. 다른 설명 없이 3줄만."""


def _hcxt_generate_sync(prompt: str, max_new_tokens: int = 512) -> str:  # 3안 생성 — 토큰 여유
    import torch
    model = model_manager.hcxt_model
    tokenizer = model_manager.hcxt_tokenizer
    device = next(model.parameters()).device
    messages = [{"role": "user", "content": prompt}]
    inputs = tokenizer.apply_chat_template(
        messages,
        add_generation_prompt=True,
        skip_reasoning=True,
        return_dict=True,
        return_tensors="pt",
    ).to(device)
    with torch.no_grad():
        out = model.generate(
            **inputs,
            max_new_tokens=max_new_tokens,
            do_sample=False,
            pad_token_id=tokenizer.eos_token_id,
            stop_strings=["<|endofturn|>", "<|stop|>"],
            tokenizer=tokenizer,
            use_cache=True,
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


# 초안 3안 방식 (stage4_complex.md 'T4-2 공통 규약' — 이미지=설명 초점)
_IMAGE_METHODS = [
    ("narrative", "상황 중심"),
    ("narrative", "위치 중심"),
    ("narrative", "요약"),
]


class ImageOpt:
    """ExtractedContent 목록 → LLMOutput 목록 (이미지). 3안 생성."""

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
                rule_trail=_min_trail("[처리 불가: 이미지 캡션 없음]"),
            )

        # ZERO/FALLBACK 등 모델 미사용·실패 시 단일안으로 격리
        if routing_tier == "ZERO":
            drafts = single_draft(caption[:120], "narrative", "원본")
            return self._build(ext.element_id, drafts, "ZERO", 0)

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
                logger.warning("HyperCLOVA X 이미지 실패 #%d id=%s: %s", fail_count, ext.element_id, exc)
                if fail_count >= 3:
                    logger.warning("FALLBACK 전환 id=%s", ext.element_id)
                    response = await _fallback_optimize(caption)
                    tier = "FALLBACK"

        drafts = parse_labeled_drafts(response, _IMAGE_METHODS)
        if not drafts:  # 파싱 실패 → 응답(또는 원본 캡션) 단일안
            drafts = single_draft(response or caption[:120], "narrative", "상황 중심")

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
            rule_trail=_min_trail(drafts[0].text),
            drafts=drafts,
            selected_idx=0,
        )
