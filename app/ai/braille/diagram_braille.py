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


class DiagramBraille:
    """LLMOutput 목록 → BrailleOutput 목록 (개념도·흐름도). 단일 출력(줄별 들여쓰기)."""

    def translate(self, optimized: list[LLMOutput]) -> list[BrailleOutput]:
        # 요소별 격리: 한 도표 점역 실패가 다른 요소를 막지 않는다.
        return safe_translate(optimized, self._translate_one)

    def _translate_one(self, opt: LLMOutput) -> BrailleOutput:
        src = opt.tn_text or opt.corrected_text
        lines, breaks = _to_braille(src)
        # 규정 골격(개념도 위계 5/3·7/5/3, 제목 5칸) 줄별 들여쓰기를 layout에 전달(줄 수 일치 시).
        line_indents = (opt.line_indents
                        if opt.line_indents is not None and len(opt.line_indents) == len(lines)
                        else None)
        return BrailleOutput(
            element_id=opt.element_id,
            braille_lines=lines,
            break_points=breaks,
            rule_trail=_base_trail(lines, src),
            box_borders=_box_borders(src),
            line_indents=line_indents,
        )
