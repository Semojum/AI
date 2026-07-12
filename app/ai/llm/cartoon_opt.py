"""PART 8-2 — 만화 점역 최적화 (§5.3 규정 + 대체텍스트 4안).

시각자료 대체텍스트 4안(QA 2026-07-05) — 생략 / 짧은 제목 / 개조식 / 줄글.
만화는 구조(structure.panels)가 있으면 개조식이 곧 §5.3 골격(장면·대사 전사)이고, 줄글은
이야기 흐름 설명이다. 대사(§5.3.3(2)(3))는 rule-based 전사, 캡션만 있으면 LLM이 채운다.
"""

from __future__ import annotations

from app.ai.braille.regulations import make_rule
from app.ai.llm.base_opt import BaseOpt
from app.ai.llm.visual_drafts import build_visual_drafts
from app.core.model_manager import model_manager  # noqa: F401 (단위 테스트가 이 네임스페이스를 patch)
from app.schemas.content import ExtractedContent, LLMOutput, RuleApplication

_RULE_ID = "JAJAK-5.3"   # 만화 골격 (점자 자료 제작 지침 §5.3)


def _trail() -> list[RuleApplication]:
    return [make_rule(_RULE_ID)]


def _panel_items(structure: dict) -> list[tuple[int, str]]:
    """panels → 개조식 항목. 여러 장면이면 '장면 N'(level0)·설명/대사(level1). §5.3.3."""
    panels = structure.get("panels") or []
    multi = len(panels) > 1
    items: list[tuple[int, str]] = []
    for p in panels:
        if multi:
            items.append((0, f"장면 {p.get('order', '')}".strip()))
        scene = (p.get("scene_desc") or p.get("scene_src") or "").strip()
        if scene:
            items.append((1 if multi else 0, scene))          # §5.3.3(2)(7)
        for d in p.get("dialogues") or []:
            speaker = (d.get("speaker") or "말풍선").strip()   # §6.3.4(3) 화자 불명
            txt = (d.get("text") or "").strip()
            items.append((1 if multi else 0, f"{speaker}:{txt}"))  # §5.3.3(2)(3) 대사 전사
    return items


class CartoonOpt(BaseOpt):
    """ExtractedContent 목록 → LLMOutput 목록 (만화). 대체텍스트 4안."""

    async def _optimize_one(self, ext: ExtractedContent, routing_tier: str) -> LLMOutput:
        st = ext.structure or {}
        title = (st.get("title") or "").strip()
        caption = (ext.corrected_text or "").strip()
        items = _panel_items(st)

        # 시드가 전부 없으면(캡셔닝 실패 포함) 규정상 '생략' 표기가 정답이다(§6.3.4(2)②).
        # 실패 문자열을 내면 그 한글이 점자로 찍혀 학생에게 나간다. 알림은 flags→R11로.
        no_seed = not (items or caption or title)

        drafts, selected_idx, line_indents, tier = await build_visual_drafts(
            ext, routing_tier, label="만화", title=title, caption=caption, kind="만화",
            struct_outline=items or None,
            decorative=no_seed,
        )
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
