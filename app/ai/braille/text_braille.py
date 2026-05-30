"""PART 4-3 — 텍스트 점역 (규칙 기반).

LLMOutput.corrected_text → translator.translate_tagged_text() → BrailleOutput
"""

from __future__ import annotations

from app.ai.braille.regulations import make_rule
from app.ai.braille.translator import translate_tagged_text
from app.schemas.content import BrailleOutput, LLMOutput

_COLS = 32


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
            # braille_text_list 기준 = 점자. opt.rule_trail(태깅 텍스트 좌표)은
            # text_list가 별도로 보유하므로 여기서 상속하지 않는다(plan §3-4 2벌 독립).
            n = len("\n".join(lines))
            trail = [
                make_rule("KBR-0.1", span_start=0, span_end=n),
                make_rule("BBPG-1.2.1", span_start=0, span_end=n),
            ]
            results.append(BrailleOutput(
                element_id=opt.element_id,
                braille_lines=lines,
                rule_trail=trail,
            ))
        return results
