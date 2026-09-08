"""PART 7-3 · 8-3 · 9-3 · 도표 — 시각 자료 점역 (점역사주 TN 텍스트 → 점자).

이미지·만화·차트/그래프·도표 넷을 한 자리에서 점역한다. ★ 2026-09-08(재구조화 5단계)
전까지는 `image_braille`·`cartoon_braille`·`chart_graph_braille`·`diagram_braille`
네 모듈이 **같은 코드를 네 벌** 갖고 있었다(파일당 107~116줄, 실질 차이 둘).
한 벌을 고치고 세 벌을 안 고치는 사고가 나기 좋은 모양이라 하나로 합쳤다.

유형마다 갈리는 것은 아래 두 가지뿐이고, 그 밖은 넷이 글자까지 같았다.
  · `src_indents`  단일 출력에서 **원본 태그**의 줄별 들여쓰기를 볼 것인가.
                   만화만 거짓 — 만화 단일 출력은 `opt.line_indents`(§5.3 5칸 장면·
                   3칸 대사 골격)만 본다.
  · 중첩 시각자료  `append_nested` 는 `nested_text` 가 없으면 즉시 돌아오므로
                   넷 다 무조건 부른다. 지금 값을 채우는 자리는 `image_opt`
                   (그림 안 그래프 Q11) 하나다.

복수 초안(drafts)이 있으면 각 초안을 점역해 `Draft.braille_lines` 를 채우고,
선택 초안(`selected_idx`)의 점자를 `BrailleOutput.braille_lines` 로 둔다(PART 10 조판용).

흐름도 도형 점형(§6.6.2(3))·반직선 점형(§6.6.2(4)⑥의 3o)은 **점역사 확인 후 배선**한다.
아래는 문서(점자 자료 제작 지침 §6.6.2(3) + 한국 점자 규정 제38·70항)의 Braille ASCII 표기를
유니코드로 디코드한 표 — 검증 전이므로 코드에 배선하지 않는다(추측 금지, 태민 2026-06-08).

  _FLOW_SHAPE_ASCII = {
      "ellipse":   ("@$OV", "⠈⠫⠕⠧"),   # 타원형
      "rectangle": ("@$R",  "⠈⠫⠗"),    # 직사각형
      "tri_pair":  ("@$TT", "⠈⠫⠞⠞"),   # 삼각형이 위아래로 붙은 모양
      "diamond":   ("@$D",  "⠈⠫⠙"),    # 마름모
      "inv_tri":   ("@$M",  "⠈⠫⠍"),    # 역삼각형
      "wave_rect": ("@$IO", "⠈⠫⠊⠕"),   # 아랫변이 물결모양인 사각형
  }
  _FLOW_ARROW = ("3o", "⠒⠕")           # 반직선/화살표(→) 제38·70항
"""

from __future__ import annotations

from app.ai.braille import tag_names as _TAGS
from app.ai.braille.isolation import safe_translate
from app.ai.braille.nested_block import append_nested
from app.ai.braille.regulations import make_rule_at
from app.ai.braille.symbol_rules import symbol_rule_spans
from app.ai.braille.translator import (
    box_borders_from_source,
    translate_visual,
    tn_marker_spans,
)
from app.schemas.content import BoxBorder, BrailleOutput, LLMOutput, RuleApplication


def _box_borders(source: str) -> list[BoxBorder]:
    """원본 글상자 테두리 태그 → box_borders(NLD-1.2.5, layout 재렌더용)."""
    return [BoxBorder(kind=k, level=lv, title=t) for k, lv, t in box_borders_from_source(source)]


def _base_trail(lines: list[str], source: str = "") -> list[RuleApplication]:
    """점역자 주 마커(NLD-1.2.6)·내용 기호 규칙만 점자 좌표로 emit.

    rule_trail은 점역사가 규정으로 확인할 '내용 변환'만 기록한다(태민 정책 2026-06-01).
    포괄 규칙(시각자료 일반·32칸 줄바꿈)·기계적 조판 규칙은 기록하지 않는다.

    source = 점역 전 원본 텍스트. 원본에 점역자 주 태그가 있을 때만 emit하여
    ∽·ː 등 동일 점형(⠠⠄)을 오인하지 않는다(B1 오탐 방지).
    """
    joined = "\n".join(lines)
    trail = [
        make_rule_at("NLD-1.2.6", lines, s, e, tag=tag)
        for s, e, tag in tn_marker_spans(joined, source)
    ]
    trail += [
        make_rule_at(rule_id, lines, s, e, tag="symbol")
        for s, e, rule_id in symbol_rule_spans(source, joined)
    ]
    return trail


