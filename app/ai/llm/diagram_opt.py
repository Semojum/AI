"""PART(도표) — 개념도·흐름도 점역 최적화 (rule-based 골격 조립, §6.6).

규정(점자 자료 제작 지침 §6.6)이 도표의 형식을 결정적 골격으로 정한다 — 자유서술이 아니다.
구조화 입력(structure)에서 코드가 골격을 결정적으로 조립한다(전사).

★ 이 파일의 들여쓰기 값은 전부 **앞 빈칸 수**다(규정의 "N칸" = 빈칸 N-1). 상수 주석 참조.

공통(§6.3.3·§6.3.4):
  제목줄  : 5칸 {제목}                           §6.3.3(1) 시각 자료 제목은 윗줄 5칸
  유형    : <!주>{개념도|흐름도}<!/주> §6.3.4(1) 유형 제시(점역자 주) — 5칸(§2.1.8(3))

개념도(§6.6.1) — 위계가 있는 개조식 항목(들여쓰기):
  2단계: 상위 5칸 · 하위 3칸                      §6.6.1(3)①
  3단계: 최상위 7칸 · 중위 5칸 · 하위 3칸          §6.6.1(3)②
  → 일반화: 깊이 D, 레벨 L(0=최상위)의 빈칸 = 2 + 2*(D-1-L).
    D=2→[4,2]=5칸/3칸, D=3→[6,4,2]=7/5/3칸 (규정 일치). D≥4는 같은 규칙으로 외삽.

흐름도(§6.6.2) — 텍스트 점역 모드(그래픽 점역 모드는 촉각 그래픽이라 본 파이프라인 범위 밖):
  ①논리 순서로 상자에 번호(시작=1)  ③번호+도형기호(빈칸X)+한칸+내용  ④상자 한 줄에 하나
  ⑤분기 선택지 줄바꿈  ⑥선택지 3칸: 3o(반직선) 선택사항 3o 목적지
  ※ 반직선 `3o`(=⠒⠕)는 정답 예6-19로 확인돼 배선했다(→, symbol_table 화살표).
  ※ 도형 점형(@$R 등)은 어느 상자가 무슨 도형인지 앞단이 안 줘서 못 적는다 — 입력이 없는
    것이지 글리프를 몰라서가 아니다(디코드 표는 diagram_braille._FLOW_SHAPE_ASCII 주석).

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
from app.ai.llm.diagram_structure import structure_from_caption, subtype_from_caption
from app.ai.braille import tag_names as _TN
from app.ai.braille import tn_notices as _TN_NOTICES
from app.ai.llm.visual_drafts import (
    DESC_IDX,
    LABELS,
    _dedupe,
    build_visual_drafts,
    extra_drafts,
    omission_draft,
)
from app.core.model_manager import model_manager  # noqa: F401 (단위 테스트가 이 네임스페이스를 patch)
from app.schemas.content import Draft, ExtractedContent, LLMOutput, RuleApplication

_RULE_ID = "JAJAK-6.6.1"   # 도표 골격 (점자 자료 제작 지침 §6.6)
# ★ 단위 = **앞 빈칸 수**. 규정의 "N칸에서 시작"은 앞 빈칸 N-1이다.
#   `line_indents`를 소비하는 곳이 `" " * indent + line`로 쓰기 때문(layout_braille._indent_lines,
#   같은 파일 `_PARA_INDENT = 2  # "3칸에서 시작" = 앞 빈칸 2`). 2026-08-09 이전에는 여기 상수가
#   칸 번호(5·3·1)로 들어 있어 8종 전부가 한 칸씩 오른쪽으로 밀려 나갔다 — 규정 정답 쌍
#   (test_data/regulation_visual, 지침 예6-18~6-25) 대조로 확인.
#
# ⚠ **개념도만 실물 정답 근거가 없다.** 정본의 예6-18(개념도)에 붙은 점자 15줄은 실제로는
#   pdf_page 138 것이고(비고에 그렇게 적혀 있다) 풀어 보면 `① 입력 / ② 웹 서버의 IP 제공 /
#   ③ IP로 접속`이라 개념도인지 흐름도인지 판정이 안 선다. 2026-08-09 정본 재구축(정규식→비전)
#   때 쪽경계 복구가 끌어온 것으로 보인다.
#   그래서 개념도 위계(7/5/3칸 → 앞 빈칸 6/4/2)는 **§6.6.1 조문으로만** 세웠다.
#   실물로 확정하려면 지침 p137~138 원문을 눈으로 봐야 한다.
_TITLE_INDENT = 4         # §6.3.3(1) 제목 5칸      — 정답 예6-25[0]
_TYPE_NOTE_INDENT = 4     # §2.1.8(3) 시각 자료 설명 점역자 주 5칸 — 정답 예6-1·6-7·6-8[0]
_NOTE_INDENT = 2          # 형식 안내 점역자 주 3칸 — 정답 예6-19·6-22·6-23·6-24·6-25
_ITEM_INDENT = 2          # 규정이 칸을 안 정한 유형(양식·연대표·화면이미지·슬라이드)의 항목 3칸
_BRANCH_INDENT = 2        # §6.6.2(4)⑥ 선택지 3칸   — 정답 예6-19
_HIER_BASE = 0            # §6.6.5(2)·§6.6.4(2)② 최상위 1칸 — 정답 예6-21·6-22
_HIER_STEP = 2            # 하위 단계마다 +2칸
_BOTTOMUP_INDENT = 2      # §6.6.4(3)② 상향식 가계도 항목 3칸
_TIMELINE_YEAR = 4        # §6.6.6(4) 동일 연도 연도줄 5칸
_TIMELINE_EVENT = 2       # §6.6.6(4) 동일 연도 사건줄 3칸
_FLOW_ARROW = "→"         # §6.6.2(4)⑥ 반직선 `3o`(⠒⠕) — symbol_table 화살표 항목이 점역
_BOX_TOP = "<!상자><!/상자>"      # 글상자 위 테두리(빈 제목 쌍) — layout 재렌더
_BOX_BOTTOM = "<!상자끝><!/상자끝>"  # 글상자 아래 테두리
_TYPE_LABEL = {
    "concept_map": "개념도", "flowchart": "흐름도",
    "org_chart": "조직도", "family_tree": "가계도", "timeline": "연대표",
    "form": "양식", "screen_image": "화면 이미지", "slide": "발표용 슬라이드",
}


# subtype → 그 골격을 정한 조항. ★ Step17(2026-08-08) 이전에는 **전부** _RULE_ID(개념도
# §6.6.1)로 나갔다 — dev 400쪽 실측 JAJAK-6.6.1 42건 / 6.6.2(흐름도) 0건. 흐름도를 보면서
# "개념도 조항"이 근거로 붙는 셈이라 점역사에게는 틀린 근거였다. 8종을 각자 조항으로 가른다.
_SUBTYPE_RULE = {
    "concept_map": "JAJAK-6.6.1", "flowchart": "JAJAK-6.6.2", "form": "JAJAK-6.6.3",
    "family_tree": "JAJAK-6.6.4", "org_chart": "JAJAK-6.6.5", "timeline": "JAJAK-6.6.6",
    "screen_image": "JAJAK-6.6.7", "slide": "JAJAK-6.6.8",
}


def _min_trail(subtype: str, how: str) -> list[RuleApplication]:
    """도표 근거 — 어느 subtype으로 보고 어떻게 만들었는지(Step17).

    subtype 판정은 앞단 신호가 없을 때 캡션 첫 줄에서 우리가 **추측한 것**이고
    (`diagram_structure.subtype_from_caption`), 들여쓰기(개념도 5/3·조직도 1칸+2칸/단계)는
    그 판정에 딸려 결정된다. 판정이 틀리면 골격 전체가 틀리므로 점역사가 제일 먼저 볼 자리다.
    how = "골격 조립"(structure에서 결정적 전사) | "캡션 3안"(구조 없어 캡션으로 폴백).
    """
    rule_id = _SUBTYPE_RULE.get(subtype, _RULE_ID)
    label = _TYPE_LABEL.get(subtype, "도표")
    return [make_rule(rule_id, tag=f"{label}·{how}")]


def _subtype(ext: ExtractedContent) -> str:
    """세분류 판별 — structure.subtype > visual_subtype > 캡션 첫 줄의 유형어."""
    st = ext.structure or {}
    sub = (st.get("subtype") or ext.visual_subtype or "").strip()
    return sub or subtype_from_caption(ext.corrected_text or "")


def _structure(ext: ExtractedContent, subtype: str) -> dict:
    """골격 입력 — 앞단이 준 structure 우선, 없으면 캡션을 파싱해 만든다.

    앞단(MinerU·분류기)은 도표 내부 구조를 내지 않아 `_ASSEMBLERS`가 한 번도 돈 적이 없었다
    (경계 JSON 실측 2026-08-08: structure 0건). 캡션은 이미 위계 줄을 갖고 있으므로
    거기서 만든다 — `diagram_structure` 참조. 못 만들면 {} → 캡션 3안 폴백(종전 동작).
    """
    if ext.structure:
        return ext.structure
    return structure_from_caption(ext.corrected_text or "", subtype) or {}


# ── 개념도 (§6.6.1) ──────────────────────────────────────────────────────────

def _tree_depth(nodes: list) -> int:
    """노드 트리의 최대 깊이(빈 트리=0)."""
    if not nodes:
        return 0
    return 1 + max((_tree_depth(n.get("children") or []) for n in nodes), default=0)


def _concept_indent(level: int, depth: int) -> int:
    """레벨(0=최상위)·전체 깊이 → 앞 빈칸(§6.6.1(3)). 하위=3칸(빈칸2), 위로 갈수록 +2."""
    return 2 + 2 * (depth - 1 - level)


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
    lines.append("<!주>개념도<!/주>:"); indents.append(_TYPE_NOTE_INDENT)        # §6.3.4(1)

    depth = _tree_depth(nodes)
    _flatten_concept(nodes, 0, depth, lines, indents)                        # §6.6.1(2)(3)
    return "\n".join(lines), indents


# ── 흐름도 (§6.6.2) — 구조 골격만(도형 점형 보류) ─────────────────────────────

def assemble_flowchart(structure: dict) -> tuple[str, list[int]]:
    """흐름도 structure → (§6.6.2(4) 구조 골격, 줄별 들여쓰기). rule-based.

    번호+내용을 한 줄에 하나씩, 분기 선택지는 3칸에 한 줄씩 적는다(§6.6.2(4)①④⑤).
    도형 점형(③의 도형기호)은 앞단이 상자별 도형을 안 줘서 생략(입력 부재).
    """
    title = (structure.get("title") or "").strip()
    boxes = structure.get("boxes") or []
    lines: list[str] = []
    indents: list[int] = []

    if title:
        lines.append(title); indents.append(_TITLE_INDENT)                  # §6.3.3(1)
    lines.append("<!주>흐름도<!/주>:"); indents.append(_TYPE_NOTE_INDENT)        # §6.3.4(1)

    for box in boxes:
        no = box.get("no", "")
        text = (box.get("text") or "").strip()
        # §6.6.2(4)③④ — 번호 + (도형기호: 보류) + 내용, 상자 한 줄에 하나
        lines.append(f"{no} {text}".strip()); indents.append(0)
        for br in box.get("branches") or []:                                # §6.6.2(4)⑤⑥
            label = (br.get("label") or "").strip()
            to = str(br.get("to", "")).strip()
            # §6.6.2(4)⑥ "3칸에 3o을 적고, 한 칸 띄어 선택사항, 그 후 3o과 목적지" — 정답 예6-19
            parts = [_FLOW_ARROW, label, _FLOW_ARROW, to] if to else [_FLOW_ARROW, label]
            lines.append(" ".join(p for p in parts if p))
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
    lines.append("<!주>조직도<!/주>:"); indents.append(_TYPE_NOTE_INDENT)
    # ★ 2026-08-12 — 칸 수를 밝힌다. 정본(자료지침 예6-22)은 "하위에 속한 기구를 **2칸씩**
    #   들여 쓰기함"이라고 쓴다. 점자에는 선·상자가 없어 위계가 들여쓰기로만 남는데,
    #   몇 칸이 한 단계인지 말해 주지 않으면 독자는 빈칸을 세도 단계를 못 센다.
    lines.append(_TN.tn(_TN_NOTICES.indent_hierarchy(_HIER_STEP, "기구")))
    indents.append(_NOTE_INDENT)
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
        lines.append("<!주>가계도<!/주>:"); indents.append(_TYPE_NOTE_INDENT)
        lines.append("<!주>후손에서 선조 순(상향식)<!/주>"); indents.append(_NOTE_INDENT)
        for it in structure.get("items") or []:                             # §6.6.4(3)①
            t = (it.get("text") or "").strip()
            if t:
                lines.append(t); indents.append(_BOTTOMUP_INDENT)           # §6.6.4(3)②
    else:
        lines.append("<!주>가계도<!/주>:"); indents.append(_TYPE_NOTE_INDENT)
        lines.append("<!주>선조에서 후손 순(하향식)<!/주>"); indents.append(_NOTE_INDENT)
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
    lines.append("<!주>연대표<!/주>:"); indents.append(_TYPE_NOTE_INDENT)        # §6.3.4(1)

    for date, texts in _group_timeline(structure.get("events") or []):
        texts = [t for t in texts if t]
        if not texts:                                                       # §6.6.6(2)③ 사건 없는 날짜 생략
            continue
        if len(texts) == 1:
            lines.append(f"{date} {texts[0]}".strip()); indents.append(_ITEM_INDENT)  # §6.6.6(2)②·예6-23
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
    lines.append("<!주>양식<!/주>:"); indents.append(_TYPE_NOTE_INDENT)          # §6.3.4(1)
    lines.append(_BOX_TOP); indents.append(0)                               # §6.6.3(2) 글상자
    for it in structure.get("items") or []:
        t = (it.get("text") or it.get("label") or "").strip()
        if t:
            lines.append(t); indents.append(_ITEM_INDENT)                   # §6.6.3(3) 한 줄에 하나·예6-20
        note = (it.get("note") or "").strip()
        if note:                                                            # §6.6.3(5) 빈칸 길이 정보
            lines.append(f"<!주>{note}<!/주>"); indents.append(_NOTE_INDENT)
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
    lines.append("<!주>화면 이미지<!/주>:"); indents.append(_TYPE_NOTE_INDENT)  # §6.3.4(1)
    lines.append(_BOX_TOP); indents.append(0)                               # §6.6.7(1) 글상자 테두리
    # §6.6.7(3)① 구획별 표기 — 구획은 **빈 줄**로 가르고 내용은 전부 3칸(정답 예6-24).
    # 종전에는 구획명 1칸·내용 3칸으로 층을 뒀는데 정답에는 그런 층이 없다.
    for i, sec in enumerate(structure.get("sections") or []):
        if i:
            lines.append(""); indents.append(0)
        name = (sec.get("name") or "").strip()
        if name:
            lines.append(name); indents.append(_ITEM_INDENT)
        for ln in sec.get("lines") or []:
            ln = str(ln).strip()
            if ln:
                lines.append(ln); indents.append(_ITEM_INDENT)
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
    lines.append("<!주>발표용 슬라이드<!/주>:"); indents.append(_TYPE_NOTE_INDENT)  # §6.3.4(1)
    for it in structure.get("items") or []:                                 # §6.6.8(2)
        t = (it.get("text") or "").strip()
        if t:
            lvl = int(it.get("level", 0) or 0)
            lines.append(t); indents.append(_ITEM_INDENT + _HIER_STEP * lvl)  # 예6-25 항목 3칸
    note = (structure.get("note") or "").strip()
    if note:                                                                # §6.6.8(3)·예6-25
        lines.append(f"<!주>노트: {note}<!/주>"); indents.append(_NOTE_INDENT)
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
    """ExtractedContent 목록 → LLMOutput 목록 (개념도·흐름도 등 도표). 대체텍스트 3안.

    도표는 구조가 §6.6 골격(개조식)으로 결정적 전사되므로 개조식 초안은 그 골격을 그대로 쓰고,
    생략·참조를 더해 3안을 만든다(모두 rule-based — 구조가 있으면 LLM 미사용).
    구조가 없으면 캡션으로 공통 3안 빌더에 위임(설명을 LLM이 채움).
    """

    async def _optimize_one(self, ext: ExtractedContent, routing_tier: str) -> LLMOutput:
        subtype = _subtype(ext)
        structure = _structure(ext, subtype)
        label = _TYPE_LABEL.get(subtype, "도표")
        title = (structure.get("title") or "").strip()

        assembled: Optional[tuple[str, list[int]]] = None
        entry = _ASSEMBLERS.get(subtype)
        if entry is not None and entry[1](structure):
            assembled = entry[0](structure)

        if assembled is not None:
            skeleton_text, skeleton_indents = assembled
            # 설명 = §6.6 골격 그대로(글상자 테두리·정밀 들여쓰기 보존).
            # ★ 2026-08-20 — 짧은 제목·줄글·유형만을 뺐다. 규정은 "설명" 하나이고
            #   gold 실측에서 '유형만'이 0건이다(visual_drafts.LABELS 주석 참조).
            drafts = [
                omission_draft(label),
                Draft(option=2, text=skeleton_text, render_mode="narrative", label=LABELS[DESC_IDX]),
                *extra_drafts(label),
            ]
            # 골격 경로는 build_visual_drafts를 안 타므로 접기를 여기서 직접 부른다.
            drafts, sel_idx = _dedupe(drafts, DESC_IDX)
            return LLMOutput(
                element_id=ext.element_id,
                corrected_text=skeleton_text,
                render_mode="narrative",
                tn_text=skeleton_text,
                routing_tier=routing_tier,
                processing_time_ms=0,
                rule_trail=_min_trail(subtype, "골격 조립"),
                drafts=drafts,
                selected_idx=sel_idx,
                # 설명 안이 선택됐을 때만 골격 들여쓰기를 넘긴다.
                # ★ option 번호가 아니라 **라벨**로 찾는다(2026-08-20). 6안→3안으로 줄이며
                #   설명 안의 option이 3에서 2로 바뀌었는데 여기가 3을 찾고 있어 터졌다.
                line_indents=skeleton_indents if (
                    0 <= sel_idx < len(drafts)
                    and drafts[sel_idx].label == LABELS[DESC_IDX]) else None,
            )

        # 폴백: 구조 없음 → 캡션으로 공통 3안 빌더(설명 LLM)
        cap = (ext.corrected_text or "").strip()
        if not cap:
            return LLMOutput(
                element_id=ext.element_id,
                # ★ 2026-08-12 — 종전엔 "[처리 불가: 도표 캡션 없음]"을 냈다. 그 한글 열 글자가
                #   **그대로 점자로 찍혀 학생에게 나갔고**, drafts가 0개라 점역사 피커에는
                #   아무것도 안 떴다(생략조차 없었다). 재료가 없을 때의 정답은 생략 표기다
                #   (§6.3.4(2)②) — `build_visual_drafts`의 무-재료 경로와 같은 결론이다.
                corrected_text=omission_draft(label).text,
                render_mode="narrative",
                routing_tier=routing_tier,
                processing_time_ms=0,
                rule_trail=_min_trail(subtype, "캡션 없음 — 생략 표기"),
                drafts=[omission_draft(label)],
                selected_idx=0,
            )
        drafts, selected_idx, line_indents, tier, cap_src = await build_visual_drafts(
            ext, routing_tier, label=label, caption=cap, kind="도표",
        )
        return LLMOutput(
            element_id=ext.element_id,
            corrected_text=drafts[selected_idx].text,
            render_mode="narrative",
            tn_text=drafts[selected_idx].text,
            routing_tier=tier,
            processing_time_ms=0,
            rule_trail=_min_trail(subtype, f"캡션 3안 · {cap_src}"),
            drafts=drafts,
            selected_idx=selected_idx,
            line_indents=line_indents,
        )
