"""PART 6-3 — 표 점역 (render_mode 기반 조판).

표의 복수 초안(3안)은 LLM 텍스트가 아니라 **레이아웃 3종**이다
(stage4_complex.md 'T4-2 공통 규약' — 표=레이아웃 차이, 셀 값 동일):
  table_grid : ⠿ 테두리 + ⠒ 행 구분선 (격자 원형)
  transposed : 행↔열 전치 (한국 점자 규정 제66항, 점역자 주 동반)
  linear     : '⠄키: 값' 선형 풀어쓰기
격자 구조가 아닌 비정형(narrative)·처리불가는 단일안으로 처리한다.
"""

from __future__ import annotations

from app.ai.braille.regulations import make_rule
from app.ai.braille.symbol_rules import symbol_rule_spans
from app.ai.braille.translator import translate_tagged_text as _translate
from app.ai.braille.translator import tn_marker_spans
from app.schemas.content import BrailleOutput, Draft, LLMOutput, RuleApplication


def _base_trail(lines: list[str], source: str = "") -> list[RuleApplication]:
    """점역자 주 마커(BBPG-1.2.6)만 점자 좌표로 emit.

    rule_trail은 '내용 변환'만 기록한다(태민 정책 2026-06-01). 포괄·조판 규칙 제외.
    표 내용 속 특수기호·수식 규칙은 Phase B에서 추가 예정.

    source = 점역 전 원본 텍스트. 원본에 점역자 주 태그가 있을 때만 emit하여
    ∽·ː 등 동일 점형(⠠⠄)을 오인하지 않는다(B1 오탐 방지).
    """
    joined = "\n".join(lines)
    trail = [
        make_rule("BBPG-1.2.6", span_start=s, span_end=e, tag=tag)
        for s, e, tag in tn_marker_spans(joined, source)
    ]
    trail += [
        make_rule(rule_id, span_start=s, span_end=e, tag="symbol")
        for s, e, rule_id in symbol_rule_spans(source, joined)
    ]
    return trail

from app.ai.braille.constants import COLS as _COLS  # noqa: E402 (공용 상수)
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
            text = opt.corrected_text

            if text.startswith("[처리 불가") or text.startswith("[표 수동"):
                lines = [text]
                results.append(BrailleOutput(
                    element_id=opt.element_id, braille_lines=lines,
                    rule_trail=_base_trail(lines, text),
                ))
                continue

            if "|" not in text:  # 비정형 → TN 단일안
                tn = opt.tn_text or text
                lines = _split_lines(_translate(tn))
                results.append(BrailleOutput(
                    element_id=opt.element_id,
                    braille_lines=lines,
                    rule_trail=_base_trail(lines, tn),
                ))
                continue

            # 격자 구조 → 레이아웃 3안 (셀 값 동일, 조판만 다름)
            grid_lines = _render_grid(text)
            transposed_lines = _split_lines(_translate(_TN_TRANSPOSE)) + _render_grid(_transpose_text(text))
            linear_lines = _render_linear(text)
            # 전치안은 표 유형별 점역(BBPG-3.1.2)을 추가로 기록
            n_tr = len("\n".join(transposed_lines))
            trail_transpose = _base_trail(transposed_lines, text) + [
                make_rule("BBPG-3.1.2", span_start=0, span_end=n_tr),
            ]
            drafts = [
                Draft(option=1, text=text, render_mode="table_grid", label="격자형",
                      braille_lines=grid_lines, rule_trail=_base_trail(grid_lines, text)),
                Draft(option=2, text=text, render_mode="transposed", label="행↔열 전치",
                      braille_lines=transposed_lines, rule_trail=trail_transpose),
                Draft(option=3, text=text, render_mode="linear", label="선형(키:값)",
                      braille_lines=linear_lines, rule_trail=_base_trail(linear_lines, text)),
            ]
            # 기본 선택은 opt가 추론한 render_mode에 맞춘다 (나머지는 대안 초안)
            sel = {"table_grid": 0, "transposed": 1, "linear": 2}.get(opt.render_mode, 0)
            results.append(BrailleOutput(
                element_id=opt.element_id,
                braille_lines=drafts[sel].braille_lines,
                rule_trail=list(drafts[sel].rule_trail),
                drafts=drafts,
                selected_idx=sel,
            ))
        return results
