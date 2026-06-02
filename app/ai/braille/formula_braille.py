"""PART 5-3 — 수식 점역 (kor_math_rules KOR_MATH 엔진)."""

from __future__ import annotations

from app.ai.braille.kor_math_rules import convert_latex, latex_rule_ids
from app.ai.braille.regulations import make_rule
from app.ai.braille.constants import COLS as _COLS
from app.schemas.content import BrailleOutput, LLMOutput


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
                struct_rules: list[str] = []
            else:
                lines = _split_lines(convert_latex(text))
                struct_rules = latex_rule_ids(text)
            # rule_trail은 '내용 변환'만 기록(태민 정책 2026-06-01): 조판 규칙(32칸 줄바꿈) 제외.
            # 수식 일반(KBR-수학-1.1) + 구조별 rule(분수·근·첨자·로그·극한 등, Phase B).
            # 수식 일반·구조 rule은 요소 전체(line_no=-1) — 구조 단위 정밀 좌표는 추후.
            trail = [make_rule("KBR-수학-1.1")]
            trail += [
                make_rule(rule_id, tag="math_struct")
                for rule_id in struct_rules
            ]
            results.append(BrailleOutput(
                element_id=opt.element_id,
                braille_lines=lines,
                rule_trail=trail,
            ))
        return results
