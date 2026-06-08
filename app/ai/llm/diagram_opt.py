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

구조가 없으면(현주 미구현 등) caption을 단일 점역자주로 폴백한다.
"""

from __future__ import annotations

from typing import Optional

from app.ai.braille.regulations import make_rule
from app.ai.llm.base_opt import BaseOpt
from app.ai.llm.draft_utils import ensure_tn_prefix
from app.core.model_manager import model_manager  # noqa: F401 (단위 테스트가 이 네임스페이스를 patch)
from app.schemas.content import ExtractedContent, LLMOutput, RuleApplication

_RULE_ID = "BBPG-3.2.1"   # 시각자료 일반(도표 골격 근거 §6.6)
_TITLE_INDENT = 5         # §6.3.3(1)
_BRANCH_INDENT = 3        # §6.6.2(4)⑥ 선택지 3칸
_TYPE_LABEL = {"concept_map": "개념도", "flowchart": "흐름도"}


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


# ── opt ──────────────────────────────────────────────────────────────────────

class DiagramOpt(BaseOpt):
    """ExtractedContent 목록 → LLMOutput 목록 (개념도·흐름도). 규정 골격 rule-based 조립(단일 출력)."""

    async def _optimize_one(self, ext: ExtractedContent, routing_tier: str) -> LLMOutput:
        structure = ext.structure or {}
        subtype = _subtype(ext)

        assembled: Optional[tuple[str, list[int]]] = None
        if subtype == "concept_map" and structure.get("nodes"):
            assembled = assemble_concept_map(structure)
        elif subtype == "flowchart" and structure.get("boxes"):
            assembled = assemble_flowchart(structure)

        if assembled is not None:
            text, indents = assembled
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

        # 폴백: 구조 없음 → caption 단일 점역자주(유형 라벨 보존)
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
        label = _TYPE_LABEL.get(subtype, "도표")
        tn = ensure_tn_prefix(f"{label}: {cap}")
        return LLMOutput(
            element_id=ext.element_id,
            corrected_text=tn,
            render_mode="narrative",
            tn_text=tn,
            routing_tier=routing_tier,
            processing_time_ms=0,
            rule_trail=_min_trail(tn),
        )
