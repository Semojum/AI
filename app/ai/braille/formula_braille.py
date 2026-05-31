"""PART 5-3 — 수식 점역 (kor_math_rules KOR_MATH 엔진)."""

from __future__ import annotations

from app.ai.braille.kor_math_rules import convert_latex
from app.ai.braille.regulations import make_rule
from app.schemas.content import BrailleOutput, LLMOutput

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
            # rule_trail은 '내용 변환'만 기록(태민 정책 2026-06-01): 조판 규칙(32칸 줄바꿈) 제외.
            # 수식 일반(KBR-수학-1.1)은 유지. Phase B에서 분수·근·첨자 등 per-construct로 정밀화.
            n = len("\n".join(lines))
            trail = [
                make_rule("KBR-수학-1.1", span_start=0, span_end=n),
            ]
            results.append(BrailleOutput(
                element_id=opt.element_id,
                braille_lines=lines,
                rule_trail=trail,
            ))
        return results
