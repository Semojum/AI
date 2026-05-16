"""PART 4-3 — 텍스트 점역 (규칙 기반).

LLMOutput.corrected_text → translator.translate_tagged_text() → BrailleOutput
"""

from __future__ import annotations

from app.ai.braille.translator import translate_tagged_text
from app.schemas.content import BrailleOutput, LLMOutput, RuleApplication

_RULE_LINE_WRAP = RuleApplication(
    rule_id="KBR-2.1.1",
    source="한국 점자 규정",
    section="2.1.1",
    title="줄 길이",
    excerpt="한 줄은 32칸을 넘지 않는다.",
    priority="primary",
)

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
            trail = list(opt.rule_trail) + [_RULE_LINE_WRAP]
            results.append(BrailleOutput(
                element_id=opt.element_id,
                braille_lines=lines,
                rule_trail=trail,
            ))
        return results
