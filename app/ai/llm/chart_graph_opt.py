"""PART 9-2 — 차트/그래프 점역 최적화 (§6.4 규정 + 대체텍스트 4안).

시각자료 대체텍스트 4안(QA 2026-07-05) — 생략 / 짧은 제목 / 개조식 / 줄글.
차트는 데이터가 있으면 개조식이 곧 '표 변환'(항목:수치 전사, §6.4·Q5)이고, 줄글은
수학적 서술(축·추세). data_points/axes는 rule-based 전사, 캡션만 있으면 LLM이 채운다.
수치는 보존(누락 시 R5).
"""

from __future__ import annotations

from app.ai.braille.regulations import make_rule
from app.ai.llm.base_opt import BaseOpt
from app.ai.llm.base_opt import numbers_grounded as _verify_numbers  # noqa: F401 (테스트가 import)
from app.ai.llm.visual_drafts import PROSE_IDX, build_visual_drafts
from app.core.model_manager import model_manager  # noqa: F401 (단위 테스트가 이 네임스페이스를 patch)
from app.schemas.content import ExtractedContent, LLMOutput, RuleApplication

_RULE_ID = "JAJAK-6.4.1"   # 그래프 골격 (점자 자료 제작 지침 §6.4)

# 차트 하위유형 → 한국어 유형 라벨(전사용)
_SUBTYPE_LABEL = {
    "bar": "막대그래프", "line": "꺾은선그래프", "pie": "비율그래프",
    "scatter": "산점도", "pictograph": "그림그래프", "number_line": "수직선", "area": "선그래프",
}


def _trail() -> list[RuleApplication]:
    return [make_rule(_RULE_ID)]


def _label(structure: dict) -> str:
    return _SUBTYPE_LABEL.get((structure.get("chart_subtype") or "").strip(), "그래프")


def _data_items(structure: dict) -> list[tuple[int, str]]:
    """data_points → 개조식 항목 '항목: 수치'(rule-based 전사, §6.4·Q5 표 변환). 축은 머리 항목."""
    items: list[tuple[int, str]] = []
    axes = _axes_phrase(structure)
    if axes:
        items.append((0, axes))
    unit = ((structure.get("axes") or {}).get("y") or {}).get("unit", "") or ""
    for dp in structure.get("data_points") or []:
        label, value = dp.get("label", ""), dp.get("value", "")
        items.append((1 if axes else 0, f"{label}: {value}{unit}".strip()))
    return items


def _axes_phrase(structure: dict) -> str:
    """축 라벨·단위 전사 구절."""
    axes = structure.get("axes") or {}
    x, y = axes.get("x") or {}, axes.get("y") or {}
    bits = []
    if x.get("label"):
        bits.append(f"가로축 {x['label']}{('('+x['unit']+')') if x.get('unit') else ''}")
    if y.get("label"):
        bits.append(f"세로축 {y['label']}{('('+y['unit']+')') if y.get('unit') else ''}")
    return ", ".join(bits)


class ChartGraphOpt(BaseOpt):
    """ExtractedContent 목록 → LLMOutput 목록 (차트/그래프). 대체텍스트 4안."""

    async def _optimize_one(self, ext: ExtractedContent, routing_tier: str) -> LLMOutput:
        st = ext.structure or {}
        label = _label(st)
        title = (st.get("title") or "").strip()
        caption = (st.get("caption_src") or ext.corrected_text or "").strip()

        data_items = _data_items(st)               # rule-based(데이터 전사)
        axes = _axes_phrase(st)

        if not caption and not data_items and not axes:
            return LLMOutput(element_id=ext.element_id, corrected_text="[처리 불가: 차트 캡션 없음]",
                             render_mode="narrative", routing_tier="FALLBACK", processing_time_ms=0,
                             rule_trail=_trail())

        # 데이터가 있으면 개조식=표 변환(rule-based). 줄글(수학적 서술)은 LLM(또는 규칙 폴백).
        struct_outline = data_items or None
        # ZERO/캡션 없음: 생성 없이 축+데이터를 rule-based 줄글로(수치 보존).
        rule_prose = ", ".join(p for p in ([axes] + [t for _, t in data_items]) if p) or caption
        struct_prose = rule_prose if (routing_tier == "ZERO" or not caption) else None
        drafts, selected_idx, line_indents, tier = await build_visual_drafts(
            ext, routing_tier, label=label, title=title, caption=caption, kind="차트",
            struct_outline=struct_outline, struct_prose=struct_prose,
        )

        # 수치 그라운딩 — LLM이 생성한 줄글에서 원본 수치가 누락/변조됐는지(누락 시 R5).
        # ZERO/rule-based 줄글은 전사라 검사 불필요(생성 환각 위험 없음).
        ref = ", ".join(t for _, t in data_items) or caption
        if tier not in ("ZERO",) and struct_prose is None and ref and not _verify_numbers(ref, drafts[PROSE_IDX].text):
            ext.flags = list(getattr(ext, "flags", None) or []) + ["R5"]

        return LLMOutput(
            element_id=ext.element_id,
            corrected_text=drafts[selected_idx].text,
            render_mode="narrative",
            tn_text=drafts[selected_idx].text,
            routing_tier=tier,
            processing_time_ms=0,
            rule_trail=_trail(),
            drafts=drafts,
            selected_idx=selected_idx,
            line_indents=line_indents,
        )
