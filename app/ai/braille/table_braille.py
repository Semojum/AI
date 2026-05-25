"""PART 6-3 — 표 점역 (render_mode 기반 조판).

table_grid : ⠿ 테두리 + ⠒ 행 구분선 + ⠒ 셀 구분자
transposed  : 첫 열 헤더 기준 뒤집기
linear      : 키: 값 형식
narrative   : TN 텍스트 → translator 변환
"""

from __future__ import annotations

from app.ai.braille.translator import translate_tagged_text as _translate
from app.schemas.content import BrailleOutput, LLMOutput, RuleApplication

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

_COLS = 32
_BORDER  = "⠿"  # 표 테두리
_SEP     = "⠒"  # 행·셀 구분선
_GUIDE   = "⠄"  # 유도점


def _border_line() -> str:
    return _BORDER * _COLS


def _row_sep() -> str:
    return _SEP * _COLS


def _split_cell(text: str, width: int) -> list[str]:
    """셀 텍스트를 주어진 너비로 분리."""
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


def _render_grid(corrected_text: str) -> list[str]:
    """텍스트 표현("|"구분) → 점자 격자 레이아웃.

    각 셀 텍스트를 translate_tagged_text()로 점자 변환 후 ⠿/⠒ 기호로 조판.
    """
    rows = [ln for ln in corrected_text.splitlines() if ln.strip()]
    if not rows:
        return [_border_line()]

    n_cols = max(len(r.split("|")) for r in rows) if rows else 1
    col_w = max(1, (_COLS - n_cols - 1) // n_cols)

    lines: list[str] = [_border_line()]
    for i, row in enumerate(rows):
        raw_cells = [c.strip() for c in row.split("|")]
        raw_cells += [""] * (n_cols - len(raw_cells))

        # 각 셀: 텍스트 → 점자 변환 후 col_w 기준 분리
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
            buf = ""
            for ch in entry:
                if len(buf) >= _COLS:
                    result.append(buf)
                    buf = ch
                else:
                    buf += ch
            if buf:
                result.append(buf)
    return result or [""]


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


class TableBraille:
    """LLMOutput 목록 → BrailleOutput 목록 (표)."""

    def translate(self, optimized: list[LLMOutput]) -> list[BrailleOutput]:
        results = []
        for opt in optimized:
            lines = self._render(opt)
            trail = list(opt.rule_trail) + [_RULE_TABLE, _RULE_LINE_WRAP]
            results.append(BrailleOutput(
                element_id=opt.element_id,
                braille_lines=lines,
                rule_trail=trail,
            ))
        return results

    def _render(self, opt: LLMOutput) -> list[str]:
        text = opt.corrected_text
        if text.startswith("[처리 불가") or text.startswith("[표 수동"):
            return [text]

        mode = opt.render_mode

        if mode == "table_grid":
            return _render_grid(text)

        if mode == "transposed":
            # 전치: 첫 열 헤더로 처리 후 grid
            return _render_grid(text)

        if mode == "linear":
            return _render_linear(text)

        # narrative / fallback: TN 텍스트 → 점자 변환
        tn = opt.tn_text or text
        return _split_lines(_translate(tn))
