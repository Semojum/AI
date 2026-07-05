"""PART(도표) — 개념도·흐름도 점역 최적화 (rule-based 골격 조립, §6.6).

규정(점자 자료 제작 지침 §6.6)이 도표의 형식을 결정적 골격으로 정한다 — 자유서술이 아니다.
구조화 입력(structure)에서 코드가 골격을 결정적으로 조립한다(전사).

공통(§6.3.3·§6.3.4):
  제목줄  : 5칸 {제목}                           §6.3.3(1) 시각 자료 제목은 윗줄 5칸
  유형    : <!점역자주>{개념도|흐름도}<!/점역자주> §6.3.4(1) 유형 제시(점역자 주)

개념도(§6.6.1) — 위계가 있는 개조식 항목(들여쓰기):
  2단계: 상위 5칸 · 하위 3칸                      §6.6.1(3)①
  3단계: 최상위 7칸 · 중위 5칸 · 하위 3칸          §6.6.1(3)②
  → 일반화: 깊이 D, 레벨 L(0=최상위)의 들여쓰기 = 3 + 2*(D-1-L).
    D=2→[5,3], D=3→[7,5,3] (규정 일치). D=1→[3], D≥4는 같은 규칙으로 외삽(9,7,5,3…).

흐름도(§6.6.2) — 텍스트 점역 모드(그래픽 점역 모드는 촉각 그래픽이라 본 파이프라인 범위 밖):
  ①논리 순서로 상자에 번호(시작=1)  ③번호+도형기호(빈칸X)+한칸+내용  ④상자 한 줄에 하나
  ⑤분기 선택지 줄바꿈  ⑥선택지 3칸: 3o(반직선) 선택사항 3o 목적지
  ※ 도형 점형(@$R 등)·반직선 점형(3o) 글리프는 점역사 확인 후 배선 — 현재는 구조 골격만 출력.
    (디코드 표는 diagram_braille._FLOW_SHAPE_ASCII 주석 참조: Braille ASCII 디코드, 검증 대기.)

조직도(§6.6.5) — 상하 위계 트리:
  (1)한 줄에 하나  (2)최상위 1칸·하위 단계마다 +2칸  (3)들여쓰기 방식은 점역자 주로 설명.
가계도(§6.6.4) — 하향식/상향식:
  하향식(2): 선조→후손, 한 줄 한 사람, 최상위 1칸·하위 +2칸(조직도와 동일 위계 들여쓰기).
  상향식(3): 후손→선조, 한 줄 한 항목, 각 항목 3칸.
  ※ 결혼·관계 기호(④)·상향식 부모 번호/빈자리 표기(④)는 점역사 확인 후 배선 — 점역자 주만.
연대표(§6.6.6) — 시간순 사건:
  (2)②한 줄 한 사건, 날짜+한 칸+사건  ③사건 없는 날짜 생략  (4)동일 연도 다수: 연도 5칸·사건 3칸.
양식(§6.6.3) — 글상자, 한 줄 한 항목:
  (2)글상자  (3)항목 한 줄씩  (5)빈칸 길이 정보는 점역자 주.
  ※ 밑줄 빈칸 글리프(4)는 점역사 확인 후 배선 — 현재는 항목 텍스트만 전사.
화면 이미지(§6.6.7) — 글상자, 구획별:
  (1)글상자 테두리 사이  (3)①도구 막대·메뉴·본문 등 구획별 표기.
  ※ 색깔 단서(2)·하이퍼링크 표시(3③)는 점역사 확인 후 배선 — 점역자 주만.
발표용 슬라이드(§6.6.8):
  (2)제목·들여쓰기·문단 형식  (3)노트는 점역자 주 '노트:' 뒤에 같은 줄에 내용.
  ※ 슬라이드 번호(1)는 원본 페이지 번호와 동일 방식 — layout 페이지 기구 담당(여기 범위 밖).

구조가 없으면(현주 미구현 등) caption을 단일 점역자주로 폴백한다.
"""

