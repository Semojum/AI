"""PART 6-3 — 표 점역 (render_mode 기반 조판).

표의 복수 초안(3안)은 LLM 텍스트가 아니라 **레이아웃 3종**이다
(stage4_complex.md 'T4-2 공통 규약' — 표=레이아웃 차이, 셀 값 동일):
  table_grid : ⠿ 테두리 + ⠒ 행 구분선 (격자 원형)
  transposed : 행↔열 전치 (한국 점자 규정 제66항, 점역자 주 동반)
  linear     : '⠄키: 값' 선형 풀어쓰기
격자 구조가 아닌 비정형(narrative)·처리불가는 단일안으로 처리한다.
"""

from __future__ import annotations

from app.ai.braille.translator import translate_tagged_text as _translate
from app.schemas.content import BrailleOutput, Draft, LLMOutput, RuleApplication

_RULE_TABLE = RuleApplication(
    rule_id="KBR-6.1",
    source="한국 점자 규정",
    section="6.1",
    title="표 점역 기본 원칙",
    excerpt="표는 점자 32칸 내에서 구조를 유지하여 변환한다.",
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
_RULE_TRANSPOSE = RuleApplication(
    rule_id="KBR-66",
    source="한국 점자 규정",
    section="제66항",
    title="표 전치 점역자 주",
    excerpt="표의 가로와 세로를 바꾸어 점역하였음.",
    priority="primary",
)

_COLS = 32
_BORDER  = "⠿"  # 표 테두리
_SEP     = "⠒"  # 행·셀 구분선
_GUIDE   = "⠄"  # 유도점
_TN_TRANSPOSE = "표의 가로와 세로를 바꾸어 점역함."


def _border_line() -> str:
    return _BORDER * _COLS


def _row_sep() -> str:
    return _SEP * _COLS


def _split_cell(text: str, width: int) -> list[str]:
    lines, buf = [], ""
    for ch in text:
        if len(buf) >= width:
            lines.append(buf)
            buf = ch
        else:
            buf += ch
    if buf:
        lines.append(buf)
    return lines or [""]


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


def _render_grid(corrected_text: str) -> list[str]:
    """텍스트 표현("|"구분) → 점자 격자 레이아웃."""
    rows = [ln for ln in corrected_text.splitlines() if ln.strip()]
    if not rows:
        return [_border_line()]

    n_cols = max(len(r.split("|")) for r in rows) if rows else 1
    col_w = max(1, (_COLS - n_cols - 1) // n_cols)

    lines: list[str] = [_border_line()]
    for i, row in enumerate(rows):
        raw_cells = [c.strip() for c in row.split("|")]
        raw_cells += [""] * (n_cols - len(raw_cells))

        cell_lines = [_split_cell(_translate(c), col_w) for c in raw_cells]
        max_h = max(len(cl) for cl in cell_lines)

        for h in range(max_h):
            parts = []
            for cl in cell_lines:
                txt = cl[h] if h < len(cl) else ""
                parts.append(txt.ljust(col_w)[:col_w])
            line = _BORDER + _SEP.join(parts) + _BORDER
            lines.append(line[:_COLS])

        if i < len(rows) - 1:
            lines.append(_row_sep())

    lines.append(_border_line())
    return lines


def _render_linear(corrected_text: str) -> list[str]:
    """2열 표 → '⠄키: 값' 점자 형식."""
    result: list[str] = []
    for ln in corrected_text.splitlines():
        if "|" in ln:
            parts = [p.strip() for p in ln.split("|", 1)]
            key_br = _translate(parts[0])
            val_br = _translate(parts[1]) if len(parts) > 1 else ""
            entry = f"{_GUIDE}{key_br}: {val_br}"
        else:
            entry = _translate(ln)
        if len(entry) <= _COLS:
            result.append(entry)
        else:
            result.extend(_split_lines(entry))
    return result or [""]


def _transpose_text(corrected_text: str) -> str:
    """'|' 구분 표 텍스트의 행↔열을 바꾼다."""
    rows = [[c.strip() for c in ln.split("|")] for ln in corrected_text.splitlines() if ln.strip()]
    if not rows:
        return corrected_text
    n_cols = max(len(r) for r in rows)
    rows = [r + [""] * (n_cols - len(r)) for r in rows]
    cols = list(zip(*rows))
    return "\n".join(" | ".join(col) for col in cols)


class TableBraille:
    """LLMOutput 목록 → BrailleOutput 목록 (표). 격자/전치/선형 3안."""

    def translate(self, optimized: list[LLMOutput]) -> list[BrailleOutput]:
        results = []
        for opt in optimized:
            base_trail = list(opt.rule_trail) + [_RULE_TABLE, _RULE_LINE_WRAP]
            text = opt.corrected_text

            if text.startswith("[처리 불가") or text.startswith("[표 수동"):
                results.append(BrailleOutput(
                    element_id=opt.element_id, braille_lines=[text], rule_trail=base_trail,
                ))
                continue

            if "|" not in text:  # 비정형 → TN 단일안
                tn = opt.tn_text or text
                results.append(BrailleOutput(
                    element_id=opt.element_id,
                    braille_lines=_split_lines(_translate(tn)),
                    rule_trail=base_trail,
                ))
                continue

            # 격자 구조 → 레이아웃 3안 (셀 값 동일, 조판만 다름)
            transposed_lines = _split_lines(_translate(_TN_TRANSPOSE)) + _render_grid(_transpose_text(text))
            drafts = [
                Draft(option=1, text=text, render_mode="table_grid", label="격자형",
                      braille_lines=_render_grid(text), rule_trail=list(base_trail)),
                Draft(option=2, text=text, render_mode="transposed", label="행↔열 전치",
                      braille_lines=transposed_lines, rule_trail=base_trail + [_RULE_TRANSPOSE]),
                Draft(option=3, text=text, render_mode="linear", label="선형(키:값)",
                      braille_lines=_render_linear(text), rule_trail=list(base_trail)),
            ]
            # 기본 선택은 opt가 추론한 render_mode에 맞춘다 (나머지는 대안 초안)
            sel = {"table_grid": 0, "transposed": 1, "linear": 2}.get(opt.render_mode, 0)
            results.append(BrailleOutput(
                element_id=opt.element_id,
                braille_lines=drafts[sel].braille_lines,
                rule_trail=base_trail,
                drafts=drafts,
                selected_idx=sel,
            ))
        return results
