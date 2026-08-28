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
from typing import TYPE_CHECKING, NamedTuple, Optional

from app.ai.braille.kor_math_rules import _NUMBER_INDICATOR, _DIGIT_MAP
from app.ai.braille.regulations import make_rule
from app.ai.braille.translator import _BOOK_STYLE  # 도서 관행 스위치(BRAILLE_STYLE)
from app.schemas.content import BrailleOutput, RuleApplication

if TYPE_CHECKING:  # 런타임 import 회피 (annotations 지연 평가)
    from app.schemas.layout import LayoutResult

logger = logging.getLogger(__name__)

from app.ai.braille.constants import COLS as _COLS, ROWS as _ROWS, DOUBLE_SIDED  # noqa: E402 (공용 상수)

# ── BBPG 2장2절1 제목 단계별 빈 줄 (level → (앞, 뒤)) ───────────────────────
# 근거 조항은 BBPG 2장2절2 2)(2)① 하나다 — 빈 줄을 넣어도 되는 자리를 **열거**한다:
#   "1단계 제목의 아래, 2단계 제목의 아래, 3단계 제목의 위아래, 4단계 제목의 위"
# 같은 조 (1)이 "시각적 효과·공간적 배치를 위해 삽입된 빈 줄은 점자에서는 삭제한다"라
# 못 박으므로, 열거에 없는 자리에 빈 줄을 넣으면 규정 위반이다.
#  · 1단계 before=0 — 열거에 '1단계 제목의 위'가 없다. 2장2절1 1)의 **장바꿈**은 빈 줄이
#    아니라 새 장이고, 통 문자열에는 장/쪽바꿈을 실을 자리가 없다(면 나눔은 FE·BE 소관).
#    2026-08-07까지 여기 2가 박혀 있었는데 어느 조항에도 없는 값이었다.
#  · 2단계 before=1 — 2장2절1 3) 다만 "본문 내용이 적어 쪽바꿈이 빈번할 경우에는 제목
#    위아래에 빈 줄을 두고 이어 적을 수 있다". 교과서가 이 경우라 예외를 채택한다.
_HEADING_BLANK: dict[int, tuple[int, int]] = {1: (0, 1), 2: (1, 1), 3: (1, 1), 4: (1, 0)}

# BBPG 3장2절1 2) "모든 시각 자료의 위아래는 한 줄을 띈다. 다만, 시각 자료가 연이어 나올
# 때 그 사이는 줄을 띄지 않는다." — 표는 여기서 뺀다. 3장1절4)(3)이 "표가 연이어 나올 때
# 그 사이에는 빈 줄을 둔다"로 정반대라, 둘을 같이 다루면 한쪽이 반드시 틀린다.
_VISUAL_TYPES = frozenset({"image", "cartoon", "chart_graph", "diagram"})

# BBPG 2장2절2 2)(2)④·3장1절4)(1)·3장2절1 2): 표·시각 자료는 위아래에 빈 줄을 삽입한다.
_BLANK_AROUND_TYPES = _VISUAL_TYPES | {"table"}

# 단어 구분 = ASCII 공백 또는 점자 빈칸(U+2800)
_WORD_RE = re.compile(r"[^ ⠀]+")

# rule_trail rule_id (regulations.json 키)
_RULE_LINE_WRAP = "BBPG-1.2.1"      # 줄바꿈(32칸), tag=line_wrap
# 인라인 태그(§3-5 `<!이름>`/`<!/이름>`) 제거용 — 발문 판정은 묵자만 본다.
_TAG_RE = re.compile(r"<!/?[^>]+>")
_RULE_HEADING_BLANK = "BBPG-2.2.1"  # 단계별 제목 표기, tag=heading_blank
_RULE_PARA_INDENT = "BBPG-2.2.2"    # 문단 형식(새 문단 3칸), tag=indent
_RULE_BULLET_INDENT = "BBPG-2.3.5"  # 글머리 3칸, tag=indent
_RULE_BOX_BORDER = "BBPG-1.2.5"     # 글상자 테두리(Step17 emit), tag=box_top/box_bottom·N단계

