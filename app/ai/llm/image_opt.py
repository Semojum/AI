"""PART 7-2 — 이미지 점역 최적화 (§6.3 규정 + 대체텍스트 4안).

시각자료 대체텍스트 4안(QA 2026-07-05)을 생성한다 — 생략 / 짧은 제목 / 개조식 / 줄글.
공통 로직은 visual_drafts.build_visual_drafts. 여기서는 이미지 구조(구성요소·원본 글자)를
개조식 항목으로 넘기고(rule-based 전사, §6.3.4(2)①), 캡션 없으면 제목·줄글만 LLM이 채운다.
장식용(decorative)은 기본 선택을 '생략'으로 둔다(§6.3.4(2)②·Q7).
"""

from __future__ import annotations

from app.ai.braille.nested_block import box_narrative
from app.ai.braille.regulations import make_rule
from app.ai.llm.base_opt import BaseOpt
from app.ai.llm.visual_drafts import build_visual_drafts
from app.core.model_manager import model_manager  # noqa: F401 (단위 테스트가 이 네임스페이스를 patch)
from app.schemas.content import ExtractedContent, LLMOutput, RuleApplication

_NESTED_GRAPH_TYPES = {"chart", "graph", "chart_graph", "그래프", "차트"}


def _nested_graph_text(structure: dict) -> str | None:
    """그림 안 그래프(Q11) → 그래프 설명을 테두리로 묶은 보조 narrative. 없으면 None."""
    blocks = [n for n in (structure.get("nested") or [])
              if (n.get("type") or "").strip() in _NESTED_GRAPH_TYPES]
    return box_narrative(blocks, default_label="그래프")

_RULE_ID = "JAJAK-6.3.4"   # 시각 자료 점역자 주 (점자 자료 제작 지침 §6.3.4)


def _trail() -> list[RuleApplication]:
    return [make_rule(_RULE_ID)]


class ImageOpt(BaseOpt):
    """ExtractedContent 목록 → LLMOutput 목록 (이미지). 대체텍스트 4안."""

    async def _optimize_one(self, ext: ExtractedContent, routing_tier: str) -> LLMOutput:
        st = ext.structure or {}
        label = (st.get("visual_type_label") or "그림").strip()
        title = (st.get("title") or "").strip()
        ocr = [str(t).strip() for t in (st.get("ocr_texts") or []) if str(t).strip()]
        caption = (st.get("caption_src") or ext.corrected_text or "").strip()

        # 캡션·원본글자·제목이 전부 없다(캡셔닝 실패 포함) → 규정상 정답은 '생략' 표기다
        # (§6.3.4(2)②). 실패 문자열("[처리 불가: …]")을 내면 그 한글이 그대로 점자로 찍혀
        # 학생에게 나간다 — 어떤 경우에도 정당하지 않다. 점역사에겐 flags→R11로 알린다.
        no_seed = not (caption or ocr or title)

        # 원본 글자(ocr_texts)가 있으면 개조식 항목으로 rule-based 전사(§6.3.4(2)①).
        struct_outline = [(0, t) for t in ocr] if ocr else None
        drafts, selected_idx, line_indents, tier = await build_visual_drafts(
            ext, routing_tier, label=label, title=title, caption=caption, kind="이미지",
            struct_outline=struct_outline,
            decorative=bool(st.get("decorative")) or no_seed,   # 시드 없음 → 기본 선택 '생략'
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
            nested_text=_nested_graph_text(st),   # 그림 안 그래프(Q11) → 테두리 묶기
        )
