"""PART 7-2 — 이미지 점역 최적화 (§6.3 규정 + 대체텍스트 3안).

시각자료 대체텍스트 3안을 생성한다 — 생략 / 설명 / 참조.
공통 로직은 visual_drafts.build_visual_drafts. 여기서는 이미지 구조(구성요소·원본 글자)를
개조식 항목으로 넘기고(rule-based 전사, §6.3.4(2)①), 캡션이 없으면 LLM이 설명을 채운다.

⚠ 아래 `decorative` 인자는 **지금 발화하지 않는다.** `st['decorative']`를 채우는 자리가
  코드 전체에 없어 항상 None이고, 남은 경로 `no_seed`는 캡셔닝이 성공하면 안 걸린다.
  즉 기본 선택은 사실상 항상 '설명'이다. 자세한 것은 visual_drafts 모듈 docstring.
"""

from __future__ import annotations

from app.ai.braille.nested_block import box_narrative
from app.ai.llm.base_opt import BaseOpt
from app.ai.braille import tag_names as _TAGS
from app.ai.llm.visual_drafts import build_visual_drafts, visual_trail
from app.core.model_manager import model_manager  # noqa: F401 (단위 테스트가 이 네임스페이스를 patch)
from app.schemas.content import ExtractedContent, LLMOutput, RuleApplication

_NESTED_GRAPH_TYPES = {"chart", "graph", "chart_graph", "그래프", "차트"}


def _nested_graph_text(structure: dict) -> str | None:
    """그림 안 그래프(Q11) → 그래프 설명을 테두리로 묶은 보조 narrative. 없으면 None."""
    blocks = [n for n in (structure.get("nested") or [])
              if (n.get("type") or "").strip() in _NESTED_GRAPH_TYPES]
    return box_narrative(blocks, default_label="그래프")

_RULE_ID = "NISE-6.3.4"   # 시각 자료 점역자 주 (점자 자료 제작 지침 §6.3.4)


def _trail(drafts, selected_idx: int, source: str) -> list[RuleApplication]:
    """§6.3.4 시각 자료 점역자 주 + 어느 안을 왜 골랐는지(Step17)."""
    return visual_trail(_RULE_ID, drafts, selected_idx, source)


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
        drafts, selected_idx, line_indents, tier, cap_src = await build_visual_drafts(
            ext, routing_tier, label=label, title=title, caption=caption, kind="이미지",
            struct_outline=struct_outline,
            decorative=bool(st.get("decorative")) or no_seed,   # 시드 없음 → 기본 선택 '생략'
        )
        return LLMOutput(
            element_id=ext.element_id,
            # 요소 본문은 **태그 없는 글**로 둔다 — `line_indents` 호환 필드와
            # 줄 단위로 짝지어지는 자리라 줄머리에 태그가 붙으면 짝이 깨진다.
            corrected_text=_TAGS.strip_indent_tags(drafts[selected_idx].text)[0],
            render_mode="narrative",
            tn_text=drafts[selected_idx].text,
            routing_tier=tier,
            processing_time_ms=0,
            rule_trail=_trail(drafts, selected_idx, cap_src),
            drafts=drafts,
            selected_idx=selected_idx,
            line_indents=line_indents,
            nested_text=_nested_graph_text(st),   # 그림 안 그래프(Q11) → 테두리 묶기
        )
