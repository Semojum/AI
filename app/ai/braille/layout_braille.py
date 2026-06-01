"""PART 10 — 점자 조판 (텍스트 전용, 단계 3).

BrailleOutput 목록 → 32칸 × 25줄 페이지 조판 → 파일 저장.

조판/레이아웃 규정 정본 = 점자 도서 제작 지침(BBPG). 점자 글리프는 한국 점자
규정(KBR)에서 도출. PDF 점자는 표준 Braille ASCII 폰트(#b=숫자2)로 디코딩.
(폐기된 점자 자료 제작 지침 JAJAK 기반 마커 전면 교체됨.)

BBPG 1장2절1: 32칸 줄바꿈, 25줄 페이지 넘김
BBPG 1장2절2: 페이지행 — 원본 페이지번호(좌·첫칸) · 꼬리말(가운데) · 점자 페이지번호(우)
BBPG 1장2절2-3): 원본 페이지 변경선 — 첫 칸부터 ⠤로 채운 선 + 우측정렬 원본 페이지번호
BBPG 1장2절5: 글상자 테두리 — 위 ⠿…⠛…⠿ / 아래 ⠿…⠶…⠿ (32칸), 앞뒤 빈 줄
BBPG 2장2절2: 문단 — 새 문단 3칸 시작, 이어지는 줄 첫 칸
BBPG 2장2절3: 밑줄 빈칸 ⠸⠤ (길이 무관 1개)
BBPG 2장2절6: 출전 — 본문 아래일 때 다음 줄 3칸
BBPG 2장3절5: 글머리 기호 — 3칸 표기, 위계 1단계 동그라미 ⠸⠴ / 2단계 붙임표 ⠤ (KBR 제72항)
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import TYPE_CHECKING, Optional

from app.ai.braille.kor_math_rules import _NUMBER_INDICATOR, _DIGIT_MAP
from app.ai.braille.regulations import make_rule
from app.schemas.content import BrailleOutput

if TYPE_CHECKING:  # 런타임 import 회피 (annotations 지연 평가)
    from app.schemas.layout import LayoutResult

logger = logging.getLogger(__name__)

from app.ai.braille.constants import COLS as _COLS, ROWS as _ROWS  # noqa: E402 (공용 상수)

# ── BBPG 2장2절1 제목 단계별 빈 줄 (level → (앞, 뒤)) ───────────────────────
_HEADING_BLANK: dict[int, tuple[int, int]] = {1: (2, 1), 2: (1, 1), 3: (1, 0)}

# 단어 구분 = ASCII 공백 또는 점자 빈칸(U+2800)
_WORD_RE = re.compile(r"[^ ⠀]+")

# rule_trail rule_id (regulations.json 키)
_RULE_LINE_WRAP = "BBPG-1.2.1"      # 줄바꿈(32칸), tag=line_wrap
_RULE_HEADING_BLANK = "BBPG-2.2.1"  # 단계별 제목 표기, tag=heading_blank
_RULE_PARA_INDENT = "BBPG-2.2.2"    # 문단 형식(새 문단 3칸), tag=indent
_RULE_BULLET_INDENT = "BBPG-2.3.5"  # 글머리 3칸, tag=indent

# ── KBR 제72항 글머리 기호: 숨김표 글리프(_..l, 꼬리 ⠇) → 글머리형(_.., 꼬리 없음) ──
# ○□△가 list_item 글머리로 쓰이면 숨김표(제49항)가 아니라 글머리형(제72항)이어야 한다.
# text 체인은 문맥을 몰라 숨김표로 변환·emit하므로 여기서 글리프·rule을 글머리로 정정한다.
_HIDDEN_TO_BULLET: dict[str, str] = {
    "⠸⠚⠇": "⠸⠚",  # ○ 숨김표 → 글머리 (제72항 _0)
    "⠸⠄⠇": "⠸⠄",  # □ → 글머리 (_7)
    "⠸⠬⠇": "⠸⠬",  # △ → 글머리 (_+)
}
_RULE_BULLET = "KBR-6.14.72"   # 글머리 기호 (제72항)
_RULE_HIDDEN_SINGLE = "KBR-6.13.49"  # 숨김표 단일(제49항) — list_item 첫머리면 글머리로 정정

_PARA_INDENT = 3        # BBPG 2장2절2 새 문단 첫 줄 3칸 (text)
_BULLET_LINE_INDENT = 3  # BBPG 2장3절5 글머리/목록 3칸 (list_item)
_HEADING_DEEP_INDENT = 5  # BBPG 2장2절1 3·4단계 제목 5칸

_DEFAULT_META: tuple[str, int, int] = ("text", 1_000_000, 0)
_PAGE_LINE_TYPES = {"header_footer", "page_number"}

# 원본 페이지 연속 표기용 알파벳 점자(a~z, 로마자표 없는 맨 letter) — BBPG 1장2절2
_ALPHA_BRAILLE = "⠁⠃⠉⠙⠑⠋⠛⠓⠊⠚⠅⠇⠍⠝⠕⠏⠟⠗⠎⠞⠥⠧⠺⠭⠽⠵"

# ── BBPG 2장2절3 밑줄 빈칸 (KBR 밑줄 빈칸 기호 _- = ⠸⠤) ──────────────────────
_UNDERLINE_BLANK_MARKER = "⠸⠤"

# ── BBPG 2장3절5 글머리 기호 — 위계 2단계 (글리프 KBR 제72항) ────────────────
# 1단계(상위) 동그라미 ⠸⠴, 2단계(하위) 붙임표 ⠤
_BULLET_MARKERS: dict[int, str] = {1: "⠸⠴", 2: "⠤"}
_BULLET_INDENT = 2  # 3칸에 표기(2칸 들여 후 3번째 칸)

# ── BBPG 2장2절2 문단 형식 ──────────────────────────────────────────────────
_PARAGRAPH_INDENT = 3  # 새 문단은 3칸에서 시작

# ── BBPG 2장2절6 출전 ──────────────────────────────────────────────────────
_CITATION_INDENT = 3

# ── BBPG 2장2절2-3) 원본 페이지 변경선 ─────────────────────────────────────
_PAGE_CHANGE_FILL = "⠤"  # 변경선 채움 점형(BBPG는 ⠤ 또는 ⠒ 허용 — ⠤ 채택)

# ── BBPG 2장2절2 선행 페이지 번호 초과 (#- = ⠼⠤) ───────────────────────────
_OVERFLOW_PAGE_NUMBER = "⠼⠤"

# ── BBPG 1장2절5 글상자 테두리 ─────────────────────────────────────────────
_BOX_BORDER_END = "⠿"   # 양 끝 (=)
_BOX_TOP_FILL = "⠛"     # 위 테두리 중간 (g)
_BOX_BOTTOM_FILL = "⠶"  # 아래 테두리 중간 (7)
_BORDER_BLANK = "⠀"     # 점자 빈칸(U+2800) — 제목 앞뒤 띔
_BORDER_LEFT_FILL = 4   # 캡1+채움4+빈칸1 → 제목 7칸째 시작 (BBPG-1.2.5(4)②)
# 위계별 테두리 (start_cap, fill, end_cap). 표준 Braille ASCII: =⠿ g⠛ 7⠶ 6⠖ 3⠒ 4⠲ h⠓ j⠚ "⠐
# 현재 1단계만 발생(태그에 위계 없음). 2·3단계는 §3-5 태그 규약 확정 후 사용.
_BOX_LEVELS: dict[int, dict[str, tuple[str, str, str]]] = {
    1: {"top": ("⠿", "⠛", "⠿"), "bottom": ("⠿", "⠶", "⠿")},
    2: {"top": ("⠖", "⠒", "⠲"), "bottom": ("⠓", "⠒", "⠚")},
    3: {"top": ("⠖", "⠐", "⠲"), "bottom": ("⠓", "⠐", "⠚")},
}
# 제목을 위 테두리 안(중간 7칸)에 둘 수 있는 최대 길이. 초과 시 윗줄 5칸(케이스①, 규정 26칸)
_BOX_TITLE_INLINE_MAX = _COLS - 2 - _BORDER_LEFT_FILL - 2  # = 24
_BOX_TITLE_INDENT = 5  # 케이스① 제목 윗줄 5칸


def _is_border_line(line: str) -> bool:
    """글상자/표 테두리 줄(32칸, 양 끝 ⠿)인지 — 들여쓰기 금지 대상(B2).

    translator/table_braille가 32칸 테두리를 미리 렌더하므로, 여기에 문단·글머리
    들여(3칸)를 더하면 35칸이 되어 _break_line이 테두리를 강제 분리해 망가뜨린다.
    """
    return (
        len(line) == _COLS
        and line.startswith(_BOX_BORDER_END)
        and line.endswith(_BOX_BORDER_END)
    )


def format_underline_blank(text: str) -> str:
    """밑줄 빈칸(_+)을 ⠸⠤ 1개로 치환 — 길이 무관 (BBPG 2장2절3)."""
    return re.sub(r"_+", _UNDERLINE_BLANK_MARKER, text)


def format_citation(text: str) -> str:
    """출전 정보를 다음 줄 3칸에 배치 (BBPG 2장2절6)."""
    return " " * _CITATION_INDENT + text


def format_paragraph_start(text: str) -> str:
    """새 문단을 3칸에서 시작 (BBPG 2장2절2 문단 형식)."""
    return " " * _PARAGRAPH_INDENT + text


def format_bullet_item(text: str, tier: int) -> str:
    """글머리 기호: 3칸 표기, tier 1→⠸⠴(동그라미) 2→⠤(붙임표), 기호 뒤 1칸 (BBPG 2장3절5)."""
    marker = _BULLET_MARKERS.get(min(max(tier, 1), 2), _BULLET_MARKERS[2])
    return " " * _BULLET_INDENT + f"{marker} {text}"


def format_page_change_line(orig_page_braille: str) -> str:
    """원본 페이지 변경선: 첫 칸부터 ⠤로 채우고 우측 정렬로 원본 페이지번호 (BBPG 2장2절2-3).

    단일 마커가 아니라 줄 전체(32칸)를 채우는 '선'이다.
    """
    fill = max(0, _COLS - len(orig_page_braille))
    return _PAGE_CHANGE_FILL * fill + orig_page_braille


def format_box_top() -> str:
    """글상자 위 테두리: ⠿ + ⠛×(32-2) + ⠿ (BBPG 1장2절5)."""
    return _BOX_BORDER_END + _BOX_TOP_FILL * (_COLS - 2) + _BOX_BORDER_END


def format_box_bottom() -> str:
    """글상자 아래 테두리: ⠿ + ⠶×(32-2) + ⠿ (BBPG 1장2절5)."""
    return _BOX_BORDER_END + _BOX_BOTTOM_FILL * (_COLS - 2) + _BOX_BORDER_END


def format_overflow_page_number() -> str:
    """선행 페이지 번호가 본문 시작을 넘을 때 ⠼⠤ (BBPG 2장2절2). JAJAK ⠒⠒ no-page 마커는 폐기."""
    return _OVERFLOW_PAGE_NUMBER


def _page_number_braille(n: int) -> str:
    digits = "".join(_DIGIT_MAP.get(c, c) for c in str(n))
    return f"{_NUMBER_INDICATOR}{digits}⠲"


def _right_align(text: str, width: int) -> str:
    pad = max(0, width - len(text))
    return " " * pad + text


def _cell_count(text: str) -> int:
    """점자 셀 수 = 문자 수. 점역 후 1점자셀=1 코드포인트(U+2800~28FF), 공백 1셀."""
    return len(text)


def _center(text: str, width: int = _COLS) -> str:
    """text를 width 안에서 가운데 정렬 (BBPG 2장2절1 1단계 제목)."""
    t = text.strip()
    if _cell_count(t) >= width:
        return t
    return " " * ((width - _cell_count(t)) // 2) + t


def _break_line(
    line: str, width: int = _COLS, first_width: Optional[int] = None
) -> tuple[list[str], int, list[int]]:
    """한 줄을 width(32) 셀 이하로 분리. 단어 경계 우선, 초과 단어는 하이픈 없이 강제 분리.

    first_width: 첫 출력 줄에 허용할 폭(들여쓰기 칸 예약용). None이면 width.
    반환: (분리된 줄 목록, 강제분리 횟수, 줄바꿈이 삽입된 원본 char 오프셋 목록).
    """
    fw = width if first_width is None else first_width
    if _cell_count(line) <= fw:
        return ([line], 0, [])
    words = [(m.group(), m.start()) for m in _WORD_RE.finditer(line)]
    if not words:  # 공백뿐인 줄
        return ([line], 0, [])

    out: list[str] = []
    wraps: list[int] = []
    forced = 0
    cur = ""
    for word, start in words:
        cap = fw if not out else width        # 첫 줄만 first_width 적용
        candidate = word if not cur else f"{cur} {word}"
        if _cell_count(candidate) <= cap:
            cur = candidate
            continue
        if cur:                               # 현재 줄을 마감하고 단어 경계에서 줄바꿈
            out.append(cur)
            wraps.append(start)
            cur = ""
        cap = fw if not out else width
        piece, piece_start = word, start
        while _cell_count(piece) > cap:       # 단어 자체가 폭 초과 → 강제 분리
            out.append(piece[:cap])
            forced += 1
            piece_start += cap
            wraps.append(piece_start)
            piece = piece[cap:]
            cap = width
        cur = piece
    if cur:
        out.append(cur)
    return (out, forced, wraps)


class LayoutBraille:
    """BrailleOutput 목록 → 32칸 × 25줄 점자 조판 (PART 10).

    reading_order 정렬 → header_footer/page_number 분리 → 제목 단계별 빈 줄 →
    32칸 단어경계 라인 브레이킹 → 25줄 페이지 브레이킹 → 파일 저장.
    조판 태깅(heading_blank·line_wrap)은 점자 좌표 rule_trail로 emit(plan §3-4,
    braille_text_list 귀속). line_overflow_rate(C6용)를 반환한다.

    촉각 그래픽(table/chart_graph SVG)은 별도 태스크 — 미구현.
    """

    def layout(
        self,
        braille_outputs: list[BrailleOutput],
        page_no: int,
        job_id: str,
        *,
        layout_result: Optional["LayoutResult"] = None,
    ) -> float:
        """조판 후 파일 저장. line_overflow_rate(강제분리 줄 / 전체 줄) 반환.

        layout_result로 element별 type·reading_order·heading_level을 조회한다.
        조판 rule_trail은 각 BrailleOutput.rule_trail에 in-place 추가(점자 좌표).
        """
        meta = self._build_meta(layout_result)
        body, page_line_items = self._partition(braille_outputs, meta)
        body.sort(key=lambda b: meta.get(b.element_id, _DEFAULT_META)[1])

        lines: list[str] = []
        total = 0
        forced_total = 0
        for bo in body:
            etype, _order, hlevel = meta.get(bo.element_id, _DEFAULT_META)
            el_lines, forced = self._format_element(bo, etype, hlevel)
            if not el_lines:                       # 빈 요소는 빈 줄·태깅 없이 건너뜀
                continue
            before, after = _HEADING_BLANK.get(hlevel, (0, 0))
            if before:
                lines.extend([""] * before)  # 조판 동작은 유지, rule_trail 미기록(태민 정책)
            lines.extend(el_lines)
            total += len(el_lines)
            forced_total += forced
            if after:
                lines.extend([""] * after)

        footer = self._footer_text(page_line_items, meta)
        orig_page = self._orig_page_text(page_line_items, meta)
        pages = self._paginate(lines, page_no, footer, orig_page)
        self._save(pages, job_id, page_no)
        return (forced_total / total) if total else 0.0

    def _format_element(
        self, bo: BrailleOutput, etype: str, hlevel: int
    ) -> tuple[list[str], int]:
        """요소 점자 줄 → 들여쓰기·정렬·32칸 브레이킹 적용. (표시 줄, 강제분리 수).

        조판 동작(들여·줄바꿈·가운데정렬)은 적용하되 rule_trail은 기록하지 않는다
        (태민 정책 2026-06-01: 조판 서식 규칙은 rule_trail 제외, 내용 변환만).
        내용이 없는 요소(빈 줄뿐)는 빈 결과를 반환한다.
        """
        self._expand_box_borders(bo)
        if not any(ln.strip() for ln in bo.braille_lines):
            return [], 0
        if etype == "list_item":
            self._apply_bullet_marker(bo)
        is_heading = hlevel >= 1
        first_indent = self._first_indent(bo, etype, is_heading, hlevel)
        if first_indent and any(_is_border_line(ln) for ln in bo.braille_lines):
            # 정식 규칙(테두리 아키텍처 B안 확정 2026-06-02): 32칸 테두리 줄(글상자 BBPG-1.2.5·
            # 표 격자)은 layout이 폭을 소유하므로 들여쓰기를 적용하지 않는다. 들이면 35칸이 되어
            # _break_line이 테두리를 분리해 깨진다. (글상자 테두리는 _expand_box_borders가 재렌더.)
            logger.debug(
                "layout: %s 요소(%s) 32칸 테두리 — 들여쓰기 미적용(정식)", etype, bo.element_id,
            )
            first_indent = 0

        out: list[str] = []
        forced_total = 0
        for li, orig in enumerate(bo.braille_lines):
            indent = first_indent if li == 0 else 0
            fw = (_COLS - indent) if indent else None
            broken, forced, _wraps = _break_line(orig, first_width=fw)
            if indent and broken:               # 표시용 들여쓰기
                broken[0] = " " * indent + broken[0]
            if is_heading and hlevel == 1:       # 1단계 제목 가운데 정렬
                broken = [_center(b) for b in broken]
            out.extend(broken)
            forced_total += forced
        return out, forced_total

    def _render_box_top(self, level: int, title: str) -> list[str]:
        """위 테두리 줄 렌더 (BBPG-1.2.5). 제목 ≤24칸이면 중간 7칸, 초과면 윗줄 5칸(케이스①)."""
        start, fill, end = _BOX_LEVELS.get(level, _BOX_LEVELS[1])["top"]
        inner = _COLS - 2
        if not title:
            return [start + fill * inner + end]
        if len(title) <= _BOX_TITLE_INLINE_MAX:
            right = inner - _BORDER_LEFT_FILL - 2 - len(title)
            return [start + fill * _BORDER_LEFT_FILL + _BORDER_BLANK
                    + title + _BORDER_BLANK + fill * right + end]
        # 케이스①: 제목을 윗줄 5칸에 적고(넘치면 다음 줄도 5칸), 테두리는 제목 없이
        avail = _COLS - _BOX_TITLE_INDENT
        chunks = [title[i:i + avail] for i in range(0, len(title), avail)] or [""]
        title_lines = [" " * _BOX_TITLE_INDENT + c for c in chunks]
        return title_lines + [start + fill * inner + end]

    def _render_box_bottom(self, level: int) -> str:
        """아래 테두리 줄 렌더 (BBPG-1.2.5)."""
        start, fill, end = _BOX_LEVELS.get(level, _BOX_LEVELS[1])["bottom"]
        return start + fill * (_COLS - 2) + end

    def _expand_box_borders(self, bo: BrailleOutput) -> None:
        """글상자 테두리 위치 마커(인라인 32칸 줄)를 box_borders와 순서대로 짝지어 재렌더(in-place).

        translator가 남긴 32칸 테두리 줄을 위계·제목 배치로 다시 그리고(BBPG-1.2.5),
        글상자 위아래에 빈 줄을 넣는다(1.2.5(5)). box_borders 없으면 변경 없음.
        """
        if not bo.box_borders:
            return
        specs = list(bo.box_borders)
        si = 0
        new_lines: list[str] = []
        for ln in bo.braille_lines:
            if si < len(specs) and _is_border_line(ln):
                spec = specs[si]
                si += 1
                if spec.kind == "top":
                    new_lines.append("")  # 위 한 줄 띔
                    new_lines.extend(self._render_box_top(spec.level, spec.title))
                else:
                    new_lines.append(self._render_box_bottom(spec.level))
                    new_lines.append("")  # 아래 한 줄 띔
            else:
                new_lines.append(ln)
        bo.braille_lines = new_lines

    def _apply_bullet_marker(self, bo: BrailleOutput) -> None:
        """list_item 첫머리 숨김표 글리프(○□△)를 KBR 제72항 글머리형으로 정정(in-place).

        text 체인은 요소 type을 몰라 ○를 숨김표(⠸⠚⠇, KBR-6.13.49)로 변환·emit한다.
        list_item 첫머리의 ○□△는 글머리이므로 글리프(꼬리 ⠇ 제거)와 rule_trail
        (6.13.49→6.14.72)을 정정한다. (태민 정책: 위계 추론 없이 단일 글머리형.)
        """
        lines = bo.braille_lines
        idx = next((i for i, ln in enumerate(lines) if ln.strip()), None)
        if idx is None:
            return
        line = lines[idx]
        for hidden, bullet in _HIDDEN_TO_BULLET.items():
            if not line.startswith(hidden):
                continue
            lines[idx] = bullet + line[len(hidden):]
            # rule_trail: 선두 숨김표(6.13.49, span_start==0) → 글머리(6.14.72)로 교체
            new_trail = []
            replaced = False
            for r in bo.rule_trail:
                if (not replaced and r.rule_id == _RULE_HIDDEN_SINGLE
                        and r.span_start == 0):
                    new_trail.append(make_rule(_RULE_BULLET, span_start=0,
                                               span_end=len(bullet), tag="bullet"))
                    replaced = True
                else:
                    new_trail.append(r)
            if not replaced:
                new_trail.append(make_rule(_RULE_BULLET, span_start=0,
                                           span_end=len(bullet), tag="bullet"))
            bo.rule_trail = new_trail
            return

    def _first_indent(
        self, bo: BrailleOutput, etype: str, is_heading: bool, hlevel: int
    ) -> int:
        """첫 줄 들여쓰기 칸 수. (조판 서식이므로 rule_trail 미기록 — 태민 정책)."""
        if is_heading:
            return _HEADING_DEEP_INDENT if hlevel >= 3 else 0
        if etype == "text":
            return _PARA_INDENT
        if etype == "list_item":
            return _BULLET_LINE_INDENT
        return 0

    def _build_meta(
        self, layout_result: Optional["LayoutResult"]
    ) -> dict:
        """element_id → (type, reading_order, heading_level)."""
        if not layout_result:
            return {}
        return {
            e.element_id: (e.type, e.reading_order, e.heading_level or 0)
            for e in layout_result.elements
        }

    def _partition(
        self, braille_outputs: list[BrailleOutput], meta: dict
    ) -> tuple[list[BrailleOutput], list[BrailleOutput]]:
        """본문 요소와 페이지행 요소(header_footer/page_number) 분리."""
        body, page_line = [], []
        for bo in braille_outputs:
            etype = meta.get(bo.element_id, _DEFAULT_META)[0]
            (page_line if etype in _PAGE_LINE_TYPES else body).append(bo)
        return body, page_line

    def _first_nonempty(self, page_line_items: list[BrailleOutput], meta: dict, want: str) -> str:
        """page_line_items 중 type==want 요소의 첫 비어있지 않은 점자 줄."""
        for bo in page_line_items:
            if meta.get(bo.element_id, _DEFAULT_META)[0] != want:
                continue
            for ln in bo.braille_lines:
                if ln.strip():
                    return ln.strip()
        return ""

    def _footer_text(self, page_line_items: list[BrailleOutput], meta: dict) -> str:
        """페이지행 꼬리말(가운데). header_footer 요소의 첫 줄."""
        return self._first_nonempty(page_line_items, meta, "header_footer")

    def _orig_page_text(self, page_line_items: list[BrailleOutput], meta: dict) -> str:
        """페이지행 원본 페이지 번호(좌측). page_number 요소의 첫 줄."""
        return self._first_nonempty(page_line_items, meta, "page_number")

    def _compose_page_line(self, footer: str, orig_page: str, page_no: int) -> str:
        """페이지행: 원본 페이지번호(좌) · 꼬리말(가운데) · 점자 페이지번호(우) (BBPG 1장2절2)."""
        pn = _page_number_braille(page_no)
        cells = [" "] * _COLS
        for k, ch in enumerate(pn):                       # 우: 점자 페이지 번호
            cells[_COLS - len(pn) + k] = ch
        left_end = 0
        if orig_page:                                     # 좌: 원본 페이지 번호 (첫 칸)
            clip = orig_page[:max(0, _COLS - len(pn) - 1)]
            for k, ch in enumerate(clip):
                cells[k] = ch
            left_end = len(clip)
        if footer:                                        # 가운데: 꼬리말
            avail_start = left_end + (1 if left_end else 0)
            avail = (_COLS - len(pn) - 1) - avail_start
            clipped = footer[:max(0, avail)]
            start = avail_start + max(0, (avail - len(clipped)) // 2)
            for k, ch in enumerate(clipped):
                cells[start + k] = ch
        return "".join(cells)

    def _paginate(
        self, lines: list[str], first_page_no: int, footer: str, orig_page: str = ""
    ) -> list[list[str]]:
        pages: list[list[str]] = []
        pno = first_page_no
        i = 0
        n = len(lines)

        page_idx = 0
        while i < n or not pages:
            while i < n and lines[i] == "":  # 페이지 첫 줄 빈 줄 버림 (plan 주의사항)
                i += 1
            content: list[str] = []
            while i < n and len(content) < _ROWS - 1:
                content.append(lines[i])
                i += 1
            while len(content) < _ROWS - 1:
                content.append("")
            op = self._continuation_orig_page(orig_page, page_idx)
            content.append(self._compose_page_line(footer, op, pno))
            pages.append(content)
            pno += 1
            page_idx += 1
            if i >= n:
                break

        return pages

    def _continuation_orig_page(self, orig_page: str, page_idx: int) -> str:
        """한 원본 페이지가 여러 점자 페이지에 걸칠 때 2번째(page_idx>=1)부터
        원본 번호 앞에 로마자표 없이 알파벳(a,b,c…)을 붙인다 (BBPG 1장2절2-2)(3))."""
        if not orig_page or page_idx == 0:
            return orig_page
        k = page_idx - 1
        suffix = _ALPHA_BRAILLE[k] if k < len(_ALPHA_BRAILLE) else _ALPHA_BRAILLE[-1]
        return suffix + orig_page

    def _save(self, pages: list[list[str]], job_id: str, page_no: int) -> None:
        result_dir = Path(f"storage/jobs/{job_id}/temp/page_{page_no:03d}/result")
        result_dir.mkdir(parents=True, exist_ok=True)
        prefix = f"{page_no:03d}"
        body = "\n".join(line for page in pages for line in page)
        (result_dir / f"{prefix}_result.txt").write_text(body, encoding="utf-8")
        (result_dir / f"{prefix}_result.brf").write_text(body, encoding="utf-8")
