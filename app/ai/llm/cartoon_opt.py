"""PART 8-2 — 만화 점역 최적화 (§5.3 규정 + 대체텍스트 3안).

시각자료 대체텍스트 3안(2026-08-20) — 생략 / 설명 / 참조.
만화는 구조(structure.panels)가 있으면 개조식이 곧 §5.3 골격(장면·대사 전사)이고, 줄글은
이야기 흐름 설명이다. 대사(§5.3.3(2)(3))는 rule-based 전사, 캡션만 있으면 LLM이 채운다.
"""

from __future__ import annotations

import re

from app.ai.llm.base_opt import BaseOpt
from app.ai.braille import tag_names as _TAGS
from app.ai.llm.visual_drafts import build_visual_drafts, visual_trail
from app.core.model_manager import model_manager  # noqa: F401 (단위 테스트가 이 네임스페이스를 patch)
from app.schemas.content import ExtractedContent, LLMOutput, RuleApplication

_RULE_ID = "JAJAK-5.3"   # 만화 골격 (점자 자료 제작 지침 §5.3)

# §5.3.3(1) 장면 번호는 5칸, (2) 인물의 대화는 3칸.
# visual_drafts의 위계 레벨은 level0→3칸(_OUTLINE_BASE)·level1→5칸이므로 **대사가 level0,
# 장면이 level1**이다(들여쓰기 칸수 기준이지 종속 관계가 아니다).
# ⚠ 종전 코드는 반대로 넣어 장면 3칸·대사 5칸으로 규정과 어긋나 있었다(2026-08-07 QA 13번).
_LV_LINE, _LV_SCENE = 0, 1


def _trail(drafts, selected_idx: int, source: str) -> list[RuleApplication]:
    """§5.3 만화 형식 + 어느 안을 왜 골랐는지(Step17)."""
    return visual_trail(_RULE_ID, drafts, selected_idx, source)


def _say(speaker: str, text: str) -> str:
    """§5.3.3(3) 인물명과 대사는 쌍점으로 구분. 쌍점 뒤 한 칸 띈다.

    BBPG 제3장 [예 3-54] 정답 점자를 역점역해 확인한 형태 — "학생: 선생님, 농업의 사회적…".
    종전 코드는 `f"{speaker}:{txt}"`로 붙여 써서 정답과 어긋났다(2026-08-07 규정 대조).
    """
    return f"{speaker}: {text}".strip()


def _panel_items(structure: dict) -> list[tuple[int, str]]:
    """panels → 개조식 항목. 여러 장면이면 '장면 N'(5칸)·대사(3칸). §5.3.3."""
    panels = structure.get("panels") or []
    multi = len(panels) > 1
    items: list[tuple[int, str]] = []
    for p in panels:
        if multi:
            items.append((_LV_SCENE, f"장면 {p.get('order', '')}".strip()))
        scene = (p.get("scene_desc") or p.get("scene_src") or "").strip()
        if scene:
            items.append((_LV_LINE, scene))                   # §5.3.3(2)(7)
        for d in p.get("dialogues") or []:
            speaker = (d.get("speaker") or "말풍선").strip()   # §6.3.4(3) 화자 불명
            items.append((_LV_LINE, _say(speaker, (d.get("text") or "").strip())))
    return items


# ── 캡션(대본 형식 평문) → 개조식 항목 ───────────────────────────────────────
# captioner의 cartoon 프롬프트가 §5.3 형식으로 뽑아 준 평문을 여기서 그대로 항목화한다.
# structure.panels가 오는 경로(현주 구조 추출)와 캡션만 오는 경로(MinerU) 둘 다 같은 골격이
# 되게 하는 것이 목적이다. **파싱되면 LLM 재구성을 아예 건너뛴다** — 종전에는 캡션을 통째로
# 점역자주 머리줄에 넣고 그 아래 LLM이 같은 내용을 또 풀어써서 중복이 났다(QA 13번).
_HEAD_RE = re.compile(r"^만화\s*[:：]\s*")
_SCENE_RE = re.compile(r"^(?:장면|컷)\s*(\d+)\s*[:：.]?\s*(.*)$")
_NUM_CUT_RE = re.compile(r"^(\d+)\s*컷\s*[:：.]?\s*(.*)$")     # "1컷: …" 실측 출력 대비
_SITU_RE = re.compile(r"^[(（\[]\s*상황\s*[)）\]]\s*[:：]?\s*")
_SAY_RE = re.compile(r"^([^:：]{1,20})\s*[:：]\s*(.+)$")
# 화자로 오인하기 쉬운 머리말 — 이 말이 화자로 들어가면 "대사: …"처럼 규정을 어긴다.
_NOT_SPEAKER = {"대사", "말", "내용", "상황", "장면", "설명", "흐름", "요약", "제목", "만화", "배경"}
# 화자를 못 밝힌 대사 머리말 → §6.3.4(3) 화자 불명은 '말풍선'으로 적는다.
_ANON_SAY = {"대사", "말", "말풍선"}
# 만화 전체를 다시 요약하는 꼬리 줄 — 제목 줄과 겹친다. QA 13번 "내용이 중복됨"의 그 줄.
_REDUNDANT = {"흐름", "요약", "정리", "전체", "줄거리"}


