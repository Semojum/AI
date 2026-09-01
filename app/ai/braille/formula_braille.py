"""PART 5-3 — 수식 점역 (kor_math_rules KOR_MATH 엔진)."""

from __future__ import annotations

from app.ai.braille.isolation import safe_translate
from app.ai.braille.kor_math_rules import convert_latex, latex_rule_ids
from app.ai.braille.regulations import make_rule
from app.schemas.content import BrailleOutput, LLMOutput


def _space_breaks(s: str) -> list[int]:
    """공백(두 칸 공백 등) 경계 = 줄바꿈 허용 지점. 수식 내부 줄바꿈 규정은 범위 밖."""
    return [i for i, ch in enumerate(s) if ch in (" ", "⠀") and 0 < i < len(s)]


class FormulaBraille:
    """LLMOutput 목록 → BrailleOutput 목록 (수식)."""

    def translate(self, optimized: list[LLMOutput]) -> list[BrailleOutput]:
        # 요소별 격리: 한 수식 점역 실패가 다른 수식을 막지 않는다.
        return safe_translate(optimized, self._translate_one)

    def _translate_one(self, opt: LLMOutput) -> BrailleOutput:
        text = opt.corrected_text
        if text.startswith("[처리 불가") or text.startswith("[수식"):
            lines = [text]
            struct_rules: list[str] = []
        else:
            lines = [convert_latex(text)]   # 논리 줄, 32칸 줄바꿈은 layout
            struct_rules = latex_rule_ids(text)
        breaks = [_space_breaks(ln) for ln in lines]
        # 구조별 rule(분수·근·첨자·로그·극한 등)만 기록 — 요소 전체(line_no=-1).
        # ★ Step17(2026-08-08) — 포괄 규정 MCST-수학-1.1("숫자는 수표를 앞세워 적는다")을 뺐다.
        #   모든 수식 요소에 붙던 자명한 규정이라 정작 봐야 할 구조 판정(제곱 ⠣/⠘⠼2 원장 C-03,
        #   아래첨자 M-02)이 그 밑에 묻혔다.
        trail = [
            make_rule(rule_id, tag="math_struct")
            for rule_id in struct_rules
        ]
        return BrailleOutput(
            element_id=opt.element_id,
            braille_lines=lines,
            break_points=breaks,
            rule_trail=trail,
        )