from __future__ import annotations

import re
from typing import Optional

from app.ai.braille.regulations import make_rule
from app.ai.llm.base_opt import BaseOpt
from app.ai.llm.visual_drafts import (
    OUTLINE_IDX,
    LABELS,
    build_visual_drafts,
    omission_draft,
    prose_draft,
    title_draft,
)
from app.core.model_manager import model_manager  # noqa: F401 (단위 테스트가 이 네임스페이스를 patch)
from app.schemas.content import Draft, ExtractedContent, LLMOutput, RuleApplication

_RULE_ID = "JAJAK-6.6.1"   # 도표 골격 (점자 자료 제작 지침 §6.6)
_TITLE_INDENT = 5         # §6.3.3(1)
_BRANCH_INDENT = 3        # §6.6.2(4)⑥ 선택지 3칸
_HIER_BASE = 1            # §6.6.5(2)·§6.6.4(2)② 최상위 1칸
_HIER_STEP = 2            # 하위 단계마다 +2칸
_BOTTOMUP_INDENT = 3      # §6.6.4(3)② 상향식 가계도 항목 3칸
_TIMELINE_YEAR = 5        # §6.6.6(4) 동일 연도 연도줄 5칸
_TIMELINE_EVENT = 3       # §6.6.6(4) 동일 연도 사건줄 3칸
_SCREEN_SECTION_BODY = 2  # 화면 이미지 구획 내용 들여쓰기(§6.6.7(3)① 가독성)
_BOX_TOP = "<!테두리_위><!/테두리_위>"      # 글상자 위 테두리(빈 제목 쌍) — layout 재렌더
_BOX_BOTTOM = "<!테두리_아래><!/테두리_아래>"  # 글상자 아래 테두리
_TYPE_LABEL = {
    "concept_map": "개념도", "flowchart": "흐름도",
    "org_chart": "조직도", "family_tree": "가계도", "timeline": "연대표",
    "form": "양식", "screen_image": "화면 이미지", "slide": "발표용 슬라이드",
}


def _min_trail(text: str) -> list[RuleApplication]:
    return [make_rule(_RULE_ID)]


def _subtype(ext: ExtractedContent) -> str:
    """concept_map / flowchart 판별 — structure.subtype 우선, 없으면 visual_subtype."""
    st = ext.structure or {}
    return (st.get("subtype") or ext.visual_subtype or "").strip()


# ── 개념도 (§6.6.1) ──────────────────────────────────────────────────────────

def _tree_depth(nodes: list) -> int:
    """노드 트리의 최대 깊이(빈 트리=0)."""
    if not nodes:
        return 0
    return 1 + max((_tree_depth(n.get("children") or []) for n in nodes), default=0)


def _concept_indent(level: int, depth: int) -> int:
    """레벨(0=최상위)·전체 깊이 → 들여쓰기 칸(§6.6.1(3)). 하위=3칸, 위로 갈수록 +2칸."""
    return 3 + 2 * (depth - 1 - level)


def _flatten_concept(nodes: list, level: int, depth: int,
                     lines: list[str], indents: list[int]) -> None:
    """DFS 전위순회 — 중심개념부터 하위개념 순서대로(§6.6.1(2)), 줄별 들여쓰기."""
    for n in nodes:
        text = (n.get("text") or "").strip()
        if text:
            lines.append(text)
            indents.append(_concept_indent(level, depth))
        _flatten_concept(n.get("children") or [], level + 1, depth, lines, indents)


