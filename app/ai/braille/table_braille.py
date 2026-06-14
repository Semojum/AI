"""PART 6-3 — 표 점역 (render_mode 기반 조판).

표의 복수 초안(3안)은 LLM 텍스트가 아니라 **레이아웃 3종**이다
(stage4_complex.md 'T4-2 공통 규약' — 표=레이아웃 차이, 셀 값 동일):
  table_grid : ⠿ 테두리 + ⠒ 행 구분선 (격자 원형)
  transposed : 행↔열 전치 (한국 점자 규정 제66항, 점역자 주 동반)
  linear     : '⠄키: 값' 선형 풀어쓰기
격자 구조가 아닌 비정형(narrative)·처리불가는 단일안으로 처리한다.
"""

from __future__ import annotations

from app.ai.braille.isolation import safe_translate
from app.ai.braille.nested_block import append_nested
from app.ai.braille.regulations import make_rule, make_rule_at
from app.ai.braille.symbol_rules import symbol_rule_spans
from app.ai.braille.translator import translate_tagged_text as _translate
from app.ai.braille.translator import tn_marker_spans, translate_with_breaks
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
        make_rule_at("BBPG-1.2.6", lines, s, e, tag=tag)
        for s, e, tag in tn_marker_spans(joined, source)
    ]
    trail += [
        make_rule_at(rule_id, lines, s, e, tag="symbol")
        for s, e, rule_id in symbol_rule_spans(source, joined)
    ]
    return trail

from app.ai.braille.constants import COLS as _COLS  # noqa: E402 (공용 상수)
_BORDER  = "⠿"  # 표 테두리
_SEP     = "⠒"  # 행·셀 구분선
_GUIDE   = "⠄"  # 유도점
_TN_TRANSPOSE = "표의 가로와 세로를 바꾸어 점역함."
_TITLE_INDENT = 5  # 도서 제작 지침 제3장 5)(1): 표 제목은 5칸에서 시작


def _title_line(title: str) -> str:
    """표 제목(전사) → 5칸 들여쓴 점자 줄 (§3 5)(1)). layout이 폭을 건드리지 않도록 공백을 직접 적는다."""
    return " " * _TITLE_INDENT + _translate(title)


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


def _render_unfold(corrected_text: str) -> list[str]:
    """표 → 풀어쓰기 컬럼 정렬 (BBPG-3.1.2: 열 제목 3칸부터·두 칸씩 띄어 구분).

    각 열을 열별 최대 너비로 맞춰 2칸씩 띄어 구분하고, 줄 전체를 3칸(앞 2칸 빈칸)에서
    시작한다. 열 제목 줄과 데이터 줄이 같은 열 위치에 정렬된다(셀 내용도 이와 같이).
    한 줄이 32칸을 넘으면 layout이 음절 단위로 줄바꿈한다(넓은 표는 전치안 권장).
    """
    rows = [[c.strip() for c in ln.split("|")] for ln in corrected_text.splitlines() if ln.strip()]
    if not rows:
        return [""]
    n_cols = max(len(r) for r in rows)
    rows = [r + [""] * (n_cols - len(r)) for r in rows]
    cells_br = [[_translate(c) for c in r] for r in rows]
    widths = [max((len(cells_br[i][j]) for i in range(len(cells_br))), default=0)
              for j in range(n_cols)]
    lines: list[str] = []
    for r in cells_br:
        parts = [r[j].ljust(widths[j]) for j in range(n_cols)]
        line = "  " + "  ".join(parts)            # 3칸 시작(앞 2칸) + 2칸 구분
        lines.append(line.rstrip() or "  ")        # 마지막 열 trailing 패딩 제거
    return lines or [""]


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
        # 요소별 격리: 한 표 점역 실패가 다른 요소를 막지 않는다.
        return safe_translate(optimized, self._translate_one)

    def _translate_one(self, opt: LLMOutput) -> BrailleOutput:
        text = opt.corrected_text

        if text.startswith("[처리 불가") or text.startswith("[표 수동"):
            lines = [text]
            return BrailleOutput(
                element_id=opt.element_id, braille_lines=lines,
                rule_trail=_base_trail(lines, text),
            )

        # 표 제목(전사) — §3 5): 위 테두리 앞에 5칸 들여 한 줄. 없으면 None.
        title_br = _title_line(opt.table_title) if opt.table_title else None

        def _wt(lines: list[str]) -> list[str]:
            """제목 줄을 표 위에 먼저 붙인다(§3 5)(2))."""
            return ([title_br] + lines) if title_br else lines

        if "|" not in text:  # 비정형 → TN 단일안
            tn = opt.tn_text or text
            lines, breaks = translate_with_breaks(tn)  # 음절 줄바꿈(BBPG-1.2.1)
            lines = _wt(lines)
            if title_br:                      # 제목 줄은 음절 줄바꿈 대상 아님(단일 줄)
                breaks = [[]] + breaks
            bo = BrailleOutput(
                element_id=opt.element_id,
                braille_lines=lines,
                break_points=breaks,
                rule_trail=_base_trail(lines, tn),
            )
            append_nested(bo, opt.nested_text)   # 표 안 그림(Q11) 글상자 1단 덧붙임
            return bo

        # 표 유형별 레이아웃 (셀 값 동일, 조판만 다름). 기본=풀어쓰기(BBPG-3.1.2 원칙).
        unfold_lines = _wt(_render_unfold(text))
        grid_lines = _wt(_render_grid(text))
        transposed_lines = _wt(_split_lines(_translate(_TN_TRANSPOSE)) + _render_grid(_transpose_text(text)))
        linear_lines = _wt(_render_linear(text))
        drafts = [
            Draft(option=1, text=text, render_mode="unfold", label="풀어쓰기(3칸·2칸)",
                  braille_lines=unfold_lines,
                  rule_trail=_base_trail(unfold_lines, text) + [make_rule("BBPG-3.1.2")]),
            Draft(option=2, text=text, render_mode="table_grid", label="격자형",
                  braille_lines=grid_lines, rule_trail=_base_trail(grid_lines, text)),
            Draft(option=3, text=text, render_mode="transposed", label="행↔열 전치",
                  braille_lines=transposed_lines,
                  rule_trail=_base_trail(transposed_lines, text) + [make_rule("BBPG-3.1.2")]),
            Draft(option=4, text=text, render_mode="linear", label="선형(키:값)",
                  braille_lines=linear_lines, rule_trail=_base_trail(linear_lines, text)),
        ]
        # 기본 선택 = opt 추론 render_mode (없으면 풀어쓰기). 나머지는 대안 초안.
        sel = {"unfold": 0, "table_grid": 1, "transposed": 2, "linear": 3}.get(opt.render_mode, 0)
        bo = BrailleOutput(
            element_id=opt.element_id,
            braille_lines=drafts[sel].braille_lines,
            rule_trail=list(drafts[sel].rule_trail),
            drafts=drafts,
            selected_idx=sel,
        )
        append_nested(bo, opt.nested_text)   # 표 안 그림(Q11) 글상자 1단 덧붙임
        return bo
