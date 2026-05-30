"""PART 7-3 — 이미지 점역 (점역사주 TN 텍스트 → 점자).

복수 초안(drafts)이 있으면 각 초안을 점역해 Draft.braille_lines를 채우고,
선택 초안(selected_idx)의 점자를 BrailleOutput.braille_lines로 둔다(PART 10 조판용).
"""

from __future__ import annotations

from app.ai.braille.regulations import make_rule
from app.ai.braille.translator import translate_tagged_text
from app.schemas.content import BrailleOutput, LLMOutput, RuleApplication


def _base_trail(lines: list[str]) -> list[RuleApplication]:
    """시각자료 일반(BBPG-3.2.1) + 줄바꿈(BBPG-1.2.1)을 점자 출력 전체 범위로 emit.

    braille_text_list 기준 = 점자이므로 opt.rule_trail은 상속하지 않는다(plan §3-4 2벌 독립).
    """
    n = len("\n".join(lines))
    return [
        make_rule("BBPG-3.2.1", span_start=0, span_end=n),
        make_rule("BBPG-1.2.1", span_start=0, span_end=n),
    ]

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


def _to_braille(text: str) -> list[str]:
    if text.startswith("[처리 불가"):
        return [text]
    return _split_lines(translate_tagged_text(text))


class ImageBraille:
    """LLMOutput 목록 → BrailleOutput 목록 (이미지). 초안별 점역."""

    def translate(self, optimized: list[LLMOutput]) -> list[BrailleOutput]:
        results = []
        for opt in optimized:
            if opt.drafts:
                out_drafts = []
                for d in opt.drafts:
                    d_lines = _to_braille(d.text)
                    out_drafts.append(d.model_copy(update={
                        "braille_lines": d_lines,
                        "rule_trail": _base_trail(d_lines),
                    }))
                sel = opt.selected_idx if 0 <= opt.selected_idx < len(out_drafts) else 0
                results.append(BrailleOutput(
                    element_id=opt.element_id,
                    braille_lines=out_drafts[sel].braille_lines,
                    rule_trail=list(out_drafts[sel].rule_trail),
                    drafts=out_drafts,
                    selected_idx=sel,
                ))
            else:  # 단일(처리 불가 등)
                lines = _to_braille(opt.tn_text or opt.corrected_text)
                results.append(BrailleOutput(
                    element_id=opt.element_id,
                    braille_lines=lines,
                    rule_trail=_base_trail(lines),
                ))
        return results