def assemble_concept_map(structure: dict) -> tuple[str, list[int]]:
    """개념도 structure → (§6.6.1 골격 텍스트, 줄별 들여쓰기). rule-based·결정적(전사)."""
    title = (structure.get("title") or "").strip()
    nodes = structure.get("nodes") or []
    lines: list[str] = []
    indents: list[int] = []

    if title:
        lines.append(title); indents.append(_TITLE_INDENT)                  # §6.3.3(1)
    lines.append("<!점역자주>개념도<!/점역자주>"); indents.append(0)        # §6.3.4(1)

    depth = _tree_depth(nodes)
    _flatten_concept(nodes, 0, depth, lines, indents)                        # §6.6.1(2)(3)
    return "\n".join(lines), indents


# ── 흐름도 (§6.6.2) — 구조 골격만(도형 점형 보류) ─────────────────────────────

def assemble_flowchart(structure: dict) -> tuple[str, list[int]]:
    """흐름도 structure → (§6.6.2(4) 구조 골격, 줄별 들여쓰기). rule-based.

    번호+내용을 한 줄에 하나씩, 분기 선택지는 3칸에 한 줄씩 적는다(§6.6.2(4)①④⑤).
    도형 점형(③의 도형기호)·반직선 점형(⑥의 3o)은 점역사 확인 후 배선 — 현재는 구조만.
    """
    title = (structure.get("title") or "").strip()
    boxes = structure.get("boxes") or []
    lines: list[str] = []
    indents: list[int] = []

    if title:
        lines.append(title); indents.append(_TITLE_INDENT)                  # §6.3.3(1)
    lines.append("<!점역자주>흐름도<!/점역자주>"); indents.append(0)        # §6.3.4(1)

    for box in boxes:
        no = box.get("no", "")
        text = (box.get("text") or "").strip()
        # §6.6.2(4)③④ — 번호 + (도형기호: 보류) + 내용, 상자 한 줄에 하나
        lines.append(f"{no} {text}".strip()); indents.append(0)
        for br in box.get("branches") or []:                                # §6.6.2(4)⑤⑥
            label = (br.get("label") or "").strip()
            to = br.get("to", "")
            # 선택지 3칸 — 반직선(3o) 점형은 보류, 구조(선택사항·목적지)만 전사
            lines.append(f"{label}: {to}".strip(": ").strip() or label)
            indents.append(_BRANCH_INDENT)
    return "\n".join(lines), indents


# ── 조직도(§6.6.5) · 하향식 가계도(§6.6.4(2)) — 위계 트리 ─────────────────────

def _hier_indent(level: int) -> int:
    """위계 들여쓰기(§6.6.5(2)·§6.6.4(2)②): 최상위 1칸, 하위 단계마다 +2칸."""
    return _HIER_BASE + _HIER_STEP * level


def _flatten_hier(nodes: list, level: int, lines: list[str], indents: list[int]) -> None:
    """DFS 전위순회 — 상위→하위, 한 줄에 하나, 단계별 +2칸 들여쓰기."""
    for n in nodes:
        text = (n.get("text") or "").strip()
        if text:
            lines.append(text); indents.append(_hier_indent(level))
        _flatten_hier(n.get("children") or [], level + 1, lines, indents)


def assemble_org_chart(structure: dict) -> tuple[str, list[int]]:
    """조직도 structure → (§6.6.5 골격, 줄별 들여쓰기). 한 줄 하나·위계 +2칸(전사)."""
    lines: list[str] = []
    indents: list[int] = []
    title = (structure.get("title") or "").strip()
    if title:
        lines.append(title); indents.append(_TITLE_INDENT)                  # §6.3.3(1)
    # §6.3.4(1) 유형 + §6.6.5(3) 들여쓰기 방식 점역자 주
    lines.append("<!점역자주>조직도: 들여쓰기로 상하 위계를 나타냄<!/점역자주>"); indents.append(0)
    _flatten_hier(structure.get("nodes") or [], 0, lines, indents)           # §6.6.5(1)(2)
    return "\n".join(lines), indents


