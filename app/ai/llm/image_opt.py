"""PART 7-2 — 이미지 점역 최적화 (§6.3 규정 골격 + 설명문 LLM 2안).

골격(rule-based, 결정적):
  제목   : 5칸 {제목}                              §6.3.3(1) (제목 있을 때, 점역자주 밖)
  점역자주: <!점역자주>{유형}: {설명}<!/점역자주>   §6.3.4(1) 유형 라벨 필수
  원본내용: ocr_texts 줄 전사                        §6.3.4(2)① 자료 내 글자/수치
생성(LLM): 설명문만 — 2안 위치 중심 / 상황 중심 (QnA Q2). 장식용(decorative)은 생략(§6.3.4(2)②·Q7).
구조가 없으면 caption을 설명문으로 폴백.
"""

from __future__ import annotations

import re

from app.ai.braille.nested_block import box_narrative
from app.ai.braille.regulations import make_rule
from app.ai.llm.base_opt import BaseOpt, decide_tier_timeout, generate_with_retry, numbers_grounded
from app.core.model_manager import model_manager  # noqa: F401 (단위 테스트가 이 네임스페이스를 patch)
from app.schemas.content import Draft, ExtractedContent, LLMOutput, RuleApplication

_NESTED_GRAPH_TYPES = {"chart", "graph", "chart_graph", "그래프", "차트"}


def _nested_graph_text(structure: dict) -> str | None:
    """그림 안 그래프(Q11) → 그래프 설명을 테두리로 묶은 보조 narrative. 없으면 None."""
    blocks = [n for n in (structure.get("nested") or [])
              if (n.get("type") or "").strip() in _NESTED_GRAPH_TYPES]
    return box_narrative(blocks, default_label="그래프")

_RULE_ID = "JAJAK-6.3.3"   # 이미지 골격·제목 5칸 (점자 자료 제작 지침 §6.3)
_STANDARD_TIMEOUT = 15.0
_QUALITY_TIMEOUT = 60.0
_METHODS = ["위치 중심", "상황 중심"]   # §QnA Q2 — 규정이 허용하는 2안만

# 답변 프리필 — 설명문만(점역자주·유형 라벨은 코드가 붙이므로 모델이 쓰지 않게).
_PREFILL = "[방식1] "

_PROMPT = """당신은 시각장애 학생용 점자 교과서 점역 전문가입니다.
다음 그림을 **서로 다른 2가지 방식**의 짧은 객관 설명으로 작성하세요. 설명문만(유형 라벨·점역자주 표시 금지 — 코드가 붙임).
[방식1] 위치 중심: 구성요소의 공간 배치·위치 관계
[방식2] 상황 중심: 무엇이 있고 무엇을 하는지

규칙: 객관 사실만(추측·분위기·작가 의도 금지), 간결, "그림은/이미지는" 시작 금지,
원본에 없는 수치·고유명사 추가 금지, 인물은 이름·성별 없으면 성별 구분 금지.
정확히 2줄([방식1]/[방식2])만.

그림: {caption}"""

_LABEL_RE = re.compile(r"\[?\s*방식\s*[12]\s*[\]:.)]*\s*(.*)")


def _min_trail(text: str) -> list[RuleApplication]:
    return [make_rule(_RULE_ID)]


def assemble_image(label: str, title: str, ocr_texts: list, description: str) -> tuple[str, list[int]]:
    """§6.3 골격 조립 → (텍스트, 줄별 들여쓰기). rule-based."""
    lines: list[str] = []
    indents: list[int] = []
    if title:
        lines.append(title); indents.append(5)                      # §6.3.3(1) 제목 5칸
    desc = (description or "").strip()
    body = (f"<!점역자주>{label}: {desc}<!/점역자주>" if desc
            else f"<!점역자주>{label} 생략<!/점역자주>")            # §6.3.4(1)/(2)
    lines.append(body); indents.append(0)
    for t in ocr_texts or []:
        t = str(t).strip()
        if t:
            lines.append(t); indents.append(0)                      # §6.3.4(2)① 원본 내용 전사
    return "\n".join(lines), indents


def _parse_descriptions(response: str) -> list[str]:
    """LLM 응답 [방식1]/[방식2] → 설명문 목록(유형/점역자주 라벨 제거)."""
    out: list[str] = []
    for ln in response.splitlines():
        m = _LABEL_RE.search(ln.strip())
        if m and m.group(1).strip():
            t = re.sub(r"^\s*(위치 중심|상황 중심)\s*[:：]?\s*", "", m.group(1).strip())
            t = t.replace("<!점역자주>", "").replace("<!/점역자주>", "").strip()
            out.append(t)
    return out


class ImageOpt(BaseOpt):
    """ExtractedContent 목록 → LLMOutput 목록 (이미지). 골격 rule-based + 설명문 2안."""

    async def _optimize_one(self, ext: ExtractedContent, routing_tier: str) -> LLMOutput:
        st = ext.structure or {}
        label = (st.get("visual_type_label") or "그림").strip()
        title = (st.get("title") or "").strip()
        ocr = st.get("ocr_texts") or []
        caption = (st.get("caption_src") or ext.corrected_text or "").strip()

        if st.get("decorative"):   # 장식용 → 생략(빈 출력, layout이 제외). §6.3.4(2)②·Q7
            return LLMOutput(element_id=ext.element_id, corrected_text="", render_mode="narrative",
                             routing_tier=routing_tier, processing_time_ms=0, rule_trail=[])

        if not caption and not ocr and not title:
            return LLMOutput(element_id=ext.element_id, corrected_text="[처리 불가: 이미지 캡션 없음]",
                             render_mode="narrative", routing_tier="FALLBACK", processing_time_ms=0,
                             rule_trail=_min_trail(""))

        tier = routing_tier
        if routing_tier == "ZERO" or not caption:
            descriptions = [caption]                                  # 모델 미사용 → 단일안(캡션 전사)
        else:
            tier, timeout = decide_tier_timeout(ext.ocr_confidence, _STANDARD_TIMEOUT, _QUALITY_TIMEOUT)
            response, used_fb = await generate_with_retry(
                _PROMPT.format(caption=caption), timeout=timeout, element_id=ext.element_id,
                kind="이미지", prefill=_PREFILL, max_new_tokens=512, fallback_max_tokens=256,
            )
            if used_fb:
                tier = "FALLBACK"
            descriptions = _parse_descriptions(response) or [caption]
            if any(not numbers_grounded(caption, d) for d in descriptions):  # 수치 변조 → R5
                ext.flags = list(getattr(ext, "flags", None) or []) + ["R5"]

        drafts: list[Draft] = []
        indents: list[int] = []
        for i, desc in enumerate(descriptions):
            text, indents = assemble_image(label, title, ocr, desc)
            drafts.append(Draft(option=i + 1, text=text, render_mode="narrative",
                                label=_METHODS[i] if i < len(_METHODS) else "설명"))
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
            nested_text=_nested_graph_text(st),   # 그림 안 그래프(Q11) → 테두리 묶기
        )
