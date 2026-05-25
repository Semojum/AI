"""PART 5-3 — 수식 점역 (kor_math_rules KOR_MATH 엔진)."""

from __future__ import annotations

from app.ai.braille.kor_math_rules import convert_latex
from app.schemas.content import BrailleOutput, LLMOutput, RuleApplication

_RULE_FORMULA = RuleApplication(
    rule_id="KBR-5.1",
    source="한국 점자 규정",
    section="5.1",
    title="수학 점자 기본 원칙",
    excerpt="수학 기호는 수학 점자 규정에 따라 변환한다.",
    priority="primary",
)
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


class FormulaBraille:
    """LLMOutput 목록 → BrailleOutput 목록 (수식)."""

    def translate(self, optimized: list[LLMOutput]) -> list[BrailleOutput]:
        results = []
        for opt in optimized:
            text = opt.corrected_text
            if text.startswith("[처리 불가") or text.startswith("[수식"):
                lines = [text]
            else:
                lines = _split_lines(convert_latex(text))
            trail = list(opt.rule_trail) + [_RULE_FORMULA, _RULE_LINE_WRAP]
            results.append(BrailleOutput(
                element_id=opt.element_id,
                braille_lines=lines,
                rule_trail=trail,
            ))
        return results
