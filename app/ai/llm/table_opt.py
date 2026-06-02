"""PART 6-2 — 표 점역 최적화 (HyperCLOVA X SEED Think 14B INT4, GPU 1).

점역사주 복수 초안 생성 + render_mode 결정.
render_mode 우선순위: table_structure['render_mode'] → 행/열 수 기반 추론 → table_grid
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Optional

from app.ai.braille.regulations import make_rule
from app.ai.llm.draft_utils import ensure_tn_prefix
from app.core.config import config
from app.core.model_manager import model_manager
from app.schemas.content import ExtractedContent, LLMOutput, RuleApplication
from app.schemas.layout import LayoutResult

logger = logging.getLogger(__name__)

_STANDARD_TIMEOUT = 15.0
_QUALITY_TIMEOUT  = 30.0
_FALLBACK_TIMEOUT = 45.0

def _min_trail(text: str) -> list[RuleApplication]:
    """표 점역 일반 사항(BBPG-3.1.1) — 요소 전체(line_no=-1)."""
    return [make_rule("BBPG-3.1.1")]

_PROMPT_TABLE_GRID = """당신은 한국어 점역 전문가입니다.
다음 표 내용을 점역사주([점역사주])로 표현하는 2가지 방식을 제안하세요.

표 내용:
{table_text}

형식:
[방식1] [점역사주] ...
[방식2] [점역사주] ...

가장 적합한 방식 번호(1 또는 2)를 마지막 줄에 "선택: N" 형식으로 기재하세요."""

_PROMPT_IRREGULAR = """당신은 한국어 점역 전문가입니다.
다음 비정형 표 내용을 점역사주로 간결하게 표현하세요.

원문:
{text}

