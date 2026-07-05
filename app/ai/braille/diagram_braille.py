"""PART(도표) — 개념도·흐름도 점역 (골격 텍스트 → 점자).

개념도·흐름도 골격은 자유서술이 아니라 줄별 들여쓰기(개조식·번호)를 가진 단일 출력이다.
점역자 주 마커(⠠⠄)·줄별 들여쓰기(§6.6.1·§6.3.3)를 layout에 전달한다(cartoon과 동일 패턴).

흐름도 도형 점형(§6.6.2(3))·반직선 점형(§6.6.2(4)⑥의 3o)은 **점역사 확인 후 배선**한다.
아래는 문서(점자 자료 제작 지침 §6.6.2(3) + 한국 점자 규정 제38·70항)의 Braille ASCII 표기를
유니코드로 디코드한 표 — 검증 전이므로 코드에 배선하지 않는다(추측 금지, 태민 2026-06-08).

  _FLOW_SHAPE_ASCII = {
      "ellipse":   ("@$OV", "⠈⠫⠕⠧"),   # 타원형
      "rectangle": ("@$R",  "⠈⠫⠗"),    # 직사각형
      "tri_pair":  ("@$TT", "⠈⠫⠞⠞"),   # 삼각형이 위아래로 붙은 모양
      "diamond":   ("@$D",  "⠈⠫⠙"),    # 마름모
      "inv_tri":   ("@$M",  "⠈⠫⠍"),    # 역삼각형
      "wave_rect": ("@$IO", "⠈⠫⠊⠕"),   # 아랫변이 물결모양인 사각형
  }
  _FLOW_ARROW = ("3o", "⠒⠕")           # 반직선/화살표(→) 제38·70항
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
    """점역자 주 마커(BBPG-1.2.6)·내용 기호 규칙만 점자 좌표로 emit(태민 정책: 내용 변환만)."""
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
    if line_indents is not None and len(line_indents) == len(lines):
        return line_indents
    return None


class DiagramBraille:
    """LLMOutput 목록 → BrailleOutput 목록 (개념도·흐름도 등 도표). 대체텍스트 4안별 점역."""

    def translate(self, optimized: list[LLMOutput]) -> list[BrailleOutput]:
        # 요소별 격리: 한 도표 점역 실패가 다른 요소를 막지 않는다.
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
            # 개조식(선택 초안)은 §6.6 골격 들여쓰기(line_indents)를 유지, 나머지는 단순 줄바꿈.
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
        # 단일(구조 없음·처리 불가 폴백)
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
