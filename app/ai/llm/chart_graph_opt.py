"""PART 9-2 — 차트/그래프 점역 최적화 (§6.4 규정 골격 + 2안).

골격(rule-based): 제목 5칸(§6.3.3) + <!점역자주>{그래프유형}: {설명}<!/점역자주>(§6.3.4(1)).
2안 (§6.4·QnA Q5):
  [표 변환]   data_points를 "항목: 수치" 로 정리(rule-based, 데이터 多 권장 — 기본 선택)
  [수학적 서술] 축 범위·단위 + 추세 1개를 문장으로 (축=전사, 추세=LLM/캡션)
수치는 전사·보존(누락 시 R5). 데이터·축이 없으면 caption 폴백.
"""

from __future__ import annotations

from app.ai.braille.regulations import make_rule
from app.ai.llm.base_opt import BaseOpt, decide_tier_timeout, generate_with_retry
from app.ai.llm.base_opt import numbers_grounded as _verify_numbers  # noqa: F401 (테스트가 import)
from app.core.model_manager import model_manager  # noqa: F401 (단위 테스트가 이 네임스페이스를 patch)
from app.schemas.content import Draft, ExtractedContent, LLMOutput, RuleApplication

_RULE_ID = "BBPG-3.2.2"   # 시각자료 유형별 점역(차트·그래프)
_STANDARD_TIMEOUT = 15.0
_QUALITY_TIMEOUT = 30.0
_METHODS = ["표 변환", "수학적 서술"]   # §6.4·Q5 — 규정이 허용하는 2안만

# 차트 하위유형 → 한국어 유형 라벨(전사용)
_SUBTYPE_LABEL = {
    "bar": "막대그래프", "line": "꺾은선그래프", "pie": "비율그래프",
    "scatter": "산점도", "pictograph": "그림그래프", "number_line": "수직선", "area": "선그래프",
}

# 수학적 서술 LLM 프롬프트(추세 1개). 설명문만 — 유형 라벨·점역자주는 코드가 붙임.
_PROMPT = """당신은 시각장애 학생용 점자 교과서 점역 전문가입니다.
다음 그래프를 수학적으로 1문장 서술하세요(축 범위·단위 + 가장 중요한 추세 1개). 설명문만, 유형 라벨·점역자주 금지.
수치는 원문 그대로(추가·누락 금지).

그래프: {caption}"""


def _min_trail(text: str) -> list[RuleApplication]:
    return [make_rule(_RULE_ID)]


def _label(structure: dict) -> str:
    return _SUBTYPE_LABEL.get((structure.get("chart_subtype") or "").strip(), "그래프")


def _table_description(structure: dict) -> str:
    """data_points → '항목: 수치' 표 변환 설명(rule-based 전사). §6.4·Q5."""
    dps = structure.get("data_points") or []
    unit = ((structure.get("axes") or {}).get("y") or {}).get("unit", "") or ""
    parts = []
    for dp in dps:
        label, value = dp.get("label", ""), dp.get("value", "")
        parts.append(f"{label}: {value}{unit}".strip())
    return ", ".join(parts)


def _axes_phrase(structure: dict) -> str:
    """축 라벨·단위 전사 구절(수학적 서술의 rule-based 부분)."""
    axes = structure.get("axes") or {}
    x, y = axes.get("x") or {}, axes.get("y") or {}
    bits = []
    if x.get("label"):
        bits.append(f"가로축 {x['label']}{('('+x['unit']+')') if x.get('unit') else ''}")
    if y.get("label"):
        bits.append(f"세로축 {y['label']}{('('+y['unit']+')') if y.get('unit') else ''}")
    return ", ".join(bits)


def assemble_chart(label: str, title: str, description: str) -> tuple[str, list[int]]:
    """§6.4 골격 조립 → (텍스트, 줄별 들여쓰기). rule-based."""
    lines: list[str] = []
    indents: list[int] = []
    if title:
        lines.append(title); indents.append(5)                      # §6.3.3
    desc = (description or "").strip()
    body = (f"<!점역자주>{label}: {desc}<!/점역자주>" if desc
            else f"<!점역자주>{label} 생략<!/점역자주>")            # §6.3.4(1)
    lines.append(body); indents.append(0)
    return "\n".join(lines), indents


class ChartGraphOpt(BaseOpt):
    """ExtractedContent 목록 → LLMOutput 목록 (차트/그래프). 골격 + 2안(표 변환/수학적 서술)."""

    async def _optimize_one(self, ext: ExtractedContent, routing_tier: str) -> LLMOutput:
        st = ext.structure or {}
        label = _label(st)
        title = (st.get("title") or "").strip()
        caption = (st.get("caption_src") or ext.corrected_text or "").strip()

        table_desc = _table_description(st)        # rule-based(데이터 전사)
        axes = _axes_phrase(st)

        if not caption and not table_desc and not axes:
            return LLMOutput(element_id=ext.element_id, corrected_text="[처리 불가: 차트 캡션 없음]",
                             render_mode="narrative", routing_tier="FALLBACK", processing_time_ms=0,
                             rule_trail=_min_trail(""))

        # 수학적 서술: 비ZERO면 LLM 추세, 아니면 축+캡션 규칙 문장
        tier = routing_tier
        if routing_tier == "ZERO" or not caption:
            math_desc = ", ".join(p for p in (axes, caption) if p) or caption
        else:
            tier, timeout = decide_tier_timeout(ext.ocr_confidence, _STANDARD_TIMEOUT, _QUALITY_TIMEOUT)
            response, used_fb = await generate_with_retry(
                _PROMPT.format(caption=caption), timeout=timeout, element_id=ext.element_id,
                kind="차트", max_new_tokens=256, fallback_max_tokens=256,
            )
            if used_fb:
                tier = "FALLBACK"
            math_desc = (response.strip() or ", ".join(p for p in (axes, caption) if p))

        # 2안 구성: [표 변환](데이터 있으면) + [수학적 서술]. 데이터 없으면 수학적 서술 단일.
        variants: list[tuple[str, str]] = []
        if table_desc:
            variants.append(("표 변환", table_desc))
        variants.append(("수학적 서술", math_desc))

        # 수치 그라운딩 — 원본(표 변환/캡션)의 수치가 각 안에 보존되는지(누락 시 R5)
        ref = table_desc or caption
        if ref and any(not _verify_numbers(ref, d) for _, d in variants):
            ext.flags = list(getattr(ext, "flags", None) or []) + ["R5"]

        drafts: list[Draft] = []
        indents: list[int] = []
        for i, (lab, desc) in enumerate(variants):
            text, indents = assemble_chart(label, title, desc)
            drafts.append(Draft(option=i + 1, text=text, render_mode="narrative", label=lab))
        return LLMOutput(
            element_id=ext.element_id,
            corrected_text=drafts[0].text,
            render_mode="narrative",
            tn_text=drafts[0].text,
            routing_tier=tier,
            processing_time_ms=0,
            rule_trail=_min_trail(drafts[0].text),
            drafts=drafts,
            selected_idx=0,
            line_indents=indents,
        )