[점역사주]로 시작하는 설명 1문장만 반환하세요."""


def _table_to_text(table_structure: dict) -> str:
    """table_structure dict → 사람이 읽을 수 있는 텍스트."""
    cells: list[dict] = table_structure.get("cells", [])
    if not cells:
        return table_structure.get("text", "") or ""

    max_row = max((c.get("row", 0) for c in cells), default=0) + 1
    max_col = max((c.get("col", 0) for c in cells), default=0) + 1

    grid: list[list[str]] = [[""] * max_col for _ in range(max_row)]
    for cell in cells:
        r, c = cell.get("row", 0), cell.get("col", 0)
        if r < max_row and c < max_col:
            grid[r][c] = str(cell.get("text", ""))

    return "\n".join(" | ".join(row) for row in grid)


def _infer_render_mode(table_structure: Optional[dict]) -> str:
    if not table_structure:
        return "narrative"
    if rm := table_structure.get("render_mode"):
        return rm
    cells = table_structure.get("cells", [])
    if not cells:
        return "narrative"
    max_row = max((c.get("row", 0) for c in cells), default=0) + 1
    max_col = max((c.get("col", 0) for c in cells), default=0) + 1
    if max_col == 2:
        return "linear"
    if max_row == 1:
        return "transposed"
    return "table_grid"


def _hcxt_generate_sync(prompt: str, max_new_tokens: int = 512) -> str:
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


async def _hcxt_optimize(prompt: str, timeout: float) -> str:
    try:
        return await asyncio.wait_for(
            asyncio.to_thread(_hcxt_generate_sync, prompt), timeout=timeout
        )
    except asyncio.TimeoutError:
        logger.warning("HyperCLOVA X 표 최적화 타임아웃 (%.0fs)", timeout)
        raise


async def _fallback_optimize(prompt: str) -> str:
    if not config.openai_api_key:
        logger.error("FALLBACK: OPENAI_API_KEY 미설정")
        return ""
    import openai
    client = openai.AsyncOpenAI(api_key=config.openai_api_key)
    try:
        resp = await asyncio.wait_for(
            client.chat.completions.create(
                model="gpt-4o",
                messages=[{"role": "user", "content": prompt}],
                max_tokens=1024,
                temperature=0.0,
            ),
            timeout=_FALLBACK_TIMEOUT,
        )
        return resp.choices[0].message.content.strip()
    except Exception as exc:
        logger.error("FALLBACK 표 최적화 실패: %s", exc)
        return ""


def _parse_tn_from_response(response: str) -> str:
    """LLM 응답에서 [점역사주] 텍스트 추출. 선택된 방식 우선."""
    lines = [ln.strip() for ln in response.splitlines() if ln.strip()]
    selected_idx = None
    for ln in lines:
        if ln.startswith("선택:"):
            try:
                selected_idx = int(ln.split(":")[1].strip()) - 1
            except (ValueError, IndexError):
                pass

    drafts = [ln for ln in lines if "[점역사주]" in ln]
    if not drafts:
        # 응답 전체가 TN인 경우
        return response.strip() if response.strip() else "[처리 불가: 표 점역사주 생성 실패]"

    if selected_idx is not None and 0 <= selected_idx < len(drafts):
        return drafts[selected_idx]
    return drafts[0]


class TableOpt:
    """ExtractedContent 목록 → LLMOutput 목록 (표)."""

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
        start = time.monotonic()
        render_mode = _infer_render_mode(ext.table_structure)
        is_irregular = render_mode == "narrative" or (
            ext.table_structure is not None
            and ext.table_structure.get("irregular", False)
        )

        # C4: 표 신뢰도 낮음
        if "C4_FALLBACK" in ext.flags:
            return LLMOutput(
                element_id=ext.element_id,
                corrected_text="[표 수동 입력 필요]",
                render_mode="narrative",
                routing_tier="FALLBACK",
                processing_time_ms=0,
                rule_trail=_min_trail("[표 수동 입력 필요]"),
            )

        # 텍스트 준비
        if ext.table_structure:
            table_text = _table_to_text(ext.table_structure)
        else:
            table_text = ext.corrected_text or ""

        if not table_text.strip():
            return LLMOutput(
                element_id=ext.element_id,
                corrected_text="[처리 불가: 표 내용 없음]",
                render_mode="narrative",
                routing_tier="FALLBACK",
                processing_time_ms=0,
                rule_trail=_min_trail("[처리 불가: 표 내용 없음]"),
            )

        if routing_tier == "ZERO":
            tn = ensure_tn_prefix(f"표. {table_text[:100]}")  # <!점역자주>…<!/점역자주>
            return LLMOutput(
                element_id=ext.element_id,
                corrected_text=table_text,
                render_mode=render_mode,
                tn_text=tn,
                routing_tier="ZERO",
                processing_time_ms=0,
                rule_trail=_min_trail(table_text),
            )

        timeout = _QUALITY_TIMEOUT if ext.ocr_confidence < config.ocr_confidence_threshold else _STANDARD_TIMEOUT
        tier = "QUALITY" if ext.ocr_confidence < config.ocr_confidence_threshold else "STANDARD"

        if is_irregular:
            prompt = _PROMPT_IRREGULAR.format(text=table_text[:500])
        else:
            prompt = _PROMPT_TABLE_GRID.format(table_text=table_text[:800])

        fail_count = 0
        response = ""
        while fail_count < 3:
            try:
                response = await _hcxt_optimize(prompt, timeout)
                break
            except Exception as exc:
                fail_count += 1
                logger.warning("HyperCLOVA X 표 실패 #%d id=%s: %s", fail_count, ext.element_id, exc)
                if fail_count >= 3:
                    logger.warning("FALLBACK 전환 id=%s", ext.element_id)
                    response = await _fallback_optimize(prompt)
                    tier = "FALLBACK"

        if response:
            parsed = _parse_tn_from_response(response)
            # 처리불가 플레이스홀더는 TN 태그로 감싸지 않는다
            tn_text = parsed if parsed.startswith("[처리 불가") else ensure_tn_prefix(parsed)
        else:
            tn_text = ensure_tn_prefix(f"표. {table_text[:80]}")
        elapsed_ms = int((time.monotonic() - start) * 1000)
        return LLMOutput(
            element_id=ext.element_id,
            corrected_text=table_text,
            render_mode=render_mode,
            tn_text=tn_text,
            routing_tier=tier,
            processing_time_ms=elapsed_ms,
            rule_trail=_min_trail(table_text),
        )
