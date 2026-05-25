"""PART 5-2 — 수식 점역 최적화 (HyperCLOVA X SEED Think 14B INT4, GPU 1).

ZERO     → LLM 호출 없음, LaTeX 정규화만 수행
STANDARD → HyperCLOVA X, 15초 제한
QUALITY  → HyperCLOVA X, 30초 제한
FALLBACK → GPT-4o API, 45초 제한 (3회 연속 실패 후)
"""

from __future__ import annotations

import asyncio
import logging
import re
import time

from app.core.config import config
from app.core.model_manager import model_manager
from app.schemas.content import ExtractedContent, LLMOutput, RuleApplication

logger = logging.getLogger(__name__)

_STANDARD_TIMEOUT = 15.0
_QUALITY_TIMEOUT  = 30.0
_FALLBACK_TIMEOUT = 45.0

_MIN_RULE_TRAIL = [RuleApplication(
    rule_id="KBR-5.1",
    source="한국 점자 규정",
    section="5.1",
    title="수학 점자 기본 원칙",
    excerpt="수학 기호는 수학 점자 규정에 따라 변환한다.",
    priority="primary",
)]

# stage3_complex.md T3-3: LaTeX 기호 → 유니코드 정규화 (LLM 교정 보조용)
# \\times / \\div / \\cdot 는 kor_math_rules에서 단일 처리 — 여기서 제거
_LATEX_NORMALIZE = [
    (r"\\alpha",  "α"),
    (r"\\beta",   "β"),
    (r"\\gamma",  "γ"),
    (r"\\delta",  "δ"),
    (r"\\theta",  "θ"),
    (r"\\pi",     "π"),
    (r"\\sigma",  "σ"),
    (r"\\omega",  "ω"),
    (r"\\infty",  "∞"),
    (r"\\in\b",   "∈"),
    (r"\\notin",  "∉"),
    (r"\\subset", "⊂"),
    (r"\\supset", "⊃"),
    (r"\\cup",    "∪"),
    (r"\\cap",    "∩"),
    (r"\\pm",     "±"),
    (r"\\leq",    "≤"),
    (r"\\geq",    "≥"),
    (r"\\neq",    "≠"),
    (r"\\approx", "≈"),
]

_PROMPT = """당신은 한국어 수학 점역 전문가입니다.
다음 LaTeX 수식을 점역 가능한 형태로 교정하세요.

규칙:
1. LaTeX 구조 유지 (\\frac, \\sqrt, ^, _ 등)
2. 불완전한 LaTeX 구문 복원
3. OCR 오인식 기호 교정 (예: O→0, l→1)
4. [처리 불가: ...] 플레이스홀더는 그대로 유지

LaTeX:
{latex}

교정된 LaTeX만 반환하세요."""


def _normalize(latex: str) -> str:
    for pattern, replacement in _LATEX_NORMALIZE:
        latex = re.sub(pattern, replacement, latex)
    return latex


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


async def _hcxt_optimize(latex: str, timeout: float) -> str:
    prompt = _PROMPT.format(latex=latex)
    try:
        return await asyncio.wait_for(
            asyncio.to_thread(_hcxt_generate_sync, prompt), timeout=timeout
        )
    except asyncio.TimeoutError:
        logger.warning("HyperCLOVA X 수식 최적화 타임아웃 (%.0fs)", timeout)
        raise


async def _fallback_optimize(latex: str) -> str:
    if not config.openai_api_key:
        logger.error("FALLBACK: OPENAI_API_KEY 미설정")
        return latex
    import openai
    client = openai.AsyncOpenAI(api_key=config.openai_api_key)
    try:
        resp = await asyncio.wait_for(
            client.chat.completions.create(
                model="gpt-4o",
                messages=[{"role": "user", "content": _PROMPT.format(latex=latex)}],
                max_tokens=512,
                temperature=0.0,
            ),
            timeout=_FALLBACK_TIMEOUT,
        )
        return resp.choices[0].message.content.strip()
    except Exception as exc:
        logger.error("FALLBACK 수식 최적화 실패: %s", exc)
        return latex


class FormulaOpt:
    """ExtractedContent 목록 → LLMOutput 목록 (수식)."""

    async def optimize(
        self,
        extracted: list[ExtractedContent],
        routing_tier: str,
    ) -> list[LLMOutput]:
        tasks = [self._optimize_one(e, routing_tier) for e in extracted]
        return await asyncio.gather(*tasks)

    async def _optimize_one(
        self, ext: ExtractedContent, routing_tier: str
    ) -> LLMOutput:
        raw = ext.latex_string or ext.corrected_text or ""
        start = time.monotonic()

        if "C3_FALLBACK" in ext.flags or not raw.strip():
            placeholder = "[수식 재확인 필요]" if raw.strip() else "[처리 불가: 수식 OCR 실패]"
            return LLMOutput(
                element_id=ext.element_id,
                corrected_text=placeholder,
                render_mode="formula_block",
                routing_tier="FALLBACK",
                processing_time_ms=0,
                rule_trail=list(_MIN_RULE_TRAIL),
            )

        render_mode = "formula_inline" if len(raw) <= 30 else "formula_block"

        if routing_tier == "ZERO":
            return LLMOutput(
                element_id=ext.element_id,
                corrected_text=_normalize(raw),
                render_mode=render_mode,
                routing_tier="ZERO",
                processing_time_ms=0,
                rule_trail=list(_MIN_RULE_TRAIL),
            )

        timeout = _QUALITY_TIMEOUT if ext.ocr_confidence < config.ocr_confidence_threshold else _STANDARD_TIMEOUT
        tier = "QUALITY" if ext.ocr_confidence < config.ocr_confidence_threshold else "STANDARD"

        fail_count = 0
        corrected = raw
        while fail_count < 3:
            try:
                corrected = await _hcxt_optimize(raw, timeout)
                break
            except Exception as exc:
                fail_count += 1
                logger.warning("HyperCLOVA X 수식 실패 #%d id=%s: %s", fail_count, ext.element_id, exc)
                if fail_count >= 3:
                    logger.warning("FALLBACK 전환 id=%s", ext.element_id)
                    corrected = await _fallback_optimize(raw)
                    tier = "FALLBACK"

        corrected = _normalize(corrected or raw)
        elapsed_ms = int((time.monotonic() - start) * 1000)
        return LLMOutput(
            element_id=ext.element_id,
            corrected_text=corrected,
            render_mode=render_mode,
            routing_tier=tier,
            processing_time_ms=elapsed_ms,
            rule_trail=list(_MIN_RULE_TRAIL),
        )
