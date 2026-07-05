"""PART 5-2 — 수식 점역 최적화 (HyperCLOVA X SEED Think 14B INT4, GPU 1).

ZERO     → LLM 호출 없음, LaTeX 정규화만 수행
STANDARD → HyperCLOVA X, 15초 제한
QUALITY  → HyperCLOVA X, 30초 제한
FALLBACK → GPT-4o API, 45초 제한 (3회 연속 실패 후)

공통 추론·폴백·재시도는 base_opt — 여기서는 수식에 최적화된 프롬프트·정규화만 정의한다.
"""

from __future__ import annotations

import logging
import re
import time

from app.ai.braille.regulations import make_rule
from app.ai.llm.base_opt import BaseOpt, decide_tier_timeout, generate_with_retry
from app.core.model_manager import model_manager  # noqa: F401 (단위 테스트가 이 네임스페이스를 patch)
from app.schemas.content import ExtractedContent, LLMOutput, RuleApplication

logger = logging.getLogger(__name__)



def _min_trail(text: str) -> list[RuleApplication]:
    """수학 점자 일반(KBR-수학-1.1) — 요소 전체(line_no=-1)."""
    return [make_rule("KBR-수학-1.1")]

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

# 답변을 `교정된 LaTeX: `로 프리필 — Think 모델이 "주어진 수식을 교정해야 합니다. 규칙을…"
# 식 사고과정을 출력하지 않고 곧바로 LaTeX를 내도록 시작을 강제. 스캐폴드는 _extract에서 제거.
_PREFILL = "교정된 LaTeX: "


def _normalize(latex: str) -> str:
    for pattern, replacement in _LATEX_NORMALIZE:
        latex = re.sub(pattern, replacement, latex)
    return latex


# ```latex … ``` 코드펜스(언어태그 포함)·$$ 구분자 제거. 백틱만 strip하면 'latex'
# 언어태그가 남아 그대로 점역되는 버그가 있었다(⠇⠁⠞⠑⠭).
_FENCE_RE = re.compile(r"```[a-zA-Z]*\n?|```")
_DOLLAR_RE = re.compile(r"^\s*\${1,2}|\${1,2}\s*$")


def _extract(resp: str) -> str:
    """프리필 스캐폴드·코드펜스·$$ 구분자를 제거하고 본문은 그대로 둔다(여러 줄 LaTeX 보존).

    프리필이 설명 머리말을 억제하므로 첫 줄만 자르지 않는다 — \\begin{cases} 등
    여러 줄 수식이 잘려 깨지는 것을 막는다.
    """
    t = resp[len(_PREFILL):] if resp.startswith(_PREFILL) else resp
    t = _FENCE_RE.sub("", t).strip()      # ```latex … ``` 펜스(언어태그 포함)
    t = t.strip("`").strip()              # 잔여 인라인 백틱(`…`)
    t = _DOLLAR_RE.sub("", t).strip()     # $$ … $$ 구분자
    return t


class FormulaOpt(BaseOpt):
    """ExtractedContent 목록 → LLMOutput 목록 (수식)."""

    async def _optimize_one(self, ext: ExtractedContent, routing_tier: str) -> LLMOutput:
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
                rule_trail=_min_trail(placeholder),
            )

        render_mode = "formula_inline" if len(raw) <= 30 else "formula_block"

        if routing_tier == "ZERO":
            norm = _normalize(raw)
            return LLMOutput(
                element_id=ext.element_id,
                corrected_text=norm,
                render_mode=render_mode,
                routing_tier="ZERO",
                processing_time_ms=0,
                rule_trail=_min_trail(norm),
            )

        tier, timeout = decide_tier_timeout(ext.ocr_confidence)   # 요소당 상한 = config(작게)
        response, used_fb = await generate_with_retry(
            _PROMPT.format(latex=raw),
            timeout=timeout, element_id=ext.element_id, kind="수식",
            prefill=_PREFILL, max_new_tokens=256, fallback_max_tokens=512,
            transform=_extract,
        )
        if used_fb:
            tier = "FALLBACK"

        corrected = _normalize(response or raw)
        elapsed_ms = int((time.monotonic() - start) * 1000)
        return LLMOutput(
            element_id=ext.element_id,
            corrected_text=corrected,
            render_mode=render_mode,
            routing_tier=tier,
            processing_time_ms=elapsed_ms,
            rule_trail=_min_trail(corrected),
        )
