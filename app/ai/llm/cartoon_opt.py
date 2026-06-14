"""PART 8-2 — 만화 점역 최적화 (rule-based 골격 조립, §5.3).

규정(점자 자료 제작 지침 §5.3)이 만화의 형식을 단일 골격으로 정한다 — 자유서술 3안이 아니다.
구조화 입력(structure.panels)에서 코드가 골격을 결정적으로 조립한다:
  제목줄  : 5칸 <!점역자주>만화<!/점역자주> {제목}            §5.3.1(1)
  장면    : 5칸 <!점역자주>장면 N<!/점역자주>                 §5.3.3(1) (여러 장면일 때)
  장면설명: 3칸 <!점역자주>{설명}<!/점역자주>                 §5.3.3(2)(7)
  대사    : 3칸 {인물명}:{대사}                               §5.3.3(2)(3)  (대사 전사)
  말풍선 화자불명 → '말풍선:내용' (§6.3.4(3)), 인물 불명 특징명은 점역자주 미사용(§5.3.3(5))
구조가 없으면(현주 미구현 등) caption을 단일 점역자주로 폴백한다.
"""

from __future__ import annotations

from app.ai.braille.regulations import make_rule
from app.ai.llm.base_opt import BaseOpt
from app.ai.llm.draft_utils import ensure_tn_prefix
from app.core.model_manager import model_manager  # noqa: F401 (단위 테스트가 이 네임스페이스를 patch)
from app.schemas.content import ExtractedContent, LLMOutput, RuleApplication

_RULE_ID = "JAJAK-5.3"   # 만화 골격 (점자 자료 제작 지침 §5.3)
_SCENE_INDENT = 3
_PANEL_INDENT = 5


def _min_trail(text: str) -> list[RuleApplication]:
    return [make_rule(_RULE_ID)]


def assemble_cartoon(structure: dict) -> tuple[str, list[int]]:
    """structure(panels/title) → (§5.3 골격 텍스트, 줄별 들여쓰기). rule-based·결정적."""
    title = (structure.get("title") or "").strip()
    panels = structure.get("panels") or []
    lines: list[str] = []
    indents: list[int] = []

    head = "<!점역자주>만화<!/점역자주>" + (f" {title}" if title else "")
    lines.append(head); indents.append(_PANEL_INDENT)        # §5.3.1(1)

    multi = len(panels) > 1
    for p in panels:
        if multi:
            lines.append(f"<!점역자주>장면 {p.get('order', '')}<!/점역자주>")
            indents.append(_PANEL_INDENT)                    # §5.3.3(1)
        scene = (p.get("scene_desc") or p.get("scene_src") or "").strip()
        if scene:
            lines.append(f"<!점역자주>{scene}<!/점역자주>")
            indents.append(_SCENE_INDENT)                    # §5.3.3(2)(7) 장면 설정/행동
        for d in p.get("dialogues") or []:
            speaker = (d.get("speaker") or "말풍선").strip()  # §6.3.4(3) 화자 불명
            txt = (d.get("text") or "").strip()
            lines.append(f"{speaker}:{txt}")                 # §5.3.3(2)(3) 인물명:대사(전사)
            indents.append(_SCENE_INDENT)
    return "\n".join(lines), indents


class CartoonOpt(BaseOpt):
    """ExtractedContent 목록 → LLMOutput 목록 (만화). 규정 골격 rule-based 조립(단일 출력)."""

    async def _optimize_one(self, ext: ExtractedContent, routing_tier: str) -> LLMOutput:
        structure = ext.structure or {}
        if structure.get("panels"):
            text, indents = assemble_cartoon(structure)
            return LLMOutput(
                element_id=ext.element_id,
                corrected_text=text,
                render_mode="narrative",
                tn_text=text,
                routing_tier=routing_tier,
                processing_time_ms=0,
                rule_trail=_min_trail(text),
                line_indents=indents,
            )
        # 폴백: 구조 없음 → caption 단일 점역자주
        cap = (ext.corrected_text or "").strip()
        if not cap:
            return LLMOutput(
                element_id=ext.element_id,
                corrected_text="[처리 불가: 만화 캡션 없음]",
                render_mode="narrative",
                routing_tier="FALLBACK",
                processing_time_ms=0,
                rule_trail=_min_trail(""),
            )
        tn = ensure_tn_prefix(f"만화: {cap}")
        return LLMOutput(
            element_id=ext.element_id,
            corrected_text=tn,
            render_mode="narrative",
            tn_text=tn,
            routing_tier=routing_tier,
            processing_time_ms=0,
            rule_trail=_min_trail(tn),
        )
