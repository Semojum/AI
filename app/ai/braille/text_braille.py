"""PART 4-3 — 텍스트 점역 (규칙 기반).

LLMOutput.corrected_text → translator.translate_tagged_text() → BrailleOutput
"""

from __future__ import annotations

from app.ai.braille.isolation import safe_translate
from app.ai.braille.regulations import make_rule_at
from app.ai.braille.symbol_rules import symbol_rule_spans
from app.ai.braille.translator import (
    _BLANK_TAG_RULE,
    blank_marker_spans,
    box_borders_from_source,
    emphasis_marker_spans,
    translate_with_breaks,
    tn_marker_spans,
)
from app.schemas.content import BoxBorder, BrailleOutput, LLMOutput, RuleApplication

def content_rules(source: str, lines: list[str]) -> list[RuleApplication]:
    """★ Step17(2026-08-08 대표 지시) — 수표·문장부호 포괄 규정을 더 이상 달지 않는다.

    종전 emit(dev 400쪽 실측):
      · MCST-5.11.40 수표 ⠼ — **14,179회.** "숫자는 수표를 앞세운다"는 점역사에게 자명하고
        고를 여지가 없다(기계적 변환). 판정 기준의 '뺄 것' 예시 그대로다.
      · MCST-6.13.49 문장부호 블록(line_no=-1) — **12,192회.** 같은 요소에 기호별 span
        (tag=symbol) 13,417회가 이미 붙는데 블록 규정이 한 번 더 붙었다 — '같은 줄 중복'.
    둘을 합치면 전체 55,639건 중 **26,371건(47%)**이 이 두 줄에서 나왔다.
    빈 목록을 반환하는 껍데기를 남긴 이유 = table_braille._base_trail이 같이 쓰는 공용
    진입점이라, 나중에 '표 내용에만 필요한 근거'가 생기면 여기 한 곳에 붙이기 위함이다.
    """
    return []


class TextBraille:
    """LLMOutput 목록 → BrailleOutput 목록."""

    def translate(self, optimized: list[LLMOutput]) -> list[BrailleOutput]:
        # 요소별 격리: 한 요소 점역 실패가 같은 체인의 다른 요소를 막지 않는다.
        return safe_translate(optimized, self._translate_one)

    def _translate_one(self, opt: LLMOutput) -> BrailleOutput:
        # 논리 줄 + 음절 줄바꿈 offset. 32칸 줄바꿈은 layout이 수행(NLD-1.2.1).
        lines, breaks = translate_with_breaks(opt.corrected_text)
        # braille_text_list 기준 = 점자. rule_trail은 **점역사가 판단해야 할 자리**만 기록한다
        # (Step17 2026-08-08 대표 지시 — 종전 "내용 변환만"에서 좁혔다):
        #   ① 우리가 재량으로 넣은 것(점역자 주·글상자·빈칸 태그)
        #   ② 규정↔관행이 갈리거나 규정끼리 갈리는 기호(symbol_rules._DISCRETIONARY)
        # 포괄 규칙(MCST-0.1)·수표·문장부호 같은 자명한 것은 넣지 않는다. 전부 source-gated.
        joined = "\n".join(lines)
        # 좌표 = 요소-로컬(lines 기준 line_no/col). 원본 태그 유무로 gate —
        # ∽·ː의 ⠠⠄를 점역자 주로 오인하지 않도록(B1).
        trail = [
            make_rule_at("NLD-1.2.6", lines, s, e, tag=tag)
            for s, e, tag in tn_marker_spans(joined, opt.corrected_text)
        ]
        trail += [
            make_rule_at(rule_id, lines, s, e, tag="symbol")
            for s, e, rule_id in symbol_rule_spans(opt.corrected_text, joined)
        ]
        # 드러냄표 ⠠⠤…⠤⠄ (제56항) — 원본 태그 개수 gate(오탐 방지, r12).
        trail += [
            make_rule_at("MCST-한글-6.13.56", lines, s, e, tag=tag)
            for s, e, tag in emphasis_marker_spans(joined, opt.corrected_text)
        ]
        # 빈칸 마커(제73항) — 묵자 □·____를 '채워 넣을 빈칸'으로 본 것은 LLM 태깅의 판단이고,
        # 그 점형은 원장 C-04·C-05·C-06이 자문 대기 중인 관행이다(Step17).
        trail += [
            make_rule_at(_BLANK_TAG_RULE, lines, s, e, tag=tag)
            for s, e, tag in blank_marker_spans(joined, opt.corrected_text)
        ]
        trail += content_rules(opt.corrected_text, lines)
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