def _caption_items(caption: str) -> tuple[str, list[tuple[int, str]]]:
    """대본 형식 캡션 → (제목, 개조식 항목). 형식이 아니면 ("", []) 로 물러난다."""
    title, items = "", []
    scenes = says = 0
    for raw in (caption or "").splitlines():
        line = raw.strip()
        if not line:
            continue                                   # BBPG 3장 9)(1)② 빈 줄 버림
        if not title and _HEAD_RE.match(line):
            title = _HEAD_RE.sub("", line).strip()
            continue
        m = _SCENE_RE.match(line) or _NUM_CUT_RE.match(line)
        if m:
            items.append((_LV_SCENE, f"장면 {m.group(1)}"))    # §5.3.3(1)
            scenes += 1
            rest = m.group(2).strip()
            if rest:                                   # "장면 1 …" 꼬리는 상황 설명 취급
                items.append((_LV_LINE, f"<!주>{rest}<!/주>"))
            continue
        if _SITU_RE.match(line):                       # §5.3.3(6)(7) 행동·상황은 점역자주 안
            body = _SITU_RE.sub("", line).strip()
            if body:
                items.append((_LV_LINE, f"<!주>{body}<!/주>"))
            continue
        m = _SAY_RE.match(line)
        if m:
            head, body = m.group(1).strip(), m.group(2).strip()
            if head in _REDUNDANT:
                continue                               # 제목 줄과 겹치는 재요약 — 버린다
            if head in _ANON_SAY:                      # §6.3.4(3) 화자 불명
                head = "말풍선"
            if head not in _NOT_SPEAKER:
                items.append((_LV_LINE, _say(head, body)))
                says += 1
                continue
        return "", []                                  # 형식 이탈 — 통째로 포기(구 경로 유지)
    # 대사가 하나도 없으면 대본이 아니다. 한 장면짜리 설명형은 구 경로(§5.3.2)가 낫다.
    return (title, items) if says else ("", [])


class CartoonOpt(BaseOpt):
    """ExtractedContent 목록 → LLMOutput 목록 (만화). 대체텍스트 3안."""

    async def _optimize_one(self, ext: ExtractedContent, routing_tier: str) -> LLMOutput:
        st = ext.structure or {}
        title = (st.get("title") or "").strip()
        caption = (ext.corrected_text or "").strip()
        items = _panel_items(st)

        # 구조가 없으면 캡션이 대본 형식인지 본다. 형식이면 그게 곧 §5.3 골격이므로
        # 캡션은 제목 한 줄만 남기고(중복 제거) 항목을 rule-based로 넘긴다.
        if not items:
            cap_title, cap_items = _caption_items(caption)
            if cap_items:
                # 캡션 제목은 **점역자주 머리줄**로만 간다 — §5.3(1) "'만화'를 5칸에 적고 한 칸
                # 띈 후 만화 제목". 별도 제목줄로도 세우면 같은 문장이 두 줄이 된다.
                items, caption = cap_items, cap_title

        # 시드가 전부 없으면(캡셔닝 실패 포함) 규정상 '생략' 표기가 정답이다(§6.3.4(2)②).
        # 실패 문자열을 내면 그 한글이 점자로 찍혀 학생에게 나간다. 알림은 flags→R11로.
        no_seed = not (items or caption or title)

        drafts, selected_idx, line_indents, tier, cap_src = await build_visual_drafts(
            ext, routing_tier, label="만화", title=title, caption=caption, kind="만화",
            struct_outline=items or None,
            decorative=no_seed,
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
        )