def assemble_family_tree(structure: dict) -> tuple[str, list[int]]:
    """가계도 structure → (§6.6.4 골격, 줄별 들여쓰기). 하향식 트리/상향식 평면(전사).

    하향식(top_down, 기본): 선조→후손 트리, 최상위 1칸·하위 +2칸(§6.6.4(2)②).
    상향식(bottom_up): 후손→선조 평면 목록, 각 항목 3칸(§6.6.4(3)②).
    결혼·관계 기호·상향식 부모 번호는 점역사 확인 후 배선 — 점역자 주로만 알린다(§6.6.4(2)④·(3)④).
    """
    lines: list[str] = []
    indents: list[int] = []
    title = (structure.get("title") or "").strip()
    if title:
        lines.append(title); indents.append(_TITLE_INDENT)                  # §6.3.3(1)

    if (structure.get("mode") or "top_down").strip() == "bottom_up":
        lines.append("<!점역자주>가계도(상향식): 후손에서 선조 순<!/점역자주>"); indents.append(0)
        for it in structure.get("items") or []:                             # §6.6.4(3)①
            t = (it.get("text") or "").strip()
            if t:
                lines.append(t); indents.append(_BOTTOMUP_INDENT)           # §6.6.4(3)②
    else:
        lines.append("<!점역자주>가계도(하향식): 선조에서 후손 순<!/점역자주>"); indents.append(0)
        _flatten_hier(structure.get("nodes") or [], 0, lines, indents)      # §6.6.4(2)①②
    return "\n".join(lines), indents


# ── 연대표(§6.6.6) ────────────────────────────────────────────────────────────

def _group_timeline(events: list) -> list[tuple[str, list[str]]]:
    """연속 동일 날짜 사건을 묶는다(§6.6.6(4) 동일 연도 다수 처리용). 순서 보존."""
    groups: list[tuple[str, list[str]]] = []
    for ev in events:
        date = str(ev.get("date", "")).strip()
        text = (ev.get("text") or "").strip()
        if groups and groups[-1][0] == date:
            groups[-1][1].append(text)
        else:
            groups.append((date, [text]))
    return groups


def assemble_timeline(structure: dict) -> tuple[str, list[int]]:
    """연대표 structure → (§6.6.6 골격, 줄별 들여쓰기). 시간순·동일 연도 5/3칸(전사)."""
    lines: list[str] = []
    indents: list[int] = []
    title = (structure.get("title") or "").strip()
    if title:
        lines.append(title); indents.append(_TITLE_INDENT)                  # §6.3.3(1)
    lines.append("<!점역자주>연대표<!/점역자주>"); indents.append(0)        # §6.3.4(1)

    for date, texts in _group_timeline(structure.get("events") or []):
        texts = [t for t in texts if t]
        if not texts:                                                       # §6.6.6(2)③ 사건 없는 날짜 생략
            continue
        if len(texts) == 1:
            lines.append(f"{date} {texts[0]}".strip()); indents.append(0)   # §6.6.6(2)②
        else:
            lines.append(date); indents.append(_TIMELINE_YEAR)              # §6.6.6(4) 연도 5칸
            for t in texts:
                lines.append(t); indents.append(_TIMELINE_EVENT)            # 사건 3칸
    return "\n".join(lines), indents


# ── 양식(§6.6.3) · 화면 이미지(§6.6.7) — 글상자 ──────────────────────────────

