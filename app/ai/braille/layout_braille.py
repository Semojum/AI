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
from app.ai.braille.translator import _BOOK_STYLE  # 도서 관행 스위치(BRAILLE_STYLE)
from app.schemas.content import BrailleOutput

if TYPE_CHECKING:  # 런타임 import 회피 (annotations 지연 평가)
    from app.schemas.layout import LayoutResult

logger = logging.getLogger(__name__)

from app.ai.braille.constants import COLS as _COLS, ROWS as _ROWS, DOUBLE_SIDED  # noqa: E402 (공용 상수)

# ── BBPG 2장2절1 제목 단계별 빈 줄 (level → (앞, 뒤)) ───────────────────────
# BBPG 2장2절1·2장2절2 2)①: 1단계 아래·2단계 아래·3단계 위아래·4단계 위 빈 줄.
# (1·2단계 before는 장/쪽바꿈 근사 — 양면 조판은 DOUBLE_SIDED 참조.)
_HEADING_BLANK: dict[int, tuple[int, int]] = {1: (2, 1), 2: (1, 1), 3: (1, 1), 4: (1, 0)}

# BBPG 2장2절2 2)①④: 표·시각 자료는 위아래에 빈 줄을 삽입한다.
_BLANK_AROUND_TYPES = frozenset({"table", "image", "cartoon", "chart_graph", "diagram"})

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
    "⠸⠴⠇": "⠸⠴",  # ○ 숨김표 → 글머리 (제72항 _0=⠸⠴) — 규정=도서 일치(정답 27회)
    "⠸⠶⠇": "⠸⠶",  # □ → 글머리 (제72항 _7=⠸⠶)
    "⠸⠬⠇": "⠸⠬",  # △ → 글머리 (제72항 _+=⠸⠬)
    # ★ • (가운뎃점 ⠐⠆): 규정 제72항 ⠸⠲(_4) vs 정답 도서 ⠔⠔(99).
    #   정답 코퍼스 1131p 원본 ASCII 직접 스캔: _4는 0회, 줄머리 99가 2,343줄.
    #   같은 스캔에서 _0(○)은 27회 잡히므로 _4=0은 측정 실패가 아니라 도서가 안 쓰는 것.
    #   기본은 관행 ⠔⠔(태민 2026-07-17 재판정 — 텍스트는 정답 도서가 잣대, "거의 틀리면 안돼").
    #   BRAILLE_STYLE=regulation 이면 규정 ⠸⠲로 전환.
    "⠐⠆": "⠔⠔⠀" if _BOOK_STYLE else "⠸⠲⠀",
}
_RULE_BULLET = "KBR-6.14.72"   # 글머리 기호 (제72항)
_RULE_HIDDEN_SINGLE = "KBR-6.13.49"  # 숨김표 단일(제49항) — list_item 첫머리면 글머리로 정정

# ★ 들여쓰기 상수는 "빈칸 개수"다 (규정의 '시작 칸' 숫자가 아님).
#   BBPG "3칸에서 시작" = 글자가 3번째 칸부터 = 앞에 빈칸 2개.
#   정답 코퍼스 1131p/85,600줄 전수 검증: 빈칸은 0(66.0%)·2(31.3%)·4(2.2%)·6(0.4%)칸만
#   나오고 홀수는 사실상 없다 → 규정의 1·3·5·7칸 시작과 정확히 일치.
#   (2026-07-16 이전엔 상수를 시작 칸 숫자 그대로 써서 전 줄이 1칸씩 밀려 있었다.)
_PARA_INDENT = 2        # BBPG 2장2절2 새 문단 "3칸에서 시작" = 앞 빈칸 2 (text)
_BULLET_LINE_INDENT = 2  # BBPG 2장3절5 글머리/목록 "3칸에서 시작" = 앞 빈칸 2 (list_item)

