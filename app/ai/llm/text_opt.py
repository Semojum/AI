"""PART 4-2 — 텍스트 점역 최적화 (HyperCLOVA X SEED Think 14B INT4, GPU 1).

ZERO     → LLM 호출 없음 (텍스트 그대로 반환)
STANDARD → HyperCLOVA X, 15초 제한
QUALITY  → HyperCLOVA X, 30초 제한
FALLBACK → GPT-5.x/o3 API, 45초 제한 (3회 연속 실패 후)
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
from typing import Optional

from app.ai.braille.regulations import make_rule
from app.core.config import config
from app.core.model_manager import model_manager
from app.schemas.content import ExtractedContent, LLMOutput, RuleApplication
from app.schemas.layout import LayoutResult

logger = logging.getLogger(__name__)

_STANDARD_TIMEOUT = 60.0   # 워밍업 후 bitsandbytes NF4 14B: ~15-25 tok/s, 100tok ≈ 5s + 여유
_QUALITY_TIMEOUT  = 90.0
_FALLBACK_TIMEOUT = 45.0

# GPU 추론 직렬화는 모든 opt가 공유하는 inference_lock.hcxt_lock()을 사용한다
# (text_opt 전용 세마포어 폐지 — 한 GPU 모델에 대해 전역 단일 추론 보장).

def _min_trail(text: str) -> list[RuleApplication]:
    """텍스트 점역 기본 원칙(KBR-0.1) — 요소 전체(line_no=-1, 포괄 규칙)."""
    return [make_rule("KBR-0.1")]

# QUALITY 티어(저신뢰 스캔)에서만 호출 — OCR 오류 교정. 프롬프트 잔재('신뢰도/입력/출력'
# 라벨)가 출력에 새지 않도록 라벨을 넣지 않고 결과만 받도록 지시한다(누출 버그 방지).
_PROMPT_QUALITY = """다음 텍스트의 OCR 오류(깨진 글자·잘못된 띄어쓰기·오인식)만 교정해 교정된 텍스트만 출력하세요. 설명·머리말·따옴표 없이 결과만.

{text}"""

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


def _hcxt_generate_sync(prompt: str, max_new_tokens: int = 256) -> str:
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
            use_cache=True,  # generation_config.json의 use_cache=false 오버라이드
        )
    generated = out[0][inputs["input_ids"].shape[1]:]
    return tokenizer.decode(generated, skip_special_tokens=True).strip()


async def _hcxt_optimize(text: str, ocr_confidence: float, timeout: float) -> str:
    # QUALITY(신뢰도<threshold)에서만 호출됨. 라벨 없는 프롬프트로 OCR 교정만 수행.
    prompt = _PROMPT_QUALITY.format(text=text)
    # 입력 텍스트 길이 기반 max_new_tokens: 한글 1자 ≈ 1~2토큰, 여유분 30% 추가
    max_new_tokens = min(512, max(64, int(len(text) * 1.3)))
    from app.ai.llm.inference_lock import hcxt_lock
    async with hcxt_lock():          # 단일 GPU 모델 추론 직렬화(전역 공유)
        try:
            raw = await asyncio.wait_for(
                asyncio.to_thread(_hcxt_generate_sync, prompt, max_new_tokens),
                timeout=timeout,
            )
            return _clean_output(raw)   # 프롬프트 잔재 제거
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

        timeout = _QUALITY_TIMEOUT
        tier = "QUALITY"

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
