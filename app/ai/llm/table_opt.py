"""PART 6-2 — 표 점역 최적화 (HyperCLOVA X SEED Think 14B INT4, GPU 1).

점역사주 복수 초안 생성 + render_mode 결정.
render_mode 우선순위: table_structure['render_mode'] → 행/열 수 기반 추론 → unfold(풀어쓰기)

공통 추론·폴백·재시도는 base_opt — 여기서는 표에 최적화된 프롬프트·구조 추론만 정의한다.
"""

from __future__ import annotations

import logging
import time
from typing import Optional

from app.ai.braille.nested_block import box_narrative
from app.ai.braille.regulations import make_rule
from app.ai.llm.base_opt import BaseOpt, decide_tier_timeout, generate_with_retry
from app.ai.llm.draft_utils import ensure_tn_prefix
from app.core.model_manager import model_manager  # noqa: F401 (단위 테스트가 이 네임스페이스를 patch)
from app.schemas.content import ExtractedContent, LLMOutput, RuleApplication

logger = logging.getLogger(__name__)

_STANDARD_TIMEOUT = 15.0
_QUALITY_TIMEOUT = 30.0
_NESTED_IMAGE_TYPES = {"image", "picture", "photo", "그림", "사진", "illustration"}


def _nested_image_text(ext: ExtractedContent) -> Optional[str]:
    """표 안 그림(Q11) → 그림을 글상자처럼 1단으로 풀어 쓴 보조 narrative. 없으면 None."""
    for src in (ext.structure, ext.table_structure):
        if src and src.get("nested"):
            blocks = [n for n in src["nested"]
                      if (n.get("type") or "").strip() in _NESTED_IMAGE_TYPES]
            if blocks:
                return box_narrative(blocks, default_label="그림")
    return None


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


def _table_title(ext: ExtractedContent) -> Optional[str]:
    """표 제목(전사) — 도서 제작 지침 제3장 5)(1) 5칸·(2) 표 위에 먼저.

    구조화 입력(table_structure 또는 structure)의 'title'을 그대로 전사한다(rule-based).
    원본에서 제목이 표 안에 있어도 점역 자료에서는 표 위로 올린다(§3 5)(2)).
    """
    for src in (ext.table_structure, ext.structure):
        if src:
            t = (src.get("title") or "").strip()
            if t:
                return t
    return None


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


def _infer_render_mode(table_structure: Optional[dict], text: str = "") -> str:
    if table_structure:
        if rm := table_structure.get("render_mode"):
            return rm
        cells = table_structure.get("cells", [])
        if cells:
            max_row = max((c.get("row", 0) for c in cells), default=0) + 1
            max_col = max((c.get("col", 0) for c in cells), default=0) + 1
            if max_col == 2:
                return "linear"
            if max_row == 1:
                return "transposed"
            return "unfold"   # 3열 이상 = 풀어쓰기 기본(BBPG-3.1.2), 격자는 대안 초안
    # table_structure 없음/빈 셀: 텍스트의 '|' 격자로 추론(현주 미파싱 핸드오프 대비).
    # '|'가 있으면 격자 표 → narrative로 오분류하지 않는다(2열은 linear, 그 외 풀어쓰기).
    rows = [ln for ln in (text or "").splitlines() if "|" in ln]
    if not rows:
        return "narrative"
    max_col = max(len(r.split("|")) for r in rows)
    return "linear" if max_col == 2 else "unfold"


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


class TableOpt(BaseOpt):
    """ExtractedContent 목록 → LLMOutput 목록 (표)."""

    async def _optimize_one(self, ext: ExtractedContent, routing_tier: str) -> LLMOutput:
        start = time.monotonic()
        title = _table_title(ext)              # §3 5) 표 제목 5칸(전사). 없으면 None.
        nested_text = _nested_image_text(ext)  # 표 안 그림(Q11) → 글상자 1단. 없으면 None.
        render_mode = _infer_render_mode(ext.table_structure, ext.corrected_text or "")
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
                table_title=title,
                nested_text=nested_text,
            )

        tier, timeout = decide_tier_timeout(ext.ocr_confidence, _STANDARD_TIMEOUT, _QUALITY_TIMEOUT)
        if is_irregular:
            prompt = _PROMPT_IRREGULAR.format(text=table_text[:500])
        else:
            prompt = _PROMPT_TABLE_GRID.format(table_text=table_text[:800])

        response, used_fb = await generate_with_retry(
            prompt, timeout=timeout, element_id=ext.element_id, kind="표",
            max_new_tokens=512, fallback_max_tokens=1024,
        )
        if used_fb:
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
            table_title=title,
            nested_text=nested_text,
        )