# ★ MinerU는 선택지(①②③…)를 한 요소로 묶어서 낸다. 요소 첫 줄만 들이면 ②③…이
#   이어지는 줄(0칸)로 흘러 정답(각 항목 2칸 시작)과 어긋난다.
#   dev 18p 실측: 줄머리 마커 2개 이상인 요소 31개 → 2칸을 94줄 놓침(실제 손실 112줄의 84%).
#   문장 안의 참조("밑줄 친 ㉠~㉢에")를 항목으로 오인하면 안 되므로 *줄머리*만 본다.
_ITEM_HEAD = re.compile(
    r"^(?:[\u2460-\u2473]"          # ①-⑳
    r"|[\u3260-\u327f]"             # ㉠-㉿
    r"|\([가-힣0-9]\)"                # (가) (1)
    r"|[가-힣]\.\s"                   # 가.
    r"|\d+\.\s)"                    # 1.
)
_HEADING_DEEP_INDENT = 4  # BBPG 2장2절1 3·4단계 제목 "5칸에서 시작" = 앞 빈칸 4
_HEADING_LEVEL2_INDENT = 6  # 2단계 제목 "7칸에서 시작" = 앞 빈칸 6 (BBPG 2장2절1 3)

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
_PARAGRAPH_INDENT = 2  # 새 문단은 "3칸에서 시작" = 앞 빈칸 2

# ── BBPG 2장2절6 출전 ──────────────────────────────────────────────────────
_CITATION_INDENT = 2  # 인용 "3칸에서 시작" = 앞 빈칸 2

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


# 테두리 줄 양 끝 캡: 1단계 ⠿, 위계 2·3단계 위 ⠖…⠲ / 아래 ⠓…⠚ (BBPG-1.2.5(3)·(5))
_BORDER_START_CAPS = frozenset("⠿⠖⠓")
_BORDER_END_CAPS = frozenset("⠿⠲⠚")


def _is_border_line(line: str) -> bool:
    """글상자/표 테두리 줄(32칸, 양 끝이 테두리 캡)인지 — 들여쓰기 금지 대상(B2).

    translator/table_braille가 32칸 테두리를 렌더하고 layout이 위계로 재렌더하므로,
    여기에 문단·글머리 들여(3칸)를 더하면 35칸이 되어 _break_line이 테두리를 망가뜨린다.
    1·2·3단계 캡을 모두 인식한다.
    """
    return (
        len(line) == _COLS
        and line[:1] in _BORDER_START_CAPS
        and line[-1:] in _BORDER_END_CAPS
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
    # 점자 페이지 번호 = 수표 + 숫자 (BBPG 1장2절2 예 1-6: ⠼NN, 끝에 마침표 없음)
    digits = "".join(_DIGIT_MAP.get(c, c) for c in str(n))
    return f"{_NUMBER_INDICATOR}{digits}"


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
    line: str, width: int = _COLS, first_width: Optional[int] = None,
    keep_indent: bool = False,
) -> tuple[list[str], int, list[int]]:
    """한 줄을 width(32) 셀 이하로 분리. 단어 경계 우선, 초과 단어는 하이픈 없이 강제 분리.

    first_width: 첫 출력 줄에 허용할 폭(들여쓰기 칸 예약용). None이면 width.
    keep_indent: 줄머리 빈칸을 첫 출력 줄에 보존한다(기본 False = 종전 동작).
    반환: (분리된 줄 목록, 강제분리 횟수, 줄바꿈이 삽입된 원본 char 오프셋 목록).
    """
    fw = width if first_width is None else first_width
    if _cell_count(line) <= fw:
        return ([line], 0, [])
    if keep_indent:
        # 어절 정규식이 `[^ ⠀]+`라 줄머리 빈칸은 어느 어절에도 안 들어가고 그대로 버려진다.
        # 안 접히는 줄은 위 조기반환으로 들여쓰기를 지키는데 접히는 줄만 잃어서, 같은 표
        # 안에서 들여쓰기가 들쭉날쭉해졌다. 들여쓰기를 떼어 재귀 호출하고 첫 줄에 되붙인다.
        body = line.lstrip(" ⠀")
        lead = line[: len(line) - len(body)]
        if lead:
            out, forced, wraps = _break_line(
                body, width=width, first_width=max(1, fw - _cell_count(lead)))
            if out:
                out[0] = lead + out[0]
            return (out, forced, [w + len(lead) for w in wraps])
    words = [(m.group(), m.start(), m.end()) for m in _WORD_RE.finditer(line)]
    if not words:  # 공백뿐인 줄
        return ([line], 0, [])

    out: list[str] = []
    wraps: list[int] = []
    forced = 0
    cur = ""
    prev_end = -1
    for word, start, end in words:
        cap = fw if not out else width        # 첫 줄만 first_width 적용
        # 어절 사이 간격은 **원본 그대로** 유지한다. 늘 한 칸으로 이어붙이면 표의
        # '열 항목을 두 칸씩 띄어'(지침 §3.1.1(1)②)가 32칸을 넘겨 접히는 순간 한 칸으로
        # 뭉개져 셀 경계가 사라진다(생물 p122 표 첫 줄 실측). 보통 텍스트는 간격이
        # 한 칸이라 동작이 바뀌지 않는다.
        gap = line[prev_end:start] if prev_end >= 0 else " "
        prev_end = end
        candidate = word if not cur else f"{cur}{gap}{word}"
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