def assemble_form(structure: dict) -> tuple[str, list[int]]:
    """양식 structure → (§6.6.3 골격, 줄별 들여쓰기). 글상자·한 줄 한 항목(전사).

    밑줄 빈칸 글리프(§6.6.3(4))는 점역사 확인 후 배선 — 현재는 항목 텍스트만 전사.
    빈칸 길이 정보(§6.6.3(5))는 item.note를 점역자 주로 적는다.
    """
    lines: list[str] = []
    indents: list[int] = []
    title = (structure.get("title") or "").strip()
    if title:
        lines.append(title); indents.append(_TITLE_INDENT)                  # §6.3.3(1)
    lines.append("<!점역자주>양식<!/점역자주>"); indents.append(0)          # §6.3.4(1)
    lines.append(_BOX_TOP); indents.append(0)                               # §6.6.3(2) 글상자
    for it in structure.get("items") or []:
        t = (it.get("text") or it.get("label") or "").strip()
        if t:
            lines.append(t); indents.append(0)                              # §6.6.3(3) 한 줄에 하나
        note = (it.get("note") or "").strip()
        if note:                                                            # §6.6.3(5) 빈칸 길이 정보
            lines.append(f"<!점역자주>{note}<!/점역자주>"); indents.append(0)
    lines.append(_BOX_BOTTOM); indents.append(0)
    return "\n".join(lines), indents


def assemble_screen_image(structure: dict) -> tuple[str, list[int]]:
    """화면 이미지 structure → (§6.6.7 골격, 줄별 들여쓰기). 글상자·구획별 표기(전사).

    색깔 단서(§6.6.7(2))·하이퍼링크 표시(§6.6.7(3)③)는 점역사 확인 후 배선 — 점역자 주만.
    """
    lines: list[str] = []
    indents: list[int] = []
    title = (structure.get("title") or "").strip()
    if title:
        lines.append(title); indents.append(_TITLE_INDENT)                  # §6.3.3(1)
    lines.append("<!점역자주>화면 이미지<!/점역자주>"); indents.append(0)  # §6.3.4(1)
    lines.append(_BOX_TOP); indents.append(0)                               # §6.6.7(1) 글상자 테두리
    for sec in structure.get("sections") or []:
        name = (sec.get("name") or "").strip()
        if name:
            lines.append(name); indents.append(0)                           # §6.6.7(3)① 구획별
        for ln in sec.get("lines") or []:
            ln = str(ln).strip()
            if ln:
                lines.append(ln); indents.append(_SCREEN_SECTION_BODY)
    lines.append(_BOX_BOTTOM); indents.append(0)
    return "\n".join(lines), indents


# ── 발표용 슬라이드(§6.6.8) ──────────────────────────────────────────────────

def assemble_slide(structure: dict) -> tuple[str, list[int]]:
    """발표용 슬라이드 structure → (§6.6.8 골격, 줄별 들여쓰기). 제목·들여쓰기·노트(전사).

    슬라이드 번호(§6.6.8(1))는 layout 페이지 기구 담당. 노트(§6.6.8(3))는 점역자 주로 같은 줄에.
    """
    lines: list[str] = []
    indents: list[int] = []
    title = (structure.get("title") or "").strip()
    if title:
        lines.append(title); indents.append(_TITLE_INDENT)                  # §6.3.3(1)
    lines.append("<!점역자주>발표용 슬라이드<!/점역자주>"); indents.append(0)  # §6.3.4(1)
    for it in structure.get("items") or []:                                 # §6.6.8(2)
        t = (it.get("text") or "").strip()
        if t:
            lvl = int(it.get("level", 0) or 0)
            lines.append(t); indents.append(_HIER_STEP * lvl)
    note = (structure.get("note") or "").strip()
    if note:
        lines.append(f"<!점역자주>노트: {note}<!/점역자주>"); indents.append(0)  # §6.6.8(3)
    return "\n".join(lines), indents


# ── opt ──────────────────────────────────────────────────────────────────────

# subtype → (assemble 함수, structure 유효성 검사). 데이터 없으면 caption 폴백.
_ASSEMBLERS = {
    "concept_map":  (assemble_concept_map,  lambda s: bool(s.get("nodes"))),
    "flowchart":    (assemble_flowchart,    lambda s: bool(s.get("boxes"))),
    "org_chart":    (assemble_org_chart,    lambda s: bool(s.get("nodes"))),
    "family_tree":  (assemble_family_tree,  lambda s: bool(s.get("nodes") or s.get("items"))),
    "timeline":     (assemble_timeline,     lambda s: bool(s.get("events"))),
    "form":         (assemble_form,         lambda s: bool(s.get("items"))),
    "screen_image": (assemble_screen_image, lambda s: bool(s.get("sections"))),
    "slide":        (assemble_slide,        lambda s: bool(s.get("items") or s.get("note"))),
}


