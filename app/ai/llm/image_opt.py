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
_QUALITY_TIMEOUT  = 60.0   # 3안 생성은 단일 교정보다 오래 걸림(느린 GPU 여유)
_FALLBACK_TIMEOUT = 45.0

def _min_trail(text: str) -> list[RuleApplication]:
    """시각자료 일반 사항(BBPG-3.2.1) — 요소 전체(line_no=-1)."""
    return [make_rule("BBPG-3.2.1")]

# 답변을 `[방식1] [점역사주] `로 프리필(_PREFILL)해 포맷을 강제 → Think 모델의 장황한 추론을
# 건너뛰고 곧바로 3안을 생성한다(Stage5 실험에서 채택된 방식). 프롬프트는 간결하게 유지.
_PREFILL = "[방식1] [점역사주] "

_PROMPT = """당신은 시각장애 학생용 점자 교과서 점역 전문가입니다.
다음 그림을 점역자 주로 **서로 다른 3가지 방식**으로 작성하세요.
[방식1] 상황 중심: 무엇이 있고 무엇을 하는지(주요 객체·행위)
[방식2] 위치 중심: 구성 요소의 공간 배치·위치 관계
[방식3] 요약: 핵심만 1문장으로 압축

규칙: 객관적 사실만(추측·분위기·작가 의도 금지), 간결하게, "그림은/이미지는"으로 시작 금지,
원본에 없는 수치·고유명사 추가 금지(이미지 내 텍스트·수치는 원문 그대로),
인물은 이름·성별이 없으면 성별 구분 금지(직업 특정 시 '직업·나이·성별' 순).
각 줄 형식: 예) [방식1] [점역사주] 그림: 원 안에 …  — [점역사주] 뒤에 자료유형(사진/그림/삽화/지도/도표/도형)과 설명을 적고, 방식 이름은 본문에 쓰지 말 것.
다른 말 없이 정확히 3줄만.

그림: {caption}"""


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
    if prefill:  # 답변 시작을 강제(포맷 고정 → 추론 람블 방지)
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
