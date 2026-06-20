"""중첩 시각자료(점역사 QnA Q11) — 테두리 묶기 / 글상자 1단 풀어쓰기 공용 유틸.

Q11:
  · 그림 안의 그래프 → 그래프 설명 부분을 **테두리로 묶어** 준다.
  · 표 안의 그림   → 그림을 **글상자처럼 1단으로 쭉 풀어 써서** 설명한다.

두 경우 모두 "테두리(<!테두리_위>/<!테두리_아래>)로 감싼 1단 narrative"라는 동일 골격이다.
opt가 `box_narrative()`로 보조 텍스트를 만들어 LLMOutput.nested_text에 담고,
braille 모듈이 `append_nested()`로 본 요소 점자 끝에 덧붙인다(테두리는 layout이 재렌더).
"""

from __future__ import annotations

from typing import Optional

from app.ai.braille.translator import box_borders_from_source, translate_with_breaks
from app.schemas.content import BoxBorder, BrailleOutput


def box_narrative(blocks: list[dict], default_label: str = "그래프") -> Optional[str]:
    """중첩 시각자료 목록 → 테두리로 감싼 1단 narrative 텍스트(점역 전).

    각 block: {"label": 유형, "description": 설명, "ocr_texts": [원본내용...]}.
    유형 라벨은 점역자 주(§6.3.4(1))로 표기하고, 원본 내용(축 수치·표 셀 등)은 전사한다.
    label이 없으면 default_label(그림 안 그래프=그래프 / 표 안 그림=그림). 빈 목록이면 None.
    """
    out: list[str] = []
    for b in blocks or []:
        label = (b.get("label") or default_label).strip()
        desc = (b.get("description") or b.get("caption") or "").strip()
        body = (f"<!점역자주>{label}: {desc}<!/점역자주>" if desc
                else f"<!점역자주>{label}<!/점역자주>")
        out.append("<!테두리_위><!/테두리_위>")   # Q11 테두리 묶기 / 글상자 1단(빈 제목 쌍)
        out.append(body)
        for t in b.get("ocr_texts") or []:          # 원본 내용 전사(축 수치·셀 등)
            t = str(t).strip()
            if t:
                out.append(t)
        out.append("<!테두리_아래><!/테두리_아래>")
    return "\n".join(out) if out else None


def append_nested(bo: BrailleOutput, nested_text: Optional[str]) -> None:
    """중첩 narrative를 본 요소 점자 출력 끝에 덧붙인다(in-place).

    braille_lines·break_points·box_borders·line_indents(있으면)·각 draft를 일관되게 확장한다.
    테두리 위치 마커는 layout `_expand_box_borders`가 box_borders와 짝지어 재렌더한다.
    """
    if not nested_text:
        return
    n_lines, n_breaks = translate_with_breaks(nested_text)

    def _aligned_breaks(breaks: list, base_len: int) -> list:
        """break_points를 braille_lines 길이에 맞춰 패딩한 뒤 중첩 줄 offset을 잇는다.

        격자 표는 break_points가 비어 있어(전부 강제 줄바꿈) 패딩 없이 붙이면 인덱스가 어긋난다.
        """
        out = list(breaks or [])
        out += [[]] * (base_len - len(out))
        return out + n_breaks

    bo.break_points = _aligned_breaks(bo.break_points, len(bo.braille_lines))
    bo.braille_lines = list(bo.braille_lines) + n_lines
    bo.box_borders = list(bo.box_borders) + [
        BoxBorder(kind=k, level=lv, title=t)
        for k, lv, t in box_borders_from_source(nested_text)
    ]
    if bo.line_indents is not None:
        bo.line_indents = list(bo.line_indents) + [0] * len(n_lines)  # 중첩 줄은 0칸(테두리 1단)
    for d in bo.drafts:   # 피커 대안에도 동일하게 덧붙여 contents 일관성 유지
        d.break_points = _aligned_breaks(d.break_points, len(d.braille_lines))
        d.braille_lines = list(d.braille_lines) + n_lines
