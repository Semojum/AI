"""PART 9-2 — 차트/그래프 점역 최적화 (HyperCLOVA X SEED Think 14B INT4, GPU 1).

GPT-4o 캡션 (축 레이블·수치·경향) → HyperCLOVA X → 점역사주 TN 최적화
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
    """시각자료 유형별 점역(BBPG-3.2.2, 차트·그래프) — 요소 전체(line_no=-1)."""
    return [make_rule("BBPG-3.2.2")]

_PROMPT = """당신은 시각장애 학생용 점자 교과서 점역 전문가입니다.
다음 차트/그래프 설명을 점역자 주로, **서로 다른 3가지 방식**으로 각각 작성하세요.
(점자 자료 제작 지침 §6.4, 점역사 지침: 데이터가 많으면 표 변환이 가장 좋음)

## 3가지 방식 (반드시 표현이 다르게)
[방식1] 표 변환: 데이터를 "항목: 수치" 표 형태로 정리 (데이터 포인트가 많을 때 권장)
[방식2] 수학적 서술: 유형 + x축·y축의 범위·단위 + 주요 추세 1개를 문장으로
[방식3] 개조식 항목별: 항목별 수치를 위계 목록으로

## 공통 규칙
- 각 줄을 "[방식N] [점역사주] 그래프유형: 내용" 형식으로 (유형: 막대/꺾은선/비율/선/그림그래프/수직선 중)
- 수치는 **아라비아 숫자 원문 그대로** (변환·추가·누락 금지), 단위 명시(%, 명, 원, ℃ 등)
- 원본에 없는 수치·고유명사 추가 금지, 색상만 언급하고 수치 생략 금지
- 주요 추세는 가장 중요한 1개만

## 출력 예시
입력: "연도별 발행 권수 막대그래프. 2020년 980권, 2021년 1100권, 2022년 1240권, 2023년 1380권."
[방식1] [점역사주] 막대그래프: 연도별 발행 권수. 2020년: 980권, 2021년: 1100권, 2022년: 1240권, 2023년: 1380권.
[방식2] [점역사주] 막대그래프: 연도별 발행 권수. x축 2020~2023년, y축 권수. 980권에서 1380권으로 증가.
[방식3] [점역사주] 막대그래프: 연도별 발행 권수. - 2020년 980권 - 2021년 1100권 - 2022년 1240권 - 2023년 1380권.

원본 설명:
{caption}

[방식1]/[방식2]/[방식3] 세 줄만 반환하세요. 다른 설명 없이."""


def _verify_numbers(original: str, output: str) -> bool:
    """원본 캡션의 수치가 출력에 모두 존재하는지 확인 (환각 방지)."""
    import re
    nums_in  = set(re.findall(r"\d+(?:\.\d+)?", original))
    nums_out = set(re.findall(r"\d+(?:\.\d+)?", output))
    return nums_in.issubset(nums_out)


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
    from app.ai.llm.inference_lock import hcxt_lock
    prompt = _PROMPT.format(caption=caption)
    async with hcxt_lock():          # 단일 GPU 모델 추론 직렬화
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


# 초안 3안 방식 (stage4_complex.md 'T4-2 공통 규약' — 차트=표현 형식)
_CHART_METHODS = [
    ("narrative", "표 변환"),
    ("narrative", "수학적 서술"),
    ("narrative", "개조식"),
]


class ChartGraphOpt:
    """ExtractedContent 목록 → LLMOutput 목록 (차트/그래프). 3안 생성 + 수치 검증."""

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
                rule_trail=_min_trail("[처리 불가: 차트 캡션 없음]"),
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
                logger.warning("HyperCLOVA X 차트 실패 #%d id=%s: %s", fail_count, ext.element_id, exc)
                if fail_count >= 3:
                    logger.warning("FALLBACK 전환 id=%s", ext.element_id)
                    response = await _fallback_optimize(caption)
                    tier = "FALLBACK"

        drafts = parse_labeled_drafts(response, _CHART_METHODS)
        if not drafts:
            drafts = single_draft(response or caption[:120], "narrative", "수학적 서술")

        # 수치 그라운딩 검증 — 원본 수치가 누락된 초안이 있으면 R5(검토 필요)만 표시.
        # 초안을 원본으로 '덮어쓰지 않는다': 방식2(수학적 서술)는 추세 중심이라 의도적으로
        # 일부 수치를 생략하므로, 덮어쓰면 3안이 모두 원본으로 동일해진다(차별화 소실).
        # 환각/누락은 점역사가 R5 표시를 보고 검토·교정한다.
        if any(not _verify_numbers(caption, d.text) for d in drafts):
            logger.warning("수치 검증 경고 id=%s — 일부 초안에 원본 수치 누락 (R5)", ext.element_id)
            ext.flags = list(getattr(ext, "flags", [])) + ["R5"]

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