def _safe_forced_cut(line: str, limit: int) -> int:
    """단위가 width 초과 시(긴 복합어/수 — §1.2.1(2)) 셀 경계 강제 분리 위치.
    2칸 지시부호(점역자 주 ⠠⠄)가 줄 경계에서 갈리지 않게 한 칸 물러선다."""
    b = max(1, min(limit, len(line)))
    if b < len(line) and line[b - 1] == "⠠" and line[b] == "⠄":
        b -= 1
    return max(1, b)


def _wrap_line(
    line: str, breaks: list[int], width: int = _COLS, first_width: Optional[int] = None,
    keep_indent: bool = False,
) -> tuple[list[str], int]:
    """break offset(음절·어절 경계)에서만 width 이하로 줄바꿈. (분리 줄, 강제분리 수).

    breaks가 비면 어절(공백) 단위 `_break_line`으로 폴백(안전 — 단위 내부 미분리).
    한 단위가 width 초과면 §1.2.1(2)대로 셀 경계 강제 분리(지시부호 보호).
    keep_indent는 그 폴백 경로에만 의미가 있다 — breaks가 있는 주 경로는 `line[start:b]`
    슬라이스라 첫 조각이 줄머리 빈칸을 이미 그대로 물고 간다.
    """
    fw = width if first_width is None else first_width
    if _cell_count(line) <= fw:
        return [line], 0
    if not breaks:
        out, forced, _ = _break_line(line, width=width, first_width=first_width,
                                     keep_indent=keep_indent)
        return out, forced

    cand = sorted(b for b in set(breaks) if 0 < b < len(line))
    out: list[str] = []
    forced = 0
    start = 0
    first = True
    while len(line) - start > (fw if first else width):
        cap = fw if first else width
        limit = start + cap
        usable = [b for b in cand if start < b <= limit]
        if usable:
            b = max(usable)
        else:
            b = _safe_forced_cut(line, limit)
            forced += 1
        out.append(line[start:b])
        start = b
        while start < len(line) and line[start] in (" ", "⠀"):  # 줄머리 공백 버림
            start += 1
        first = False
    if start < len(line):
        out.append(line[start:])
    return (out or [line], forced)