def _to_braille(text: str) -> tuple[list[str], list[list[int]]]:
    """논리 줄 + 음절 줄바꿈 offset. 32칸 줄바꿈은 layout(NLD-1.2.1)."""
    if text.startswith("[처리 불가"):
        return [text], [[]]
    return translate_visual(text)   # 시각 설명은 항목 번호 마침표 관행을 안 탄다(C-41)


def _match_indents(line_indents, lines):
    """줄별 들여쓰기(규정 골격: 시각자료 제목 5칸·만화 5칸 장면/3칸 대사)를
    줄 수와 일치할 때만 전달."""
    if line_indents is not None and len(line_indents) == len(lines):
        return line_indents
    return None


class VisualBraille:
    """LLMOutput 목록 → BrailleOutput 목록 (시각 자료). 초안별 점역."""

    kind = "시각 자료"
    src_indents = True     # 단일 출력에서 원본 태그의 들여쓰기를 볼 것인가(만화만 거짓)

    def translate(self, optimized: list[LLMOutput]) -> list[BrailleOutput]:
        # 요소별 격리: 한 요소의 점역 실패가 다른 요소를 막지 않는다.
        return safe_translate(optimized, self._translate_one)

    def _translate_one(self, opt: LLMOutput) -> BrailleOutput:
        bo = self._drafts(opt) if opt.drafts else self._single(opt)
        # 중첩 시각자료(Q11) — `nested_text` 가 없으면 `append_nested` 가 즉시 돌아온다.
        append_nested(bo, opt.nested_text)
        return bo

    def _drafts(self, opt: LLMOutput) -> BrailleOutput:
        out_drafts = []
        draft_breaks: list[list[list[int]]] = []
        draft_indents: list[list[int] | None] = []
        for d in opt.drafts:
            # ★ 안마다 **자기 글에 박힌 태그**에서 들여쓰기를 뽑는다(2026-08-25).
            #   종전에는 요소 한 곳의 값(선택 안 것)이 모든 안에 씌워졌다.
            d_text, d_ind = _TAGS.strip_indent_tags(d.text)
            d_lines, d_breaks = _to_braille(d_text)
            draft_breaks.append(d_breaks)
            draft_indents.append(d_ind)
            out_drafts.append(d.model_copy(update={
                "braille_lines": d_lines,
                "break_points": d_breaks,
                # ★ 안마다 **자기** 들여쓰기를 싣는다(2026-08-25). 종전에는 선택 안의
                #   값만 BrailleOutput 에 실려 다른 안에도 그대로 씌워졌다.
                "rule_trail": _base_trail(d_lines, d.text),
            }))
        sel = opt.selected_idx if 0 <= opt.selected_idx < len(out_drafts) else 0
        return BrailleOutput(
            element_id=opt.element_id,
            braille_lines=out_drafts[sel].braille_lines,
            break_points=draft_breaks[sel],
            # 골격 규정(§6.3·§6.6 등 opt가 정한 governing rule) + 점역자주·기호 span.
            rule_trail=list(opt.rule_trail) + list(out_drafts[sel].rule_trail),
            drafts=out_drafts,
            selected_idx=sel,
            box_borders=_box_borders(opt.drafts[sel].text),
            line_indents=_match_indents(draft_indents[sel], out_drafts[sel].braille_lines),
        )

    def _single(self, opt: LLMOutput) -> BrailleOutput:
        """구조 없음·처리 불가 폴백 — 초안 없이 한 벌만 낸다."""
        src, src_ind = _TAGS.strip_indent_tags(opt.tn_text or opt.corrected_text)
        lines, breaks = _to_braille(src)
        ind = (src_ind or opt.line_indents) if self.src_indents else opt.line_indents
        return BrailleOutput(
            element_id=opt.element_id,
            braille_lines=lines,
            break_points=breaks,
            rule_trail=list(opt.rule_trail) + _base_trail(lines, src),
            box_borders=_box_borders(src),
            line_indents=_match_indents(ind, lines),
        )


class ImageBraille(VisualBraille):
    kind = "이미지"


class ChartGraphBraille(VisualBraille):
    kind = "차트/그래프"


class DiagramBraille(VisualBraille):
    """개념도·흐름도 등 도표. 골격은 자유서술이 아니라 줄별 들여쓰기를 가진 단일 출력이다."""

    kind = "도표"


class CartoonBraille(VisualBraille):
    """만화. 단일 출력의 들여쓰기는 §5.3 골격(`opt.line_indents`)만 본다."""

    kind = "만화"
    src_indents = False
