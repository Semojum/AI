"""PART 8-2 — 만화/그림 점역 최적화 (HyperCLOVA X SEED Think 14B INT4, GPU 1).

GPT-4o 캡션 (말풍선·컷 순서) → HyperCLOVA X → 점역사주 TN 최적화
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
_QUALITY_TIMEOUT  = 60.0   # 3안 생성은 단일 교정보다 오래 걸림(느린 GPU 여유)
_FALLBACK_TIMEOUT = 45.0

def _min_trail(text: str) -> list[RuleApplication]:
    """시각자료 일반 사항(BBPG-3.2.1) — 요소 전체(line_no=-1)."""
    return [make_rule("BBPG-3.2.1")]

# 답변을 `[방식1] [점역사주] 만화: `로 프리필해 포맷+유형(만화)을 강제 → Think 모델의 추론 람블
# 건너뛰고 3안 생성(Stage5 실험에서 채택). 프롬프트는 간결하게.
_PREFILL = "[방식1] [점역사주] 만화: "

_PROMPT = """당신은 시각장애 학생용 점자 교과서 점역 전문가입니다.
다음 만화를 점역자 주로 **서로 다른 3가지 방식**으로 작성하세요.
[방식1] 장면+대사 통합: 장면 배경과 대사를 읽는 순서대로
[방식2] 대사 중심: "인물명: 대사" 위주, 장면 설명 최소화
[방식3] 장면별 개조식: "장면 1." "장면 2." 위계로 정리

규칙: 대사·말풍선 내부 텍스트는 원문 그대로(요약·변형·따옴표 금지), 화자 불명은 "말풍선: 내용",
행동·표정은 (객관 묘사), 감정 주관 해석 금지, 인물은 이름·성별 없으면 성별 구분 금지,
원본에 없는 인물명·대화 추가 금지.
각 줄 형식: 예) [방식1] [점역사주] 만화: 1장면. …  — [점역사주] 뒤에 '만화:'과 설명을 적고, 방식 이름은 본문에 쓰지 말 것.
다른 말 없이 정확히 3줄만.

만화: {caption}"""


def _hcxt_generate_sync(prompt: str, max_new_tokens: int = 512, prefill: str = "") -> str:
    import torch
    model = model_manager.hcxt_model
    tokenizer = model_manager.hcxt_tokenizer
    device = next(model.parameters()).device
    messages = [{"role": "user", "content": prompt}]
    enc = tokenizer.apply_chat_template(
        messages, add_generation_prompt=True, skip_reasoning=True,
        return_dict=True, return_tensors="pt",
    )
    input_ids = enc["input_ids"]
    if prefill:  # 답변 시작 강제(포맷 고정 → 추론 람블 방지)
        pf = tokenizer(prefill, return_tensors="pt", add_special_tokens=False)["input_ids"]
        input_ids = torch.cat([input_ids, pf], dim=1)
    input_ids = input_ids.to(device)
    with torch.no_grad():
        out = model.generate(
            input_ids=input_ids,
            attention_mask=torch.ones_like(input_ids),
            max_new_tokens=max_new_tokens,
            do_sample=False,
            pad_token_id=tokenizer.eos_token_id,
            stop_strings=["<|endofturn|>", "<|stop|>"],
            tokenizer=tokenizer,
            use_cache=True,
        )
    generated = tokenizer.decode(out[0][input_ids.shape[1]:], skip_special_tokens=True).strip()
    return (prefill + generated) if prefill else generated


async def _hcxt_optimize(caption: str, timeout: float) -> str:
    from app.ai.llm.inference_lock import hcxt_lock
    prompt = _PROMPT.format(caption=caption)
    async with hcxt_lock():          # 단일 GPU 모델 추론 직렬화
        try:
            return await asyncio.wait_for(
                asyncio.to_thread(_hcxt_generate_sync, prompt, 512, _PREFILL),
                timeout=timeout,
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
                rule_trail=_min_trail("[처리 불가: 만화 캡션 없음]"),
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
            rule_trail=_min_trail(drafts[0].text),
            drafts=drafts,
            selected_idx=0,
        )
