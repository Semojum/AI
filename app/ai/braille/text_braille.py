"""PART 4-3 — 텍스트 점역 (규칙 기반).

LLMOutput.corrected_text → translator.translate_tagged_text() → BrailleOutput
"""

from __future__ import annotations

import re

from app.ai.braille.isolation import safe_translate
from app.ai.braille.regulations import make_rule_at
from app.ai.braille.symbol_rules import symbol_rule_spans
from app.ai.braille.translator import (
    _BLANK_TAG_RULE,
    blank_marker_spans,
    border_marker_spans,
    box_borders_from_source,
    emphasis_marker_spans,
    tn_marker_spans,
    translate_body,
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


# 정답 목록 줄(`01 ①  02 ③  03 ④`)은 쌍 안(번호와 답 사이)에서 접지 않는다(#1353). 앱 사이드카 · FE 는 응답 `breaks`
#   (음절 경계 · 빈칸)에서 32칸을 접는데, 그 목록에 쌍 안 빈칸이 들어 있어 `5` / `③  6 ②` 로 쌍이 갈렸다(2027 dev · val
#   71곳). gold 는 쌍 사이에서만 접는다. 줄 끝까지 `번호 답` 토막이 번갈아 이어지고(앞에 붙은 상자 제목 같은 글은 둔다)
#   번호가 1씩 늘고 원문자 답이 하나 이상일 때만 쌍 안 자리를 뺀다. 수학 선택지 `① 1  ② 2` 는 원문자가 번호 자리라 안 걸린다.
_DIGIT_CELLS = "⠚⠁⠃⠉⠙⠑⠋⠛⠓⠊"                   # 0~9 — 범위로 쓰면 ⠛(7)이 빠지고 ⠂⠄⠈ 가 끼어든다
_NUM_RE = re.compile(f"⠼[{_DIGIT_CELLS}]+")
_CIRCLED_RE = re.compile("⠼[⠂⠆⠒⠲⠢]")             # ①~⑤
_TOKEN_RE = re.compile("[^⠀]+")


def _keep_answer_pairs(line: str, breaks: list[int]) -> list[int]:
    toks = list(_TOKEN_RE.finditer(line))
    for i in range(len(toks) % 2, len(toks) - 3, 2):        # 꼬리가 짝수 토막이 되는 머리부터 — 가장 긴 꼬리
        tail = toks[i:]
        nums, anss = tail[0::2], tail[1::2]
        if not all(_NUM_RE.fullmatch(t.group()) for t in nums):
            continue
        if not all(_NUM_RE.fullmatch(t.group()) or _CIRCLED_RE.fullmatch(t.group()) for t in anss):
            continue
        if not any(_CIRCLED_RE.fullmatch(t.group()) for t in anss):
            continue
        nos = [int("".join(str(_DIGIT_CELLS.index(c)) for c in t.group()[1:])) for t in nums]
        if any(b != a + 1 for a, b in zip(nos, nos[1:])):
            continue
        inner = {b for n, a in zip(nums, anss) for b in range(n.end(), a.start() + 1)}
        return [b for b in breaks if b not in inner]
    return breaks


class TextBraille:
    """LLMOutput 목록 → BrailleOutput 목록."""

    def translate(self, optimized: list[LLMOutput]) -> list[BrailleOutput]:
        # 요소별 격리: 한 요소 점역 실패가 같은 체인의 다른 요소를 막지 않는다.
        return safe_translate(optimized, self._translate_one)

    def _translate_one(self, opt: LLMOutput) -> BrailleOutput:
        # 논리 줄 + 음절 줄바꿈 offset. 32칸 줄바꿈은 layout이 수행(NLD-1.2.1).
        lines, breaks = translate_body(opt.corrected_text)
        if len(breaks) == len(lines):
            breaks = [_keep_answer_pairs(ln, br) for ln, br in zip(lines, breaks)]
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
        # 글상자 테두리(NLD-1.2.5 · 원장 C-01b) — 묵자에 없던 것을 우리가 판단해 넣은 자리다.
        # ★ layout 이 아니라 여기서 낸다: 응답 좌표계(flatten)가 layout 앞에서 굳는다.
        trail += [
            make_rule_at("NLD-1.2.5", lines, s, e, tag=tag)
            for s, e, tag in border_marker_spans(joined, opt.corrected_text)
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
