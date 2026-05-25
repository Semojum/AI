"""PART 8-3 — 만화/그림 점역 (점역사주 TN 텍스트 → 점자)."""

from __future__ import annotations

from app.ai.braille.translator import translate_tagged_text
from app.schemas.content import BrailleOutput, LLMOutput, RuleApplication

_RULE_CARTOON = RuleApplication(
    rule_id="KBR-6.4.2",
    source="점자 교과서 제작 지침",
    section="6.4.2",
    title="만화·그림 점역사주 원칙",
    excerpt="만화는 컷 순서, 등장인물, 대화 내용을 순서대로 기술한다.",
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
    lines, buf = [], ""
    for ch in text:
        if len(buf) >= _COLS:
            lines.append(buf)
            buf = ch
        else:
            buf += ch
    if buf:
        lines.append(buf)
    return lines or [""]


class CartoonBraille:
    """LLMOutput 목록 → BrailleOutput 목록 (만화)."""

    def translate(self, optimized: list[LLMOutput]) -> list[BrailleOutput]:
        results = []
        for opt in optimized:
            text = opt.corrected_text
            if text.startswith("[처리 불가"):
                lines = [text]
            else:
                tn = opt.tn_text or text
                lines = _split_lines(translate_tagged_text(tn))
            trail = list(opt.rule_trail) + [_RULE_CARTOON, _RULE_LINE_WRAP]
            results.append(BrailleOutput(
                element_id=opt.element_id,
                braille_lines=lines,
                rule_trail=trail,
            ))
        return results
