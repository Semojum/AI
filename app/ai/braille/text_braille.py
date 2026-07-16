"""PART 4-3 — 텍스트 점역 (규칙 기반).

LLMOutput.corrected_text → translator.translate_tagged_text() → BrailleOutput
"""

from __future__ import annotations

import re

from app.ai.braille.isolation import safe_translate
from app.ai.braille.regulations import make_rule, make_rule_at
from app.ai.braille.symbol_rules import symbol_rule_spans
from app.ai.braille.translator import (
    box_borders_from_source,
    translate_with_breaks,
    tn_marker_spans,
)
from app.schemas.content import BoxBorder, BrailleOutput, LLMOutput, RuleApplication

# 인라인 태그(<!이름>) 제거 — 숫자·문장부호 탐지는 점역 대상 '내용'만 본다.
_TAG_TOKEN_RE = re.compile(r"<!(/?)([^>]+)>")
# 문장 부호(원본 기준) — 있으면 문장부호 규정(KBR-6.13.49)을 블록 규정으로 표시.
_PUNCT_RE = re.compile(r"[.?!,;:…·•（）()\[\]{}「」『』“”‘’\"'—~]")
_NUM_INDICATOR = "⠼"   # 수표(kor_math_rules._NUMBER_INDICATOR와 동일)


def _content_rules(source: str, lines: list[str]) -> list[RuleApplication]:
    """점역된 '내용'에 적용된 구체 규정(수표·문장부호)을 rule_trail로 emit.

    포괄 규칙(KBR-0.1)·조판 규칙은 정책상 제외하고(태민 2026-06-01), 점역사가 규정으로
    확인할 실제 변환만 기록한다. FE 규정 패널이 평문에서도 비지 않도록 하는 핵심:
      - 수표(⠼): 원본에 아라비아 숫자가 있으면 출력 점자의 ⠼ 위치를 정밀 span으로(KBR-5.11.40).
      - 문장부호: 원본에 문장부호가 있으면 블록 규정(line_no=-1)으로(KBR-6.13.49).
    """
    clean = _TAG_TOKEN_RE.sub("", source or "")
    joined = "\n".join(lines)
    rules: list[RuleApplication] = []
    if any(ch.isdigit() for ch in clean):   # 수표는 원본에 숫자가 있을 때만(오탐 방지)
        i = joined.find(_NUM_INDICATOR)
        while i != -1:
            rules.append(make_rule_at("KBR-5.11.40", lines, i, i + 1, tag="number_sign"))
            i = joined.find(_NUM_INDICATOR, i + 1)
    if _PUNCT_RE.search(clean):
        rules.append(make_rule("KBR-6.13.49", tag="punctuation"))
    return rules


class TextBraille:
    """LLMOutput 목록 → BrailleOutput 목록."""

    def translate(self, optimized: list[LLMOutput]) -> list[BrailleOutput]:
        # 요소별 격리: 한 요소 점역 실패가 같은 체인의 다른 요소를 막지 않는다.
        return safe_translate(optimized, self._translate_one)

    def _translate_one(self, opt: LLMOutput) -> BrailleOutput:
        # 논리 줄 + 음절 줄바꿈 offset. 32칸 줄바꿈은 layout이 수행(BBPG-1.2.1).
        lines, breaks = translate_with_breaks(opt.corrected_text)
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
        # 수표·문장부호 규정 — 평문에서도 FE 규정 패널이 비지 않게 실제 변환을 기록.
        trail += _content_rules(opt.corrected_text, lines)
        box_borders = [
            BoxBorder(kind=kind, level=level, title=title)
            for kind, level, title in box_borders_from_source(opt.corrected_text)
        ]
        return BrailleOutput(
            element_id=opt.element_id,
            corrected_text=opt.corrected_text,   # layout이 묶인 항목(①②③) 줄머리 판정에 쓴다
            braille_lines=lines,
            break_points=breaks,
            rule_trail=trail,
            box_borders=box_borders,
        )
