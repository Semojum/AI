"""PART 9-2 — 차트/그래프 점역 최적화 (HyperCLOVA X SEED Think 14B INT4, GPU 1).

GPT-4o 캡션 (축 레이블·수치·경향) → HyperCLOVA X → 점역사주 TN 최적화
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
    rule_id="KBR-6.4",
    source="점자 교과서 제작 지침",
    section="6.4",
    title="차트·그래프 점역사주 원칙",
    excerpt="그래프는 유형, 축 레이블, 수치 범위, 주요 경향을 포함하여 기술한다.",
    priority="primary",
)]

_PROMPT = """당신은 시각장애 학생용 점자 교과서 점역 전문가입니다.
다음 차트/그래프 설명을 점역자 주([점역사주])로 최적화하세요.

## 점역자 주 형식 (점자 자료 제작 지침 §6.3.4, §6.4)
- "[점역사주] 그래프유형: 내용" 형식으로 작성
- 유형 명시 필수 — 막대그래프, 꺾은선그래프, 비율그래프, 선그래프, 그림그래프, 수직선 중 하나
- [점역사주]로 시작 (필수)

## 유형별 기술 원칙 (§6.4)
- 비율그래프: 제목 + 전체 합계(있으면) + 항목별 레이블: 수치%
- 막대그래프: 제목 + 가로축(항목명) + 세로축(단위) + 주요 막대 수치
- 꺾은선그래프: 제목 + 축 정보 + 핵심 값 + 주요 추이(증가/감소/역전) 1개
- 선그래프: 제목 + x축·y축 + 절편·좌표 + 변수 간 관계
- 복잡하여 직접 기술 불가: "표로 대체하여 정리함" 명시

## 수치 규칙
- 수치는 아라비아 숫자 그대로 (100 → 백 변환 금지)
- 단위 반드시 명시 (%, 명, 원, ℃ 등)
- 원본 설명에 없는 수치·고유명사 추가 금지

## 금지 사항
- 주요 경향 2개 이상 나열 금지 (가장 중요한 1개만)
- 그래프 색상만 언급하고 수치 생략 금지

## 출력 예시
입력: "청일 전쟁 배상금 사용처 원형 그래프. 총 3억 6천만 엔. 군비 확장비 62%, 임시 군비 21.6%, 왕실 경비 5.5%, 기타 5.5%, 교육 기금 2.7%, 재해 준비금 2.7%."
출력: [점역사주] 비율그래프: 청일 전쟁 배상금 사용처(총 3억 6천만 엔). 군비 확장비 62%, 임시 군비 21.6%, 왕실 경비 5.5%, 기타 5.5%, 교육 기금 2.7%, 재해 준비금 2.7%.

원본 설명:
{caption}

최적화된 점역자 주만 반환하세요. 다른 설명 없이 [점역사주]로 시작하는 문장만."""


def _verify_numbers(original: str, output: str) -> bool:
    """원본 캡션의 수치가 출력에 모두 존재하는지 확인 (환각 방지)."""
    import re
    nums_in  = set(re.findall(r"\d+(?:\.\d+)?", original))
    nums_out = set(re.findall(r"\d+(?:\.\d+)?", output))
    return nums_in.issubset(nums_out)


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
        logger.warning("HyperCLOVA X 차트 최적화 타임아웃 (%.0fs)", timeout)
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
        logger.error("FALLBACK 차트 최적화 실패: %s", exc)
        return caption


class ChartGraphOpt:
    """ExtractedContent 목록 → LLMOutput 목록 (차트/그래프)."""

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
                corrected_text="[처리 불가: 차트 캡션 없음]",
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
                logger.warning("HyperCLOVA X 차트 실패 #%d id=%s: %s", fail_count, ext.element_id, exc)
                if fail_count >= 3:
                    logger.warning("FALLBACK 전환 id=%s", ext.element_id)
                    tn_text = await _fallback_optimize(caption)
                    tier = "FALLBACK"

        if not tn_text.startswith("[점역사주]"):
            tn_text = f"[점역사주] {tn_text}"

        # 수치 그라운딩 검증 — 원본 수치가 출력에 없으면 R5 플래그 + 원본 유지
        if not _verify_numbers(caption, tn_text):
            logger.warning("수치 검증 실패 id=%s — 원본 캡션 사용 (R5)", ext.element_id)
            tn_text = f"[점역사주] {caption}"
            ext.flags = list(getattr(ext, "flags", [])) + ["R5"]

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