# ── KBR 제72항 글머리 기호: 숨김표 글리프(_..l, 꼬리 ⠇) → 글머리형(_.., 꼬리 없음) ──
# ○□△가 list_item 글머리로 쓰이면 숨김표(제49항)가 아니라 글머리형(제72항)이어야 한다.
# text 체인은 문맥을 몰라 숨김표로 변환·emit하므로 여기서 글리프·rule을 글머리로 정정한다.
_HIDDEN_TO_BULLET: dict[str, str] = {
    "⠸⠴⠇": "⠸⠴",  # ○ 숨김표 → 글머리 (제72항 _0=⠸⠴) — 규정=도서 일치(정답 27회)
    "⠸⠶⠇": "⠸⠶",  # □ → 글머리 (제72항 _7=⠸⠶)
    "⠸⠬⠇": "⠸⠬",  # △ → 글머리 (제72항 _+=⠸⠬)
    # ⚠ • 가운뎃점 분기를 지웠다(2026-08-15) — 죽은 분기였다. symbol_table이 점역
    #   단계에서 •를 먼저 글머리 셀로 바꾸므로 ⠐⠆인 채 여기까지 오지 않는다.
    #   글머리 점형은 symbol_rules._SYMBOL_BULLET이 정본이다.
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
# 페이지행으로 빠지는 요소 타입 — **원본 페이지 번호(page_number)뿐이다.**
# 종전에는 header_footer도 여기 있었고 그 첫 요소가 꼬리말 슬롯에 잘려 들어갔는데,
# 인쇄 러닝풋은 pipeline._is_running_foot·_is_boilerplate가 이미 상류에서 걷어 내므로
# 여기까지 오는 header_footer는 러닝풋이 아니라 **강 도입부 본문**이다(a5fa765 실측).
# 근거는 _partition·_footer_text 주석 참조.
_PAGE_LINE_TYPES = {"page_number"}

# 꼬리말로 쓰는 제목 단계 — 점자 도서 제작 지침 제1장 3-3) "해당 페이지의 1, 2단계 제목".
# 1단계를 우선하고, 같은 단계면 읽기순서가 앞선 것을 쓴다(_footer_text 주석).
_FOOTER_HEADING_LEVELS = (1, 2)

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
# ★ 점자 지면의 빈칸은 전부 U+2800 이다(대표 지적 R1, 2026-08-24). 종전에는 낱말 사이만
#   U+2800 이고 **줄머리 들여쓰기는 ASCII 공백**이었다(실측 한 쪽: U+0020 1,215 · U+2800 302).
#   점수에는 영향이 없다(`kpi_v2.cells_only` 가 공백을 버린다). 표시·역점역·내보내기가 흔들린다.
#   ⚠ `.brf`(BRF-ASCII) 내보내기는 `unicode_to_ascii` 가 담당하고 그쪽 빈칸은 U+0020 이 맞다.
#     여기서 바꾸는 것은 **유니코드 점자 층**뿐이다.
_PAD = "⠀"              # 들여쓰기·정렬에 쓰는 점자 빈칸
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
_BOX_TITLE_INDENT = 4  # 케이스① 제목 윗줄 "5칸에서 시작" = 앞 빈칸 4 (2026-08-10 정정)


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


def _tail_blanks(lines: list[str]) -> int:
    """줄 목록 끝에 실제로 쌓여 있는 빈 줄 수."""
    n = 0
    for ln in reversed(lines):
        if ln.strip():
            break
        n += 1
    return n


def _lead_blanks(lines: list[str]) -> int:
    """줄 목록 앞에 실제로 붙어 있는 빈 줄 수(글상자 위 띔 등 요소가 이미 달고 온 것)."""
    n = 0
    for ln in lines:
        if ln.strip():
            break
        n += 1
    return n


def format_underline_blank(text: str) -> str:
    """밑줄 빈칸(_+)을 ⠸⠤ 1개로 치환 — 길이 무관 (BBPG 2장2절3)."""
    return re.sub(r"_+", _UNDERLINE_BLANK_MARKER, text)


def format_citation(text: str) -> str:
    """출전 정보를 다음 줄 3칸에 배치 (BBPG 2장2절6)."""
    return _PAD * _CITATION_INDENT + text


def format_paragraph_start(text: str) -> str:
    """새 문단을 3칸에서 시작 (BBPG 2장2절2 문단 형식)."""
    return _PAD * _PARAGRAPH_INDENT + text


def format_bullet_item(text: str, tier: int) -> str:
    """글머리 기호: 3칸 표기, tier 1→⠸⠴(동그라미) 2→⠤(붙임표), 기호 뒤 1칸 (BBPG 2장3절5)."""
    marker = _BULLET_MARKERS.get(min(max(tier, 1), 2), _BULLET_MARKERS[2])
    return _PAD * _BULLET_INDENT + f"{marker}{_PAD}{text}"


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
    return _PAD * pad + text


def _cell_count(text: str) -> int:
    """점자 셀 수 = 문자 수. 점역 후 1점자셀=1 코드포인트(U+2800~28FF), 공백 1셀."""
    return len(text)


def _center(text: str, width: int = _COLS) -> str:
    """text를 width 안에서 가운데 정렬 (BBPG 2장2절1 1단계 제목)."""
    t = text.strip()
    if _cell_count(t) >= width:
        return t
    return _PAD * ((width - _cell_count(t)) // 2) + t


# 가운데에 빈칸을 품어서 어절 분리(`[^ ⠀]+`)로 갈리면 안 되는 기호들 (원장 C-16).
_ATOMIC_SEQS = ("⠸⠦⠀⠴⠇",)   # 규정 제73항 네모 빈칸
_ATOMIC_SENTINEL = "\x01"     # 길이 1 — 1:1 치환이라 wraps 오프셋이 안 밀린다


def _break_line(
    line: str, width: int = _COLS, first_width: Optional[int] = None,
    keep_indent: bool = False,
) -> tuple[list[str], int, list[int]]:
    """한 줄을 width(32) 셀 이하로 분리. 단어 경계 우선, 초과 단어는 하이픈 없이 강제 분리.

    first_width: 첫 출력 줄에 허용할 폭(들여쓰기 칸 예약용). None이면 width.
    keep_indent: 줄머리 빈칸을 첫 출력 줄에 보존한다(기본 False = 종전 동작).
    반환: (분리된 줄 목록, 강제분리 횟수, 줄바꿈이 삽입된 원본 char 오프셋 목록).
    """
    if any(seq in line for seq in _ATOMIC_SEQS):
        # 가운데에 빈칸이 든 기호는 어절 분리(`[^ ⠀]+`)가 반으로 가른다. 규정 제73항
        # 네모 빈칸 ⠸⠦⠀⠴⠇이 그렇다 — 32칸 경계에 걸리면 ⠸⠦가 줄 끝, ⠴⠇가 다음 줄로
        # 갈려 점역사가 빈칸이 어디서 끝나는지 못 읽는다(전수 확인: 14개 위치 중 3개).
        # 빈칸을 같은 길이 sentinel로 바꿔 한 어절로 만들고, 접은 뒤 되돌린다.
        # 1:1 치환이라 wraps 오프셋은 그대로 유효하다.
        guarded = line
        for seq in _ATOMIC_SEQS:
            guarded = guarded.replace(seq, seq.replace("⠀", _ATOMIC_SENTINEL))
        out, forced, wraps = _break_line(guarded, width, first_width, keep_indent)
        return ([o.replace(_ATOMIC_SENTINEL, "⠀") for o in out], forced, wraps)
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

    reading_order 정렬 → page_number(페이지행) 분리 → 제목 단계별 빈 줄 →
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
        # 발문을 만나면 그 문항이 끝날 때까지 '지문 구간'이다(원장 C-33). 발문과 상자
        # 사이에 단서 `(단, …)`·그림 캡션이 끼는 일이 잦아 직전 요소만 보면 2/6밖에 못 잡는다.
        # 구간은 다음 **제목**에서 닫는다 — 제목이 나오면 새 단락·새 개념 설명이다.
        in_passage = False
        for bo in body:
            etype, _order, hlevel = meta.get(bo.element_id, _DEFAULT_META)
            if etype == "title":
                in_passage = False
            el_lines, forced = self._format_element(bo, etype, hlevel, tight_box=in_passage)
            if self._is_prompt_text(getattr(bo, "corrected_text", "") or ""):
                in_passage = True
            if not el_lines:                       # 빈 요소는 빈 줄·태깅 없이 건너뜀
                continue
            formatted.append((hlevel, etype, el_lines))
            total += len(el_lines)
            forced_total += forced

        self._c6_clip_page_line_items(page_line_items, meta)
        footer = self._footer_text(body, meta)
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
        finalize()(편집본)가 공유하는 순수 조립부.

        ★ 인접 빈 줄 병합은 **실제로 쌓인 빈 줄**을 세서 한다(선언값 before/after가 아니라).
        `_expand_box_borders`가 글상자 위아래 빈 줄을 el_lines **안에** 박아 넣기 때문이다 —
        선언값만 보면 그게 안 보여서 요소 경계 빈 줄이 그 위에 또 얹혔다. dev-2027 200쪽
        실측: 빈 줄 두 줄 연속 72곳·세 줄 4곳. 정답 도서는 3,811곳 중 2곳(0.05%)뿐이다.
        규정도 겹치기를 허용하지 않는다 — 글상자 연속은 1장2절5(6)이 "빈 줄"(한 줄)이다.
        """
        lines: list[str] = []
        prev_type = ""
        pending = 0    # 직전 요소가 요구한 '아래 빈 줄' — 다음 요소의 '위'와 합쳐 한 줄로 낸다
        for hlevel, etype, el_lines in formatted_blocks:
            if not el_lines:
                continue
            before, after = _HEADING_BLANK.get(hlevel, (0, 0))
            if etype in _BLANK_AROUND_TYPES:        # 표·시각자료 위아래(BBPG 2장2절2 2)(2)④)
                before, after = max(before, 1), max(after, 1)
            # 요소가 스스로 달고 온 앞뒤 빈 줄(글상자 위아래 띔 §1.2.5(6))도 같은 '한 줄'
            # 요구다. 떼어 내 before/after에 합치면 경계 빈 줄과 겹칠 일이 없다.
            lead, tail = _lead_blanks(el_lines), _tail_blanks(el_lines)
            body = el_lines[lead:len(el_lines) - tail] or el_lines
            before, after = max(before, min(lead, 1)), max(after, min(tail, 1))
            if (etype in _VISUAL_TYPES and prev_type in _VISUAL_TYPES
                    and not _is_border_line(body[0])
                    and not _is_border_line(
                        next((ln for ln in reversed(lines) if ln.strip()), ""))):
                # BBPG 3장2절1 2) 다만 — 시각 자료가 연이어 나올 때 그 사이는 안 띈다.
                # 글상자로 묶인 것끼리는 예외다 — 1장2절5(6)이 "사이에 빈 줄"이라 반대다.
                before = pending = 0
            if (pending or before) and lines:       # 두 줄 이상 띄는 자리는 규정에 없다
                lines.append("")
            lines.extend(body)
            pending = after
            prev_type = etype
        if pending:
            lines.append("")
        return self._paginate(lines, page_no, footer, orig_page)

    def finalize(self, blocks: list[dict], page_no: int = 1) -> list[list[str]]:
        """점역사가 편집한 블록(이미 32칸 줄)을 규정대로 페이지 조립(REST /finalize 전용).

        blocks 항목: {type, heading_level, order, lines:[점자 줄...]}.
        page_number type만 페이지행으로 분리(header_footer는 본문 — _partition 주석).
        본문은 order로 정렬.
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
        # 꼬리말 = 페이지의 1·2단계 제목 (지침 제1장 3-3) — _footer_text 주석과 같은 규칙)
        footer = ""
        for lvl in _FOOTER_HEADING_LEVELS:
            cands = [b for b in body if int(b.get("heading_level") or 0) == lvl]
            for b in cands:
                line = next((ln.strip() for ln in b.get("lines", []) if ln.strip()), "")
                if line:
                    footer = line
                    break
            if footer:
                break
        orig_page = _first_line("page_number")
        return self._assemble_pages(formatted, footer, orig_page, page_no)

    def _format_element(
        self, bo: BrailleOutput, etype: str, hlevel: int, *, tight_box: bool = False
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
        self._expand_box_borders(bo, tight=tight_box)
        if not any(ln.strip() for ln in bo.braille_lines):
            return [], 0
        # 글머리표는 요소 타입이 아니라 "줄머리에 글머리 글리프가 있는가"로 결정된다.
        # dev 18p 실측: 불릿을 가진 요소가 list_item 5 / text 5로 반반이라 둘 다 본다.
        if etype in ("list_item", "text"):
            self._apply_bullet_marker(bo)
        is_heading = hlevel >= 1
        first_indent = self._first_indent(bo, etype, is_heading, hlevel)
        self._mark_item_lines(bo, etype, first_indent)
        # 32칸 테두리 줄(글상자 BBPG-1.2.5·표 격자)은 layout이 폭을 소유하므로 들이지 않는다
        # — 들이면 35칸이 되어 _break_line이 테두리를 쪼갠다. 그렇다고 요소 전체의 들여쓰기를
        # 버리면 글상자 안 문단이 0칸에서 시작해 gold와 어긋난다(원장 C-01b) — 첫 들여쓰기를
        # **테두리 안 첫 줄**로 옮긴다. ★ `_indent_lines`(통 문자열)와 같은 판정이어야 한다.
        # -1 = 테두리뿐인 요소(시각자료 껍데기) — 아무 줄도 들이지 않는다.
        first_at = next((i for i, ln in enumerate(bo.braille_lines)
                         if ln.strip() and not _is_border_line(ln)), -1)

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
            indent = (per_line[li] if per_line is not None
                      else (first_indent if li == first_at else 0))
            fw = (_COLS - indent) if indent else None
            br = bo.break_points[li] if li < len(bo.break_points) else []
            broken, forced = _wrap_line(orig, br, _COLS, first_width=fw,
                                        keep_indent=keep_indent)
            if indent and broken:               # 표시용 들여쓰기
                broken[0] = _PAD * indent + broken[0]
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
        title_lines = [_PAD * _BOX_TITLE_INDENT + c for c in chunks]
        return title_lines + [start + fill * inner + end]

    def _render_box_bottom(self, level: int) -> str:
        """아래 테두리 줄 렌더 (BBPG-1.2.5)."""
        start, fill, end = _BOX_LEVELS.get(level, _BOX_LEVELS[1])["bottom"]
        return start + fill * (_COLS - 2) + end

    @staticmethod
    def _is_prompt_text(src: str) -> bool:
        """이 요소가 **발문·지시문**인가 — 뒤따르는 글상자를 '지문 상자'로 보는 신호.

        원장 C-33. 조항이 둘 겹쳐 있다:
          §2.1.6(5) 글상자 위아래를 한 줄씩 띈다.
                    단, 평가문제에서 글상자가 지문으로 제시된 경우 '4.2.2 (2)'를 따른다.
          §4.2.2(2) 발문과 선택지, 발문과 지문, 지시문과 지문 사이에는 **빈 줄을 두지 않는다.**

        우리는 §2.1.6(5)만 보고 상자 위아래를 전부 띄웠다(실측 10쪽: 위 100%·아래 94%).
        정답 도서는 2,917쪽에서 위 21.1%·아래 31.1%다 — 관행이 아니라 **규정과 맞는 값**이다
        (일반 상자는 띄고 지문 상자는 안 띈다).

        판정은 **묵자 원문**으로 한다. 점자 물음표 `⠦`는 여는 따옴표·괄호와 같은 점형이라
        조판된 줄만 보고 가르면 오탐이 난다.
        """
        t = _TAG_RE.sub("", src or "").strip()
        if not t:
            return False
        last = t.splitlines()[-1].strip()
        return last.endswith(("?", "？"))

    def _expand_box_borders(self, bo: BrailleOutput, *, tight: bool = False) -> None:
        """글상자 테두리 위치 마커(인라인 32칸 줄)를 box_borders와 순서대로 짝지어 재렌더(in-place).

        translator가 남긴 32칸 테두리 줄을 위계·제목 배치로 다시 그리고(BBPG-1.2.5),
        글상자 위아래에 빈 줄을 넣는다(1.2.5(5)). box_borders 없으면 변경 없음.

        ★ Step17(2026-08-08) — 그린 테두리마다 근거를 남긴다(BBPG-1.2.5, tag=box_top/box_bottom).
          여기가 대표가 지목한 "레이아웃 관련 점자 기호를 왜 그걸 골랐는지"의 핵심이다.
          이 테두리는 묵자에 점자 기호로 적혀 있던 것이 아니라 **우리가 판단해서 넣은 것**이다
          — LLM 태깅(`text_opt._TAG_PROMPT`)이나 `pdf_analyzer`의 벡터 사각형 검출이 "이건
          글상자다"라고 결정한 결과다. 게다가 원장 C-01a·C-01b는 이 항목을 "규정 모호 →
          관행 채택"으로 분류해 점역사 자문 대상으로 올려 뒀다((A)이자 (B)).
          실측(dev 400쪽): 위 테두리 520개·아래 522개가 rule_trail **0건**으로 나갔다.
        """
        if not bo.box_borders:
            return
        specs = list(bo.box_borders)
        old_breaks = bo.break_points
        si = 0
        new_lines: list[str] = []
        new_breaks: list[list[int]] = []   # new_lines와 1:1 (삽입 줄은 [])
        index_map: dict[int, int] = {}  # 옛 줄 인덱스 → 새 줄 인덱스(내용 줄만)
        border_trail: list[RuleApplication] = []
        for old_idx, ln in enumerate(bo.braille_lines):
            if si < len(specs) and _is_border_line(ln):
                spec = specs[si]
                si += 1
                if spec.kind == "top":
                    if not tight:
                        new_lines.append("")  # 위 한 줄 띔 (§2.1.6(5))
                    top = self._render_box_top(spec.level, spec.title)
                    border_trail.append(self._border_rule(spec, len(new_lines), top[0]))
                    new_lines.extend(top)
                    new_breaks.extend([[]] * ((0 if tight else 1) + len(top)))
                else:
                    bottom = self._render_box_bottom(spec.level)
                    border_trail.append(self._border_rule(spec, len(new_lines), bottom))
                    new_lines.append(bottom)
                    new_breaks.append([])
                    if not tight:
                        new_lines.append("")  # 아래 한 줄 띔 (§2.1.6(5))
                        new_breaks.append([])
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
        bo.rule_trail += border_trail   # 테두리 좌표는 이미 새 프레임 기준이라 재매핑 뒤에 붙인다

    @staticmethod
    def _border_rule(spec: "BoxBorder", line_no: int, line: str) -> RuleApplication:
        """그린 글상자 테두리 한 줄 → BBPG-1.2.5 근거(요소-로컬 좌표).

        tag에 위치(위/아래)·위계·제목 유무를 담는다 — 점역사가 "왜 여기에 상자를 쳤고
        왜 이 단계 캡을 썼는지"를 판단하는 데 필요한 정보이자, 원장 C-01a/C-01b 자문 항목이다.
        """
        kind = "box_top" if spec.kind == "top" else "box_bottom"
        titled = "·제목있음" if (spec.kind == "top" and spec.title) else ""
        return make_rule(
            _RULE_BOX_BORDER, line_no=line_no, col_start=0, col_end=len(line),
            tag=f"{kind}·{spec.level}단계{titled}",
        )

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

    def _indent_lines(
        self, bo: BrailleOutput, etype: str, hlevel: int,
        lines: Optional[list[str]] = None,
    ) -> tuple[list[str], list[int]]:
        """이 요소의 논리 줄 + 줄별 들여쓰기 칸 수. 통 문자열·조판이 함께 쓴다.

        `_format_element`의 들여쓰기 판정과 **같은 순서**로 돈다(글머리 정정 → 첫 줄
        들여쓰기 → 항목 줄 재배분 → 테두리 예외 → line_indents). 조판 쪽은 32칸으로 접은
        뒤에 들여쓰기를 붙이므로 코드를 합치지 못했다 — 한쪽만 고치면 화면과 다운로드가
        갈라진다. 회귀 `test_flat_string.py::test_flat_indent_matches_layout`이 둘을 묶는다.

        1단계 제목은 들여쓰기가 아니라 가운데 정렬(BBPG 2장2절1)이라 pad를 좌우 여백으로
        계산한다 — 32칸을 넘으면 정렬하지 않는다(`_center`와 같은 판정).
        """
        draft = lines is not None             # 초안은 본문 줄을 건드리지 않는다
        if not draft and etype in ("list_item", "text"):
            self._apply_bullet_marker(bo)     # 멱등 — layout이 다시 불러도 안전하다
        is_heading = hlevel >= 1
        first_indent = self._first_indent(bo, etype, is_heading, hlevel)
        if not draft:
            self._mark_item_lines(bo, etype, first_indent)
        lines = list(lines if draft else bo.braille_lines)
        # 32칸 테두리 줄은 들이면 폭을 넘어 깨진다. 그렇다고 요소 전체의 들여쓰기를 버리면
        # 글상자 안 문단이 0칸에서 시작해 gold와 어긋난다(원장 C-01b) — 첫 들여쓰기를
        # **테두리 안 첫 줄**로 옮긴다.
        first_at = next((i for i, ln in enumerate(lines)
                         if ln.strip() and not _is_border_line(ln)), -1)
        if is_heading and hlevel == 1:
            lines = [ln.strip() for ln in lines]
            return lines, [max(0, (_COLS - _cell_count(ln)) // 2) if _cell_count(ln) < _COLS
                           else 0 for ln in lines]
        # 줄별 들여쓰기(규정 골격 — 만화 5칸 장면·시각자료 제목 5칸)는 **줄 수가 맞을 때만**
        # 쓴다. 초안도 마찬가지다 — `bo.line_indents`는 **선택 초안**의 줄 수에 맞춰져 있어
        # (`image_braille._match_indents`) 선택 초안에서는 맞고 나머지에서는 안 맞아 걸러진다.
        # ⚠ 초안이라고 무조건 건너뛰면 선택 초안만 들여쓰기가 빠져 proto 불변식
        #   `contents == drafts[selected_idx].contents`가 깨진다(실측 5건).
        per_line = (bo.line_indents
                    if bo.line_indents is not None and len(bo.line_indents) == len(lines)
                    else None)
        if per_line is not None:
            return lines, list(per_line)
        # 표는 들여쓰기를 줄 문자열에 이미 박아 낸다(§3.1.1(1)②) — 여기서 또 넣으면 두 번 들어간다.
        return lines, [first_indent if i == first_at else 0 for i in range(len(lines))]

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
        """본문 요소와 페이지행 요소(page_number) 분리.

        페이지행은 슬롯이 셋뿐이다 — 원본 페이지 번호(좌)·꼬리말(가운데)·점자 페이지
        번호(우) (BBPG 1장2절1). 즉 page_number 타입에서 **한 요소만** 페이지행에 쓰이는데,
        종전에는 타입이 같다는 이유로 나머지 요소까지 전부 이 통에 담겨 **본문에도
        페이지행에도 찍히지 않고 사라졌다.**

        실측(2026-07-21 dev+val 1,131p): 페이지행 타입이 2개 이상인 페이지가
        val 495/951·dev 97/180. 버려진 요소 val 517·dev 98 중 정답 도서에 실재하는 것이
        val 340·dev 68이다. 이 타입이 러닝헤더라는 보장이 없다 — 실제 인쇄 러닝풋은
        pipeline._is_running_foot가 이미 위에서 걸러 내고, 여기까지 오는 것은
        **강 도입부 본문**인 경우가 많다(세계사 p054: header_footer 10개가 강 번호·강
        제목·대단원·핵심 주제 목록이고, 정답 도서는 이를 ⠔⠔ 접두 목록으로 본문에 싣는다).

        그래서 페이지행에는 타입별 첫 비어있지 않은 요소만 남기고 나머지는 본문으로
        되돌린다. 되돌린 요소는 _format_element를 타므로 32칸 조판도 정상 적용된다.

        ★ 2026-07-26(r21): header_footer를 이 통에서 아예 뺐다 — 위 실측의 귀결이다.
        여기 오는 header_footer가 러닝풋이 아니라면 **첫 요소도 러닝풋이 아니다.**
        그런데 종전 코드는 첫 요소만 꼬리말 슬롯(폭 22~24칸)에 밀어 넣어 잘라 찍었고,
        잘린 나머지는 인쇄물 어디에도 남지 않았다(자기정합 B 실측, 기준선 ce31896:
        header_footer가 dev 88.7%(133/150)·val 91.3%(702/769)로 텍스트계에서 가장 낮고
        — page_number dev 98.4%·val 99.5%가 그 다음 — 미인쇄 84건이 이 슬롯에서 잘린
        요소다. 그중 gold에 그대로 있는 것만 val 8건이며, 이 개편 뒤 B는 dev·val 모두
        100.0%, 'A통과인데 인쇄 안 됨'은 val 8건→1건이 된다). 정답 도서의 꼬리말은
        도서 제목이고 ('수특 …' 접두 꼬리말 1,762줄 — 분자는 독립 재현됨. 분모는
        페이지행 검출 정의에 따라 1,771~1,832로 갈려 비율은 96~99%로 적는다) 우리
        header_footer 고유 문자열(러닝풋·보일러플레이트 제외 512종, 원시 584종) 중
        정답 꼬리말과 일치하는 건 **0종**이라, 이 슬롯에 header_footer를 밀어 넣어
        얻을 것이 없다. ← 판정을 떠받치는 건 '일치 0종'이고 위 분모·종수는 규모 감각용이다.

        실물 확인(2026-07-26): 세계사 원본 p054는 이 요소가 6장 전 페이지행에
        '⠕⠂⠘⠷⠐ ⠟⠊⠥⠐ ⠊⠿⠉⠢ ⠣⠠⠕⠣ ⠠⠝'으로 잘려 반복 인쇄됐고 본문엔 없었다. 지금은
        본문 첫 줄에 '⠕⠂⠘⠷⠐ ⠟⠊⠥⠐ ⠊⠿⠉⠢ ⠣⠠⠕⠣ ⠠⠝⠈⠌⠺ ⠨⠾⠈⠗'로 온전히 실리며,
        정답 도서도 같은 내용을 본문 첫 줄에 싣는다(gold 0행).
        """
        body, page_line = [], []
        taken: set[str] = set()
        for bo in braille_outputs:
            etype = meta.get(bo.element_id, _DEFAULT_META)[0]
            if (etype in _PAGE_LINE_TYPES and etype not in taken
                    and any(ln.strip() for ln in bo.braille_lines)):
                taken.add(etype)
                page_line.append(bo)
            else:
                body.append(bo)
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

    def _c6_clip_page_line_items(
        self, page_line_items: list[BrailleOutput], meta: dict
    ) -> None:
        """페이지행 요소(원본 페이지 번호)의 점자 줄을 32칸으로 절단(in-place). C6.

        (2026-07-26 r21로 header_footer가 페이지행 통에서 빠져 _format_element 32칸 조판을
        정상적으로 타게 됐다 — 아래 실측의 43줄은 그 경로로 해소된다. page_number 7줄은
        여전히 이 절단이 유일한 방어라 그대로 둔다.)

        **C6 근본 원인**: 페이지행 요소는 _partition에서 본문과 갈라져 나가
        _format_element(=_wrap_line 32칸 조판)를 **타지 않는 유일한 경로**다. 조립되는
        페이지행 자체는 _compose_page_line이 절단해 32칸을 지켰지만, 요소의 braille_lines는
        점역 원문 길이 그대로 braille_text_list(=FE가 편집하는 화면)에 실려 나갔다.
        전수 실측(dev+val 1,131p): 32칸 초과 50줄(header_footer 43·page_number 7),
        최장 165칸. 본문 타입(text·list_item)은 0줄 — 일반 조판은 정상이었다.

        **왜 줄바꿈이 아니라 절단인가(BBPG 1장3절4)**: "제목이 길어 전체를 꼬리말로 적을 수
        없는 경우에는 핵심 단어를 선택하여 꼬리말이 들어갈 수 있는 칸수만큼만 적는다.
        다만, 분명한 핵심어 선택이 어려운 경우에는 앞에서부터 내용의 일부를 적어 준다."
        핵심어 자동 선택은 근거 없는 추측이 되므로 규정이 명시한 폴백(앞에서부터)을 쓴다.
        정답 도서 실측도 32칸 상한을 뒷받침한다 — gold 51,581줄 중 초과 0줄(33칸으로
        세어지던 451줄은 전부 줄머리 \\x0c 페이지 구분자이고 점자 셀이 아니다).

        **왜 페이지행 슬롯폭이 아니라 32칸인가**: 슬롯폭(꼬리말이 실제로 차지하는 칸,
        보통 22~24)으로 자르는 판본을 먼저 만들어 전수 측정했더니, 원본 페이지 번호 요소가
        OCR 오분류로 길어진 페이지에서 꼬리말 슬롯이 0이 되어 요소 9건(val 7·dev 2)이
        통째로 소멸했다(dev 텍스트 축 69.6→69.5). 32칸(=점자 페이지 폭)은 C6를 똑같이
        해소하면서 요소를 소멸시키지 않는다. 인쇄면에 실제로 나가는 더 좁은 절단은
        _compose_page_line이 이미 규정대로 하고 있으므로 이중으로 걸 필요가 없다.

        절단 폭 32 ≥ _compose_page_line의 슬롯폭이고 접두 절단이라 **조립되는 페이지행은
        불변**이다 — 이 수정은 braille_text_list만 바꾸고 BRF는 바이트 동일하다
        (전수 대조 1,131p 전부 일치 확인).
        """
        def clip(lines: list[str]) -> list[str]:
            # 32칸 안에 드는 줄은 손대지 않는다(들여쓰기·빈 줄 보존).
            return [ln.strip()[:_COLS] if _cell_count(ln.strip()) > _COLS else ln
                    for ln in lines]

        for bo in page_line_items:
            if meta.get(bo.element_id, _DEFAULT_META)[0] not in _PAGE_LINE_TYPES:
                continue
            bo.braille_lines = clip(bo.braille_lines)
            for d in bo.drafts:                     # 현재 페이지행 요소엔 초안이 없으나 방어
                d.braille_lines = clip(d.braille_lines)

    def _footer_text(self, body: list[BrailleOutput], meta: dict) -> str:
        """페이지행 꼬리말(가운데) — **해당 페이지의 1·2단계 제목** (점자 도서 제작 지침
        제1장 3.꼬리말 3)).

        규정 원문(제1장 3-3)): "본문의 꼬리말은 해당 페이지의 1, 2단계 제목이나 번호 체계
        표기를 기본으로 하되 도서의 전체 구성과 분량을 고려하여 ... 구분 기준을 변경할 수
        있다." 즉 **기본값이 페이지 제목**이고, 도서별로 바꿀 수 있다.

        정답 도서(EBS 수능특강 6종)는 그 '변경'을 행사한 판본이다 — 실측(2026-07-26,
        dev+val): 가운데 슬롯이 '수특 <도서명> <권번호>' 형태인 것이 **1,762줄**(분자는
        독립 재현됨), 빈 것 56줄. 분모(페이지행 총수)는 검출 정의에 따라 1,771~1,832라
        비율은 96~99%다 — 정의를 고정하지 않은 채 비율만 인용하지 말 것. 권번호는 인쇄 쪽번호를 따라 단조 증가해
        (언어: p009→1 · p046→2 · p085→3 · p122→4 · p156→5 · p195→6 · p234→7 · p270→8)
        **점자책을 몇 권으로 나누느냐는 제작 결정**이다. 도서명도 러닝헤드·러닝풋이 실제로
        추출된 면(_is_running_foot 기준 511/1,131 = 45.2%)에서만 읽히고 나머지 면은
        인쇄돼 있지도 않다(입력 PDF 1,131개의 메타 title은 전량 빈 문자열). 즉 정답 도서의
        꼬리말은 한 장짜리 입력에서 재현할 수 없다 — 재현하려면 BE/점역사가 책 단위로
        주는 값이 필요하다. (재현 스크립트: temp/r25_gold_footer.py · temp/r29_verify_claims.py)

        그래서 우리가 실제로 가진 정보로 지침의 **기본값**을 지킨다: 그 페이지의 1단계
        제목(없으면 2단계)의 첫 줄. 길면 _compose_page_line이 슬롯 폭만큼 앞에서부터
        자르는데, 이는 지침 3-4)의 폴백("분명한 핵심어 선택이 어려운 경우에는 앞에서부터
        내용의 일부를 적어 준다")과 같다.

        ⚠ 오늘 이 규칙은 **잠들어 있다**. 현 경계 파일(현주 핸드오프)은 heading_level을
        주지 않는다 — dev+val 요소 28,425개 전수가 heading_level=None이고 type='title'은
        0건이다. 그래서 코퍼스 전 페이지에서 꼬리말은 공란이고(전 출력 페이지행 4,900줄
        중 가운데 슬롯이 채워진 줄 0), '지침형'과 '공란 유지'는 오늘 출력이 동일하다.
        상류가 제목 단계를 싣기 시작하면 별도 배선 없이 켜진다.
        (재현: temp/r29_census.py · temp/r29_pageline_census.py)

        ⛔⛔ **켜기 전에 읽을 것 — 켜는 순간 꼬리말이 두 겹으로 찍힌다.** (2026-08-22 plan)
        조판은 **BE·FE 소관으로 이관됐다**(`braille-assist` 모듈, 대표 2026-08-16 구두 확정).
        페이지행과 꼬리말을 BE가 조립하고, 도서명·권번호는 `TranslateText`의 `footerText`로
        들어오며 시작 점자쪽은 `braille-assist` 인자다(계약: `SPEC-INTERFACE.md` §1-2-1).
        즉 **AI가 여기서 꼬리말을 또 넣으면 BE 것과 겹친다.** 지금은 `heading_level`이
        전량 None이라 잠들어 있어 사고가 안 났을 뿐이다.
        → 상류가 제목 단계를 싣기 시작하면 **이 함수를 켜지 말고 빈 문자열로 두는 쪽**이
          계약과 맞다. D-11(페이지행) 재측정 때 그 판단을 같이 내린다.

        ★ 대안 '첫 header_footer 요소를 꼬리말로 복사'는 기각했다. 그 판본이 채웠을
        페이지행을 현 응답으로 재현하면 2,155/4,900줄 = 44.0%인데, 채워질 내용이 제목이
        아니다 — 상위가 '02'(123줄)·'01'(108줄) 같은 번호 조각, 'Exercises'(81줄)·
        'Level 2 기본연습'(45줄) 같은 하위 배너, 그리고 OCR 잡음이며 그중 32줄은
        '[처리 불가: 점역 불가 문자 匙]'이 전 페이지 가구로 찍힌다. 우리 header_footer
        고유 문자열(512종, 원시 584종) 중 정답 도서 꼬리말과 일치하는 것은 **0종**이다.
        (재현: temp/r29_hf_footer_variant.py · temp/r29_verify_claims.py)
        """
        best: tuple[int, int, str] | None = None
        for bo in body:
            _etype, order, hlevel = meta.get(bo.element_id, _DEFAULT_META)
            if hlevel not in _FOOTER_HEADING_LEVELS:
                continue
            line = next((ln.strip() for ln in bo.braille_lines if ln.strip()), "")
            if not line:
                continue
            key = (hlevel, order, line)
            if best is None or key[:2] < best[:2]:
                best = key
        return best[2] if best else ""

    def _orig_page_text(self, page_line_items: list[BrailleOutput], meta: dict) -> str:
        """페이지행 원본 페이지 번호(좌측). page_number 요소의 첫 줄."""
        return self._first_nonempty(page_line_items, meta, "page_number")

    def _compose_page_line(self, footer: str, orig_page: str, page_no: int) -> str:
        """페이지행: 원본 페이지번호(좌) · 꼬리말(가운데) · 점자 페이지번호(우) (BBPG 1장2절2)."""
        pn = _page_number_braille(page_no)
        # ★ 점자 빈칸으로 채운다(2026-08-28). 종전엔 ASCII 공백(U+0020)이었다 —
        #   이 줄만 점자 파일에 ASCII 가 섞여, 셀을 세는 소비자(BE·FE·점자 프린터)가
        #   다르게 읽고 앞 빈칸 통계도 어긋났다(생명과학 한 권 실측: ASCII 29칸 26줄·28칸 4줄).
        #   나머지 조판은 전부 `_PAD`(U+2800)를 쓴다. 여기만 예외였다.
        cells = [_PAD] * _COLS
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
            # ★ 면 첫 줄의 빈 줄은 **버리지 않는다** — 「점자 도서 제작 지침」 2장2절2 2)(3)
            #   "면의 첫 줄에 오는 빈 줄은 삭제하지 않는다". 정답 도서도 면 첫 줄이 빈 줄인
            #   경우가 3.2%다(2026-08-08 대표 결정으로 규정대로 살린다).
            #   남은 것이 전부 빈 줄이면 거기서 끝낸다 — 빈 면을 만들지 않기 위해서다.
            if pages and all(x == "" for x in lines[i:]):
                break
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


# ── 통 문자열 직렬화 (2026-08-05, 조판 가이드 §3) ────────────────────────────
# AI finalize 폐기에 따라 ProcessPage 응답의 contents는 **조판하지 않은 통 문자열**이다.
# 32칸 자름·면 나눔·페이지행·페이지 변경선만 FE(화면)·BE(다운로드, braille-assist)가 한다.
# **조판 규칙(구조적 빈 줄·들여쓰기·가운데 정렬)은 전부 우리 몫이다** — 제목 앞뒤 빈 줄과
# 3/5/7칸 들여쓰기, 1단계 제목 가운데 정렬은 지침(BBPG 2장2절1·2절2·3절5) 규칙이지 화면
# 사정이 아니다. FE·BE가 type·heading_level을 보고 재현하려면 규정을 다시 구현해야 하고,
# 그러면 규칙이 세 벌로 갈라진다. 여기서 점자 공백 셀로 문자열에 직접 박아 내보낸다.

class FlatElement(NamedTuple):
    """요소 하나의 통 문자열 + 그 좌표계로 옮긴 rule_trail.

    text — `"\\n" * before + 본문 + "\\n" * (after + 1)`.
      뒤의 +1은 본문 마지막 줄을 끝내는 개행이다. 그래서 요소들을 **그냥 이어 붙이면**
      각자 자기 줄에서 시작하고, 빈 줄 수가 지침대로 나온다.
    prefix/suffix — 초안(drafts)도 같은 구조적 빈 줄을 달아야 해서 따로 들고 있는다.
    draft_texts — 초안별 통 문자열. 들여쓰기·가운데 정렬까지 본문과 같은 규칙으로 넣는다
      (proto 불변식 `contents == drafts[selected_idx].contents`).
    """

    text: str
    trail: list[RuleApplication]
    prefix: str
    suffix: str
    draft_texts: tuple[str, ...] = ()


# 통 문자열에서 접을 줄의 폭 임계. 이만큼 찬 줄 뒤 개행은 **칸수에 밀린 것**이라
# 내용이 아니다(2026-08-16 대표 기준: "칸수 초과 때문이면 한 줄로, 의도된 것이면 살린다").
# 32칸에서 4칸 여유를 둔 것은 어절 하나가 못 들어가 접힌 자리까지 잡기 위해서다.
_FULL_LINE_MIN = _COLS - 4


# 접기를 적용할 요소 유형. 표·시각자료·글상자는 32칸 줄이 **조판 결과가 아니라 구조**다
# (테두리 ⠿⠛…⠿가 정확히 32칸이라 접기 조건에 걸린다 — 한 번 밟았다).
_FOLDABLE_TYPES = {"text", "list_item", "caption", "footnote", "sidebar", "title"}


def _fold_full_lines(lines: list[str], pads: list[int],
                     etype: str = "text") -> tuple[list[int], list[str]]:
    """꽉 찬 줄 뒤 개행을 점자 공백으로 바꾼다 — 줄은 그대로 두고 **구분자만** 고른다.

    `contents`는 조판하지 않은 통 문자열이 계약인데(proto §TextElement.contents) 32칸에
    밀려 끊긴 줄이 개행으로 남아 있었다. 실측 점자 요소의 25%가 안쪽 개행을 물고 나갔고,
    그중 32%가 이 얼굴이다(eval 2026-08-17).

    ★ 개행과 점자 공백은 **둘 다 1문자**라 이 치환은 오프셋을 안 바꾼다 — `_flat_trail`이
      쓰는 `starts` 계산(`+1`)이 그대로 맞는다. 그래서 줄 문자열에는 손대지 않는다
      (표식을 줄에 붙이면 `len(ln)`이 1 늘어 오프셋이 밀린다 — 한 번 밟았다).
      이어 붙는 줄의 들여쓰기만 0으로 돌리고, 그 pads를 두 함수가 같이 쓴다.

    ⚠ 짧은 줄 뒤 개행은 안 건드린다 — 시행·대사·목록처럼 줄바꿈이 내용인 자리다.

    반환: (조정된 pads, 줄 사이 구분자 목록 — 길이 len(lines)-1)
    """
    seps = ["\n"] * max(0, len(lines) - 1)
    if len(lines) < 2 or etype not in _FOLDABLE_TYPES:
        return list(pads), seps
    out_pads = list(pads)
    for i in range(len(lines) - 1):
        width = (pads[i] if i < len(pads) else 0) + len(lines[i])
        if width >= _FULL_LINE_MIN and lines[i + 1].strip():
            seps[i] = "⠀"
            out_pads[i + 1] = 0
    return out_pads, seps


def _pad_join(lines: list[str], pads: list[int],
              seps: Optional[list[str]] = None) -> str:
    """줄별 들여쓰기를 점자 공백 셀로 박아 한 문자열로 잇는다.

    `seps`를 주면 줄 사이 구분자를 자리마다 고른다(`_fold_full_lines` 참조).
    구분자는 전부 1문자라 오프셋 계산이 그대로 맞는다.
    """
    parts = [_PAD * p + ln for ln, p in zip(lines, pads)]
    if not seps:
        return "\n".join(parts)
    out = parts[0] if parts else ""
    for i, part in enumerate(parts[1:]):
        out += (seps[i] if i < len(seps) else "\n") + part
    return out


def _flat_trail(
    trail: list[RuleApplication], lines: list[str], prefix_len: int, body_len: int,
    pads: Optional[list[int]] = None,
) -> list[RuleApplication]:
    """요소-로컬 (line_no, col) → 통 문자열 문자 오프셋. line_no는 0으로 고정한다.

    좌표계가 줄 배열에서 문자열 하나로 바뀌었으므로 `\\n`도 1문자로 센다.
    `line_no=-1`(요소 전체)은 본문 전 구간을 가리키게 옮긴다 — 빈 줄은 뺀다.
    """
    starts: list[int] = []
    acc = prefix_len
    for i, ln in enumerate(lines):
        pad = pads[i] if pads and i < len(pads) else 0
        starts.append(acc + pad)    # 들여쓴 칸 수만큼 본문 시작이 뒤로 밀린다
        acc += pad + len(ln) + 1    # +1 = 줄 끝 개행
    out: list[RuleApplication] = []
    for r in trail:
        c = r.model_copy()
        if r.line_no < 0 or r.line_no >= len(starts):
            c.line_no, c.col_start, c.col_end = 0, prefix_len, prefix_len + body_len
        else:
            base = starts[r.line_no]
            c.line_no = 0
            c.col_start = base + r.col_start
            c.col_end = base + r.col_end
        out.append(c)
    return out


def flatten_elements(
    braille_outputs: list[BrailleOutput],
    layout_result: Optional["LayoutResult"] = None,
) -> dict:
    """요소별 통 문자열을 만든다. **조판(layout) 전에** 불러야 한다.

    `layout()`이 `braille_lines`를 32칸 조판본으로 write-back하고 rule_trail도 그 프레임으로
    재매핑하기 때문이다. 통 문자열은 조판 전 논리 줄이 기준이다.

    빈 줄 계산은 `_assemble_pages`와 **같은 규칙**을 쓴다 — `_HEADING_BLANK`·
    `_BLANK_AROUND_TYPES` + 인접 블록 빈 줄 병합(`trailing`). 규칙을 두 벌로 두면
    화면(FE)과 다운로드(BE)가 갈라지므로 여기서 한 번만 정의한다.

    반환: element_id → FlatElement. 내용이 없는 요소는 담지 않는다(`_format_element`와 같은 판정).
    """
    lb = LayoutBraille()
    meta = lb._build_meta(layout_result)
    body, page_line = lb._partition(braille_outputs, meta)
    body.sort(key=lambda b: meta.get(b.element_id, _DEFAULT_META)[1])

    out: dict = {}
    # 페이지행 요소(page_number)는 본문 흐름에 안 들어간다 — 페이지행 조립은 FE·BE가
    # braille-assist `page_row`로 한다. 그래도 응답에는 실려야 하므로 구조적 빈 줄 없이 담는다.
    for bo in page_line:
        lines = list(bo.braille_lines)
        if not any(ln.strip() for ln in lines):
            continue
        text_body = "\n".join(lines)
        out[bo.element_id] = FlatElement(
            text=text_body + "\n",
            trail=_flat_trail(bo.rule_trail, lines, 0, len(text_body)),
            prefix="", suffix="\n",
        )

    trailing = 0            # 직전 요소가 남긴 빈 줄 수 — 중복 삽입 방지
    prev_key = None         # 직전 요소 키·타입 — 연속 시각 자료 판정용
    prev_type = ""
    for bo in body:
        if not any(ln.strip() for ln in bo.braille_lines):
            continue        # 빈 요소는 빈 줄도 만들지 않는다
        etype, _order, hlevel = meta.get(bo.element_id, _DEFAULT_META)
        lines, pads = lb._indent_lines(bo, etype, hlevel)
        pads, seps = _fold_full_lines(lines, pads, etype)
        before, after = _HEADING_BLANK.get(hlevel, (0, 0))
        if etype in _BLANK_AROUND_TYPES:      # 표·시각자료 위아래(BBPG 2장2절2 2)(2)④)
            before, after = max(before, 1), max(after, 1)
        if etype in _VISUAL_TYPES and prev_type in _VISUAL_TYPES:
            # BBPG 3장2절1 2) 다만 — 시각 자료가 연이어 나올 때 그 사이는 안 띈다.
            # 여기선 빈 줄이 **앞 요소의 suffix에 이미 박혀** 있으므로 그만큼 되돈다
            # (줄 배열을 들고 가는 `_assemble_pages`와 달리 되감을 lines가 없다).
            if trailing:
                pf = out[prev_key]
                out[prev_key] = pf._replace(
                    text=pf.text[:-trailing],
                    suffix=pf.suffix[:-trailing],
                    draft_texts=tuple(t[:-trailing] for t in pf.draft_texts),
                )
                trailing = 0
            before = 0
        # 요소가 이미 달고 온 앞뒤 빈 줄까지 세서 겹치지 않게 한다(`_assemble_pages`와 같은 규칙).
        before = max(0, before - trailing - _lead_blanks(lines))
        after = max(0, after - _tail_blanks(lines))
        trailing = after
        prev_key, prev_type = bo.element_id, etype

        prefix = "\n" * before
        suffix = "\n" * (after + 1)           # +1 = 본문 마지막 줄 끝내기
        text_body = _pad_join(lines, pads, seps)
        drafts = []
        for d in getattr(bo, "drafts", []) or []:
            d_lines, d_pads = lb._indent_lines(bo, etype, hlevel, list(d.braille_lines))
            drafts.append(prefix + _pad_join(d_lines, d_pads) + suffix)
        out[bo.element_id] = FlatElement(
            text=prefix + text_body + suffix,
            trail=_flat_trail(bo.rule_trail, lines, len(prefix), len(text_body), pads),
            prefix=prefix,
            suffix=suffix,
            draft_texts=tuple(drafts),
        )
    return out