_TAG_RE = re.compile(r"<!(/?)([^>]+)>")


def _skeleton_prose(text: str) -> str:
    """§6.6 골격 텍스트 → 줄글(태그·글상자 테두리 제거 후 항목을 쉼표로 이음). rule-based."""
    parts: list[str] = []
    for ln in text.split("\n"):
        clean = _TAG_RE.sub("", ln).strip()
        if clean and not set(clean) <= {"⠿", " "}:   # 빈 테두리 줄 제외
            parts.append(clean)
    return ", ".join(parts)


class DiagramOpt(BaseOpt):
    """ExtractedContent 목록 → LLMOutput 목록 (개념도·흐름도 등 도표). 대체텍스트 4안.

    도표는 구조가 §6.6 골격(개조식)으로 결정적 전사되므로 개조식 초안은 그 골격을 그대로 쓰고,
    생략·짧은 제목·줄글을 더해 4안을 만든다(모두 rule-based — 구조가 있으면 LLM 미사용).
    구조가 없으면 캡션으로 공통 4안 빌더에 위임(제목·개조식·줄글을 LLM이 채움).
    """

    async def _optimize_one(self, ext: ExtractedContent, routing_tier: str) -> LLMOutput:
        structure = ext.structure or {}
        subtype = _subtype(ext)
        label = _TYPE_LABEL.get(subtype, "도표")
        title = (structure.get("title") or "").strip()

        assembled: Optional[tuple[str, list[int]]] = None
        entry = _ASSEMBLERS.get(subtype)
        if entry is not None and entry[1](structure):
            assembled = entry[0](structure)

        if assembled is not None:
            skeleton_text, skeleton_indents = assembled
            # 개조식 = §6.6 골격 그대로(글상자 테두리·정밀 들여쓰기 보존). 나머지 3안은 파생.
            drafts = [
                omission_draft(label),
                title_draft(label, title),
                Draft(option=3, text=skeleton_text, render_mode="narrative", label=LABELS[OUTLINE_IDX]),
                prose_draft(label, _skeleton_prose(skeleton_text)),
            ]
            return LLMOutput(
                element_id=ext.element_id,
                corrected_text=skeleton_text,
                render_mode="narrative",
                tn_text=skeleton_text,
                routing_tier=routing_tier,
                processing_time_ms=0,
                rule_trail=_min_trail(skeleton_text),
                drafts=drafts,
                selected_idx=OUTLINE_IDX,
                line_indents=skeleton_indents,
            )

        # 폴백: 구조 없음 → 캡션으로 공통 4안 빌더(제목·개조식·줄글 LLM)
        cap = (ext.corrected_text or "").strip()
        if not cap:
            return LLMOutput(
                element_id=ext.element_id,
                corrected_text="[처리 불가: 도표 캡션 없음]",
                render_mode="narrative",
                routing_tier="FALLBACK",
                processing_time_ms=0,
                rule_trail=_min_trail(""),
            )
        drafts, selected_idx, line_indents, tier = await build_visual_drafts(
            ext, routing_tier, label=label, caption=cap, kind="도표",
        )
        return LLMOutput(
            element_id=ext.element_id,
            corrected_text=drafts[selected_idx].text,
            render_mode="narrative",
            tn_text=drafts[selected_idx].text,
            routing_tier=tier,
            processing_time_ms=0,
            rule_trail=_min_trail(drafts[selected_idx].text),
            drafts=drafts,
            selected_idx=selected_idx,
            line_indents=line_indents,
        )