def _find_nth_occurrence(
    lines: list[str], start: int, end: int, glyph: str, rank: int
) -> Optional[tuple[int, int]]:
    """lines[start:end]에서 glyph의 rank번째(0-based, 비중첩) 등장 위치 (line_idx, col)."""
    count = 0
    for li in range(start, min(end, len(lines))):
        line = lines[li]
        pos = line.find(glyph)
        while pos != -1:
            if count == rank:
                return (li, pos)
            count += 1
            pos = line.find(glyph, pos + len(glyph))
    return None


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

        formatted: list[tuple[int, str, list[str]]] = []  # (heading_level, etype, 조판 줄)
        total = 0
        forced_total = 0
        for bo in body:
            etype, _order, hlevel = meta.get(bo.element_id, _DEFAULT_META)
            el_lines, forced = self._format_element(bo, etype, hlevel)
            if not el_lines:                       # 빈 요소는 빈 줄·태깅 없이 건너뜀
                continue
            formatted.append((hlevel, etype, el_lines))
            total += len(el_lines)
            forced_total += forced

        footer = self._footer_text(page_line_items, meta)
        orig_page = self._orig_page_text(page_line_items, meta)
        pages = self._assemble_pages(formatted, footer, orig_page, page_no)
        self._save(pages, job_id, page_no)
        return (forced_total / total) if total else 0.0

    def _assemble_pages(
        self,
        formatted_blocks: list[tuple[int, str, list[str]]],
        footer: str,
        orig_page: str,
        page_no: int,
    ) -> list[list[str]]:
        """이미 조판된 블록 줄들을 페이지로 조립(BBPG): 제목·표·시각자료 빈 줄 + 페이지 + 페이지행.

        재-wrap·들여쓰기는 하지 않는다(블록 줄은 이미 32칸 조판본). layout()(초안)과
        finalize()(편집본)가 공유하는 순수 조립부. 인접 블록의 빈 줄은 하나로 합친다.
        """
        lines: list[str] = []
        trailing = 0   # 현재 lines 끝의 빈 줄 수(인접 블록 빈 줄 중복 방지)
        for hlevel, etype, el_lines in formatted_blocks:
            if not el_lines:
                continue
            before, after = _HEADING_BLANK.get(hlevel, (0, 0))
            if etype in _BLANK_AROUND_TYPES:        # 표·시각자료 위아래(BBPG 2장2절2 2)①④)
                before, after = max(before, 1), max(after, 1)
            lines.extend([""] * max(0, before - trailing))
            lines.extend(el_lines)
            lines.extend([""] * after)
            trailing = after
        return self._paginate(lines, page_no, footer, orig_page)

    def finalize(self, blocks: list[dict], page_no: int = 1) -> list[list[str]]:
        """점역사가 편집한 블록(이미 32칸 줄)을 규정대로 페이지 조립(REST /finalize 전용).

        blocks 항목: {type, heading_level, order, lines:[점자 줄...]}.
        page_number/header_footer type은 페이지행으로 분리. 본문은 order로 정렬.
        재-wrap 없음(줄 단위 편집 가정) — 점자 규정 조판은 AI가 소유, BE/FE는 호출만.
        반환: 점자 페이지 목록(각 32칸×25줄).
        """
        def _first_line(want: str) -> str:
            for b in blocks:
                if b.get("type") == want:
                    for ln in b.get("lines", []):
                        if ln.strip():
                            return ln.strip()
            return ""

        body = sorted(
            (b for b in blocks if b.get("type") not in _PAGE_LINE_TYPES),
            key=lambda b: b.get("order", 1_000_000),
        )
        formatted = [(int(b.get("heading_level") or 0), b.get("type") or "", list(b.get("lines", [])))
                     for b in body]
        footer = _first_line("header_footer")
        orig_page = _first_line("page_number")
        return self._assemble_pages(formatted, footer, orig_page, page_no)

    def _format_element(
        self, bo: BrailleOutput, etype: str, hlevel: int
    ) -> tuple[list[str], int]:
        """요소 점자 줄 → 들여쓰기·정렬·32칸 브레이킹 적용. (표시 줄, 강제분리 수).

        조판 결과(out)를 **bo.braille_lines에 write-back**한다 — FE가 받는 contents가
        곧 최종 조판본(들여·줄바꿈·가운데정렬 반영)이 되도록(태민 원칙: FE는 보이는
        그대로 하이라이트, AI가 좌표 완성). rule_trail 요소-로컬 좌표도 조판 후 프레임으로
        재매핑한다(내용 기반 탐색 — 비공백 글리프는 조판이 순서·개수를 보존하므로 안전).
        조판 서식 규칙 자체는 rule_trail로 기록하지 않는다(태민 정책 2026-06-01: 내용 변환만).
        내용이 없는 요소(빈 줄뿐)는 빈 결과를 반환한다.
        """
        # 시각요소 drafts와 rule_trail 객체 공유 시 in-place 변형이 새지 않도록 분리.
        bo.rule_trail = [r.model_copy() for r in bo.rule_trail]
        self._expand_box_borders(bo)
        if not any(ln.strip() for ln in bo.braille_lines):
            return [], 0
        # 글머리표는 요소 타입이 아니라 "줄머리에 글머리 글리프가 있는가"로 결정된다.
        # dev 18p 실측: 불릿을 가진 요소가 list_item 5 / text 5로 반반이라 둘 다 본다.
        if etype in ("list_item", "text"):
            self._apply_bullet_marker(bo)
        is_heading = hlevel >= 1
        first_indent = self._first_indent(bo, etype, is_heading, hlevel)
        self._mark_item_lines(bo, etype, first_indent)
        if first_indent and any(_is_border_line(ln) for ln in bo.braille_lines):
            # 정식 규칙(테두리 아키텍처 B안 확정 2026-06-02): 32칸 테두리 줄(글상자 BBPG-1.2.5·
            # 표 격자)은 layout이 폭을 소유하므로 들여쓰기를 적용하지 않는다. 들이면 35칸이 되어
            # _break_line이 테두리를 분리해 깨진다. (글상자 테두리는 _expand_box_borders가 재렌더.)
            logger.debug(
                "layout: %s 요소(%s) 32칸 테두리 — 들여쓰기 미적용(정식)", etype, bo.element_id,
            )
            first_indent = 0

        orig_lines = list(bo.braille_lines)   # 조판 전 스냅샷(좌표 재매핑 기준)
        # 규정 골격 요소(만화 5칸 장면/3칸 대사·시각자료 제목 5칸)는 줄마다 들여쓰기가 다르다.
        # line_indents가 줄 수와 맞으면 줄별 들여쓰기를 적용(첫 줄만 들이는 기본 동작 대체).
        per_line = (bo.line_indents
                    if bo.line_indents is not None and len(bo.line_indents) == len(orig_lines)
                    else None)
        out: list[str] = []
        line_slices: list[tuple[int, int]] = []  # orig 줄 → out 줄 범위 [start, end)
        forced_total = 0
        # 표는 들여쓰기를 줄 문자열에 직접 박아 낸다(3칸 = 앞 빈칸 2, §3.1.1(1)②; 제목은
        # 5칸 §3.1.3(1)). 다른 타입은 _first_indent/line_indents로 layout이 들여쓰기를
        # 소유하므로 문자열 줄머리가 비어 있다 — 그래서 이 보존은 표 경로에만 건다.
        # 정답 도서 실측(생물 p122): 접힌 표 줄은 첫 줄 2칸·이어지는 줄 0칸이다.
        keep_indent = etype == "table"
        for li, orig in enumerate(orig_lines):
            indent = per_line[li] if per_line is not None else (first_indent if li == 0 else 0)
            fw = (_COLS - indent) if indent else None
            br = bo.break_points[li] if li < len(bo.break_points) else []
            broken, forced = _wrap_line(orig, br, _COLS, first_width=fw,
                                        keep_indent=keep_indent)
            if indent and broken:               # 표시용 들여쓰기
                broken[0] = " " * indent + broken[0]
            if is_heading and hlevel == 1:       # 1단계 제목 가운데 정렬
                broken = [_center(b) for b in broken]
            start = len(out)
            out.extend(broken)
            line_slices.append((start, len(out)))
            forced_total += forced

        self._remap_trail_to_formatted(bo, orig_lines, out, line_slices)
        bo.braille_lines = out                # contents = 최종 조판본
        # 모든 초안(피커 대안)을 32칸 조판한다(#4). 선택 초안 = 본문(proto 계약
        # contents == drafts[selected_idx].contents). 시각요소는 들여/가운데 없음(_first_indent=0)
        # 이라 음절 줄바꿈만 적용 → 점역사가 대안을 골라도 contents가 깨지지 않는다.
        for di, d in enumerate(bo.drafts):
            if di == bo.selected_idx:
                d.braille_lines = out
                continue
            d_out: list[str] = []
            for li, dl in enumerate(d.braille_lines):
                dbr = d.break_points[li] if li < len(d.break_points) else []
                seg, _ = _wrap_line(dl, dbr, _COLS)
                d_out.extend(seg)
            d.braille_lines = d_out
        return out, forced_total

    @staticmethod
    def _remap_trail_to_formatted(
        bo: BrailleOutput,
        orig_lines: list[str],
        out: list[str],
        line_slices: list[tuple[int, int]],
    ) -> None:
        """rule_trail 요소-로컬 좌표를 조판 후(out) 프레임으로 재매핑(in-place).

        내용 기반: 조판은 비공백 글리프의 순서·개수를 보존하므로(공백 재배치·들여·가운데
        패딩만 추가), 원본 줄에서 글리프의 등장 순번(rank)을 구해 out의 같은 순번 위치를 찾는다.
        강제분리가 글리프 가운데를 끊는 드문 경우엔 못 찾으면 좌표를 유지(best-effort).
        """
        for r in bo.rule_trail:
            if r.line_no < 0 or r.line_no >= len(orig_lines):
                continue  # -1 = 요소 전체 / 안전
            orig = orig_lines[r.line_no]
            seg_start, seg_end = line_slices[r.line_no]
            glyph = orig[r.col_start:r.col_end]
            if not glyph:  # 점 태그(col_start==col_end): 해당 줄 첫 서브라인 시작으로
                r.line_no = seg_start if seg_start < seg_end else r.line_no
                continue
            rank = orig.count(glyph, 0, r.col_start)  # col_start 앞 등장 횟수
            located = _find_nth_occurrence(out, seg_start, seg_end, glyph, rank)
            if located is not None:
                nl, nc = located
                r.line_no, r.col_start, r.col_end = nl, nc, nc + len(glyph)

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
        old_breaks = bo.break_points
        si = 0
        new_lines: list[str] = []
        new_breaks: list[list[int]] = []   # new_lines와 1:1 (삽입 줄은 [])
        index_map: dict[int, int] = {}  # 옛 줄 인덱스 → 새 줄 인덱스(내용 줄만)
        for old_idx, ln in enumerate(bo.braille_lines):
            if si < len(specs) and _is_border_line(ln):
                spec = specs[si]
                si += 1
                if spec.kind == "top":
                    new_lines.append("")  # 위 한 줄 띔
                    top = self._render_box_top(spec.level, spec.title)
                    new_lines.extend(top)
                    new_breaks.extend([[]] * (1 + len(top)))
                else:
                    new_lines.append(self._render_box_bottom(spec.level))
                    new_lines.append("")  # 아래 한 줄 띔
                    new_breaks.extend([[], []])
            else:
                index_map[old_idx] = len(new_lines)
                new_lines.append(ln)
                new_breaks.append(old_breaks[old_idx] if old_idx < len(old_breaks) else [])
        # 줄별 들여쓰기(규정 골격)도 새 줄 수에 맞춰 재매핑 — 삽입된 테두리·빈 줄은 0칸,
        # 내용 줄은 index_map으로 들여쓰기 보존(테두리 묶기 + 위계 들여쓰기 공존, Q11).
        if bo.line_indents is not None and len(bo.line_indents) == len(bo.braille_lines):
            new_indents = [0] * len(new_lines)
            for old_idx, new_idx in index_map.items():
                new_indents[new_idx] = bo.line_indents[old_idx]
            bo.line_indents = new_indents
        bo.braille_lines = new_lines
        bo.break_points = new_breaks
        # 빈 줄·테두리 삽입으로 내용 줄이 밀렸으므로 rule_trail 요소-로컬 line_no 재매핑.
        for r in bo.rule_trail:
            if r.line_no >= 0 and r.line_no in index_map:
                r.line_no = index_map[r.line_no]

    def _apply_bullet_marker(self, bo: BrailleOutput) -> None:
        """list_item 첫머리 숨김표 글리프(○□△)를 KBR 제72항 글머리형으로 정정(in-place).

        text 체인은 요소 type을 몰라 ○를 숨김표(⠸⠚⠇, KBR-6.13.49)로 변환·emit한다.
        list_item 첫머리의 ○□△는 글머리이므로 글리프(꼬리 ⠇ 제거)와 rule_trail
        (6.13.49→6.14.72)을 정정한다. (태민 정책: 위계 추론 없이 단일 글머리형.)
        """
        lines = bo.braille_lines
        # ★ 요소 안의 *모든* 줄머리를 본다. MinerU가 여러 글머리 항목을 한 요소로 묶어
        #   내므로(선택지와 동일 구조), 첫 줄만 보면 나머지를 놓친다.
        #   dev 11p 실측: 첫 줄만 보면 ⠔⠔ 7개(정답 44개).
        for idx, line in enumerate(lines):
            if not line.strip():
                continue
            for hidden, bullet in _HIDDEN_TO_BULLET.items():
                if not line.startswith(hidden):
                    continue
                lines[idx] = bullet + line[len(hidden):]
                # 글리프 길이 변화(delta)만큼 같은 줄 뒤 좌표·break offset을 보정.
                delta = len(hidden) - len(bullet)
                if delta and idx < len(bo.break_points):
                    bo.break_points[idx] = [
                        (b - delta) if b >= len(hidden) else b
                        for b in bo.break_points[idx]
                    ]
                new_trail = []
                replaced = False
                for r in bo.rule_trail:
                    if (not replaced and r.rule_id == _RULE_HIDDEN_SINGLE
                            and r.line_no == idx and r.col_start == 0):
                        new_trail.append(make_rule(_RULE_BULLET, line_no=idx, col_start=0,
                                                   col_end=len(bullet), tag="bullet"))
                        replaced = True
                    else:
                        if delta and r.line_no == idx and r.col_start > 0:
                            r = r.model_copy(update={
                                "col_start": max(0, r.col_start - delta),
                                "col_end": max(0, r.col_end - delta),
                            })
                        new_trail.append(r)
                if not replaced:
                    new_trail.append(make_rule(_RULE_BULLET, line_no=idx, col_start=0,
                                               col_end=len(bullet), tag="bullet"))
                bo.rule_trail = new_trail
                break          # 이 줄은 처리됨 → 다음 줄로

    def _mark_item_lines(self, bo, etype: str, first_indent: int) -> None:
        """묶인 항목(①②③…)의 줄머리마다 들여쓰기를 준다.

        MinerU는 선택지를 한 요소로 묶어서 낸다. 기본 동작(첫 줄만 들여)이면 ②③…이
        이어지는 줄(0칸)로 흘러 정답(각 항목 2칸 시작)과 어긋난다.
        원문(corrected_text) 줄과 braille_lines가 1:1이므로 원문 줄머리로 판정한다.
        (점자만 보면 수표+숫자가 일반 숫자와 구분되지 않는다.)
        """
        if etype not in ("list_item", "text") or not first_indent:
            return
        if getattr(bo, "line_indents", None) is not None:  # 골격 들여쓰기 있으면 유지
            return
        src = (getattr(bo, "corrected_text", "") or "").split("\n")
        if len(src) != len(bo.braille_lines) or len(src) < 2:
            return
        heads = [i for i, ln in enumerate(src) if _ITEM_HEAD.match(ln.strip())]
        if len(heads) < 2:                   # 항목이 하나뿐이면 기본 동작으로 충분
            return
        bo.line_indents = [first_indent if i in set(heads) else 0 for i in range(len(src))]

    def _first_indent(
        self, bo: BrailleOutput, etype: str, is_heading: bool, hlevel: int
    ) -> int:
        """첫 줄 들여쓰기 칸 수. (조판 서식이므로 rule_trail 미기록 — 태민 정책)."""
        if is_heading:
            if hlevel >= 3:
                return _HEADING_DEEP_INDENT  # 3·4단계 5칸
            if hlevel == 2:
                return _HEADING_LEVEL2_INDENT  # 2단계 3칸
            return 0  # 1단계는 가운데 정렬(별도 처리)
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
            # 양면 제본이면 홀수 점자페이지만 페이지행, 짝수는 26줄 본문(BBPG 1장2절2). 단면은 매 페이지.
            has_page_line = (not DOUBLE_SIDED) or (pno % 2 == 1)
            cap = (_ROWS - 1) if has_page_line else _ROWS
            content: list[str] = []
            while i < n and len(content) < cap:
                content.append(lines[i])
                i += 1
            while len(content) < cap:
                content.append("")
            if has_page_line:
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
