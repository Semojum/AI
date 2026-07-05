"""PART 9-3 — 차트/그래프 점역 (점역사주 TN 텍스트 → 점자).

복수 초안(drafts)이 있으면 각 초안을 점역해 Draft.braille_lines를 채우고,
선택 초안(selected_idx)의 점자를 BrailleOutput.braille_lines로 둔다(PART 10 조판용).
"""

from __future__ import annotations

from app.ai.braille.isolation import safe_translate
from app.ai.braille.regulations import make_rule_at
from app.ai.braille.symbol_rules import symbol_rule_spans
from app.ai.braille.translator import (
    box_borders_from_source,
    translate_with_breaks,
    tn_marker_spans,
)
from app.schemas.content import BoxBorder, BrailleOutput, LLMOutput, RuleApplication


def _box_borders(source: str) -> list[BoxBorder]:
    """원본 글상자 테두리 태그 → box_borders(BBPG-1.2.5, layout 재렌더용)."""
    return [BoxBorder(kind=k, level=lv, title=t) for k, lv, t in box_borders_from_source(source)]


def _base_trail(lines: list[str], source: str = "") -> list[RuleApplication]:
    """점역자 주 마커(BBPG-1.2.6)만 점자 좌표로 emit.

    rule_trail은 '내용 변환'만 기록한다(태민 정책 2026-06-01). 포괄·조판 규칙 제외.
    내용 속 특수기호·수식 규칙은 Phase B에서 추가 예정.

    source = 점역 전 원본 텍스트. 원본에 점역자 주 태그가 있을 때만 emit하여
    ∽·ː 등 동일 점형(⠠⠄)을 오인하지 않는다(B1 오탐 방지).
    """
    joined = "\n".join(lines)
    trail = [
        make_rule_at("BBPG-1.2.6", lines, s, e, tag=tag)
        for s, e, tag in tn_marker_spans(joined, source)
    ]
    trail += [
        make_rule_at(rule_id, lines, s, e, tag="symbol")
        for s, e, rule_id in symbol_rule_spans(source, joined)
    ]
    return trail

def _to_braille(text: str) -> tuple[list[str], list[list[int]]]:
    """논리 줄 + 음절 줄바꿈 offset. 32칸 줄바꿈은 layout(BBPG-1.2.1)."""
    if text.startswith("[처리 불가"):
        return [text], [[]]
    return translate_with_breaks(text)


def _match_indents(line_indents, lines):
    """줄별 들여쓰기(규정 골격: 제목 5칸)를 줄 수와 일치할 때만 전달."""
    if line_indents is not None and len(line_indents) == len(lines):
        return line_indents
    return None


class ChartGraphBraille:
    """LLMOutput 목록 → BrailleOutput 목록 (차트/그래프). 초안별 점역."""

    def translate(self, optimized: list[LLMOutput]) -> list[BrailleOutput]:
        # 요소별 격리: 한 차트 점역 실패가 다른 요소를 막지 않는다.
        return safe_translate(optimized, self._translate_one)

    def _translate_one(self, opt: LLMOutput) -> BrailleOutput:
        if opt.drafts:
            out_drafts = []
            draft_breaks: list[list[list[int]]] = []
            for d in opt.drafts:
                d_lines, d_breaks = _to_braille(d.text)
                draft_breaks.append(d_breaks)
                out_drafts.append(d.model_copy(update={
                    "braille_lines": d_lines,
                    "break_points": d_breaks,
                    "rule_trail": _base_trail(d_lines, d.text),
                }))
            sel = opt.selected_idx if 0 <= opt.selected_idx < len(out_drafts) else 0
            return BrailleOutput(
                element_id=opt.element_id,
                braille_lines=out_drafts[sel].braille_lines,
                break_points=draft_breaks[sel],
                rule_trail=list(opt.rule_trail) + list(out_drafts[sel].rule_trail),
                drafts=out_drafts,
                selected_idx=sel,
                box_borders=_box_borders(opt.drafts[sel].text),
                line_indents=_match_indents(opt.line_indents, out_drafts[sel].braille_lines),
            )
        src = opt.tn_text or opt.corrected_text
        lines, breaks = _to_braille(src)
        return BrailleOutput(
            element_id=opt.element_id,
            braille_lines=lines,
            break_points=breaks,
            rule_trail=list(opt.rule_trail) + _base_trail(lines, src),
            box_borders=_box_borders(src),
            line_indents=_match_indents(opt.line_indents, lines),
        )
