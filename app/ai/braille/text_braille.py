"""PART 4-3 — 텍스트 점역 (규칙 기반).

LLMOutput.corrected_text → translator.translate_tagged_text() → BrailleOutput
"""

from __future__ import annotations

from app.ai.braille.regulations import make_rule_at
from app.ai.braille.symbol_rules import symbol_rule_spans
from app.ai.braille.translator import (
    box_borders_from_source,
    translate_tagged_text,
    tn_marker_spans,
)
from app.ai.braille.constants import COLS as _COLS
from app.schemas.content import BoxBorder, BrailleOutput, LLMOutput


def _split_lines(text: str) -> list[str]:
    """32칸 기준 줄 분리."""
    lines: list[str] = []
    buf = ""
    for ch in text:
        if len(buf) >= _COLS:
            lines.append(buf)
            buf = ch
        else:
            buf += ch
    if buf:
        lines.append(buf)
    return lines or [""]


class TextBraille:
    """LLMOutput 목록 → BrailleOutput 목록."""

    def translate(self, optimized: list[LLMOutput]) -> list[BrailleOutput]:
        results = []
        for opt in optimized:
            braille_str = translate_tagged_text(opt.corrected_text)
            lines = _split_lines(braille_str)
            # braille_text_list 기준 = 점자. rule_trail은 '내용 변환'만 기록한다
            # (태민 정책 2026-06-01): 포괄 규칙(KBR-0.1)·조판 규칙(32칸 줄바꿈) 제외.
            # 점역자 주 마커 + 특수기호·수식 규칙 emit (Phase B). 둘 다 source-gated.
            joined = "\n".join(lines)
            # 좌표 = 요소-로컬(lines 기준 line_no/col). 원본 태그 유무로 gate —
            # ∽·ː의 ⠠⠄를 점역자 주로 오인하지 않도록(B1).
            trail = [
                make_rule_at("BBPG-1.2.6", lines, s, e, tag=tag)
                for s, e, tag in tn_marker_spans(joined, opt.corrected_text)
            ]
            trail += [
                make_rule_at(rule_id, lines, s, e, tag="symbol")
                for s, e, rule_id in symbol_rule_spans(opt.corrected_text, joined)
            ]
            box_borders = [
                BoxBorder(kind=kind, level=level, title=title)
                for kind, level, title in box_borders_from_source(opt.corrected_text)
            ]
            results.append(BrailleOutput(
                element_id=opt.element_id,
                braille_lines=lines,
                rule_trail=trail,
                box_borders=box_borders,
            ))
        return results
