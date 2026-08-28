"""PART 6-3 — 표 점역 (render_mode 기반 조판).

표의 복수 초안(3안)은 LLM 텍스트가 아니라 **레이아웃 3종**이다
(stage4_complex.md 'T4-2 공통 규약' — 표=레이아웃 차이, 셀 값 동일):
  table_grid : ⠿ 테두리 + ⠒ 행 구분선 (격자 원형)
  transposed : 행↔열 전치 (점자 도서 제작 지침 3장1절 BBPG-3.1.2, 점역자 주 동반)
  linear     : '  키  값' 선형 풀어쓰기 (3칸 시작, 유도점·콜론 없음)
격자 구조가 아닌 비정형(narrative)·처리불가는 단일안으로 처리한다.
"""

from __future__ import annotations

import os
import re

from app.ai.braille.isolation import safe_translate
from app.ai.braille.nested_block import append_nested
from app.ai.braille.regulations import make_rule, make_rule_at
from app.ai.braille.symbol_rules import symbol_rule_spans
from app.ai.braille.text_braille import content_rules
from app.ai.braille.translator import translate_tagged_text as _translate
from app.ai.braille.translator import (
    emphasis_marker_spans,
    tn_marker_spans,
    translate_with_breaks,
)
from app.schemas.content import BrailleOutput, Draft, LLMOutput, RuleApplication


def _base_trail(
    lines: list[str], source: str = "", *, content: bool = True
) -> list[RuleApplication]:
    """점역자 주 마커(BBPG-1.2.6)·판단이 갈리는 특수기호를 점자 좌표로 emit.

    rule_trail은 **점역사가 판단해야 할 자리**만 기록한다(Step17 2026-08-08 대표 지시 —
    종전 "내용 변환만"에서 좁혔다). 수표·문장부호 같은 자명한 규정은 `content_rules`가
    더 이상 내지 않고, 기호는 `symbol_rules._DISCRETIONARY`가 거른다.
    text 경로와 같은 함수를 쓰는 것은 그대로다 — text/table 비대칭 금지(r12).

    source = 점역 전 원본 텍스트. 원본에 점역자 주 태그가 있을 때만 emit하여
    ∽·ː 등 동일 점형(⠠⠄)을 오인하지 않는다(B1 오탐 방지).
    content=False = 점역되지 않은 원문 그대로인 줄(처리 불가 플레이스홀더) —
    변환이 없으므로 내용 규정을 붙이지 않는다(환각 0).
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
    # 드러냄표 ⠠⠤…⠤⠄ (제56항) — text 경로와 동일 배선(원본 태그 gate, r12).
    trail += [
        make_rule_at("KBR-6.13.56", lines, s, e, tag=tag)
        for s, e, tag in emphasis_marker_spans(joined, source)
    ]
    if content:
        trail += content_rules(source, lines)
    return trail

from app.ai.braille.constants import COLS as _COLS  # noqa: E402 (공용 상수)
_BORDER  = "⠿"  # 표 테두리
_EMPTY_CELL = "⠿⠿"  # 빈 셀 (BBPG-3.1.2(4))
_SEP     = "⠒"  # 행·셀 구분선

# ── 표 구조 태그 (plan §3-5 확장) ─────────────────────────────────────────────
# table_opt가 stage②(점역 직전 텍스트)에 <!표>/<!행>/<!칸>으로 표 구조를 출력하고,
# 여기서 행렬로 파싱해 기존 4안 렌더러(풀어쓰기/격자/전치/선형)에 1:1 위임한다.
_TBL_OPEN, _TBL_CLOSE = "<!표>", "<!/표>"
_TBL_ROW_OPEN, _TBL_ROW_CLOSE = "<!행>", "<!/행>"
_TBL_CELL = "<!칸>"
# build_table_tags는 여는 `<!칸>`만 찍지만(구분자 하나면 족하다), 손으로 쓴 입력과
# BE가 보내는 txt는 다른 태그처럼 **쌍으로** 적는다. 닫는 쪽을 먼저 지우고 여는 쪽으로
# 가른다 — 여닫이를 한꺼번에 구분자로 쓰면 빈 조각이 생겨 빈 셀과 구분되지 않는다.
_TBL_CELL_CLOSE = "<!/칸>"
_TBL_ROW_RE = re.compile(r"<!행>(.*?)<!/행>", re.DOTALL)


def build_table_tags(rows: list[list[str]]) -> str:
    """행렬 → <!표><!행><!칸>… 태그 문자열(stage② 표시·table_braille 입력)."""
    out = [_TBL_OPEN]
    for r in rows:
        out.append(_TBL_ROW_OPEN + "".join(_TBL_CELL + str(c) for c in r) + _TBL_ROW_CLOSE)
    out.append(_TBL_CLOSE)
    return "\n".join(out)


def parse_table_tags(text: str):
    """<!표> 태그 → 행렬(list[list[str]]). 태그 없으면 None(파이프 폴백)."""
    if _TBL_OPEN not in text:
        return None
    rows: list[list[str]] = []
    for m in _TBL_ROW_RE.finditer(text):
        cells = m.group(1).replace(_TBL_CELL_CLOSE, "").split(_TBL_CELL)
        if cells and cells[0] == "":
            cells = cells[1:]   # 첫 <!칸> 앞 빈 셀 제거
        rows.append([c.strip() for c in cells])
    return rows or None
# 유도점: 지침 §(5)는 열 항목 간격이 5칸 이상일 때 열 **사이**에 `"`를 연속으로 적으라 한다
# (열 제목 사이는 제외). 줄머리에 무조건 붙이던 옛 구현을 제거 — 진짜 규정 유도점은 미구현.

# ── 도서 관행 / 규정 스위치 (BRAILLE_STYLE) ───────────────────────────────────
# 수식 축(kor_math_rules)·텍스트 축(translator)과 같은 형태의 게이팅을 표 축에도 둔다
# (2026-07-21). 그전까지 표는 스위치가 없어 **규정 모드를 아예 제공하지 못했다**.
# 기본값은 book — 우리 KPI 정답이 도서(수능특강 점역본)이고 점역사도 그 표기로 검수한다.
#
# 무엇이 관행이고 무엇이 규정인지 (자료지침 =「2025년도 개정 …점자교과서 및 교수학습
# 자료 제작 지침」 3장, 도서지침 =「점자 도서 제작 지침」 3장):
#
#   규정 근거가 있어 **게이팅하지 않는** 것
#     · 표 제목 5칸                자료지침 §3.1.3(1) "위 테두리 이전 줄 5칸에 적는다"
#     · 빈 셀 ⠿⠿                  자료지침 §3.1.3(9) "내용이 없는 빈칸은 =="
#     · 위/아래 테두리 ⠿⠛…⠿·⠿⠶…⠿  자료지침 §3.1.3(2) =GGG…= / =777…=
#     · 행 제목 3칸에서 시작        자료지침 §3.3.1(3) "행 제목은 3칸에 적고"
#     · 열 항목 두 칸 구분          자료지침 §3.1.1(1)②·§3.3.1(3) "두 칸씩 띄어"
#     · 전치 시 점역자 주           자료지침 §3.1.1(2) "변경한 내용은 점역자 주로 알린다"
#                                  (예 3-2 실물과 셀 단위 일치 — 아래 _TN_TRANSPOSE)
#
#   규정 근거 없이 gold 실측으로 정한 것 = **관행, book 모드 한정**
#     · _ROWWISE_MAX_WIDTH 40      규정 ①은 32칸. 40은 "32 + 한 번 접힘" 실측
#     · 문장 수준 구분자 쌍점        규정에 없음(§3.3.3은 번호 체계, §3.3.1(5)는 세로선)
#     · 전치 발동 조건 "열 수 > 행 수"  규정 (2)의 조건은 "원본 형태대로 점역할 수 없다면"
#     · 32칸 초과 시 행 머리 단독 줄  규정은 §3.3.1(4)+도서지침 §3 6)(3) 첫 칸 이어적기
#
#   조판 선택이 아니라 **입력 한계 보완**이라 게이팅 대상이 아닌 것
#     · _header_extent 숫자 휴리스틱 — 규정은 원본의 열/행 제목을 그대로 쓰지만 우리
#       입력(<!표> 태그)에는 머리 메타가 없어 추론한다. 모드와 무관한 구조 추론이다.
#     · _render_grid / _render_linear — option 2·4 초안. 점역사가 손으로 고르는 대안이라
#       자동 경로의 규정 준수와 층이 다르다(_render_linear 독스트링 참조).
_BOOK_STYLE = os.environ.get("BRAILLE_STYLE", "book") != "regulation"

# 전치 점역자 주 — 자료지침 §3.1.1(2) "이때 변경한 내용은 점역자 주로 알린다".
# 문구는 같은 지침 예 3-2 '행과 열을 변경한 표'가 실제로 실은 것을 그대로 쓴다:
#   원문 BRF  ,'jr7@v`\!`^,@ms`d+@oj5,'  (지침 문서는 backtick=빈칸)
#   →         ⠠⠄⠚⠗⠶⠈⠧⠀⠳⠮⠀⠘⠠⠈⠍⠎⠀⠙⠬⠈⠕⠚⠢⠠⠄
# 우리 translator가 내는 점자와 셀 단위로 일치함을 확인했다(25셀).
# 옛 문구 "표의 가로와 세로를 바꾸어 점역함."은 지침에 없는 자작 표현이고 8셀 더 길었다.
# ⚠ 이 문구는 **자료지침 예3-2 실물과 셀 단위로 일치**한다(회귀 테스트가 그걸 지킨다).
#   2026-08-12에 도서지침 예3-13("가독성을 위해 열과 행을 바꾸어 점역하고…")을 보고
#   "이유가 빠졌다"며 고쳤다가 예3-2 대조가 깨져 되돌렸다. **지침 두 권이 서로 다른
#   문구를 쓴다** — 자료지침은 짧게, 도서지침은 이유를 앞에 둔다. 둘 다 정본이므로
#   여기서는 셀 대조가 걸려 있는 자료지침 쪽을 정본으로 삼는다(`tn_notices` 참조).
_TN_TRANSPOSE = "행과 열을 바꾸어 표기함"
_TN_SRC = f"<!주>{_TN_TRANSPOSE}<!/주>"   # 태그 형식(§3-5) — rule_trail emit용
_TN_SRC_MARK = "⠠⠄"                                  # 점역자 주 마커(양끝) — 출력 검출용
# 표 제목 "5칸에서 시작" = 앞 빈칸 **4**(도서지침 §3 5)(1)·자료지침 §3.1.3(1)).
# 5로 적어 한 칸 밀려 있었다(2026-08-10 정정, 원장 C-21). 근거 3단이 모두 4다:
#   규정 실물 5건 — 도서지침 예3-1·3-5·3-9·3-2, 자료지침 예3-4 모두 앞 빈칸 4
#   코퍼스 관행   — dev+val 2027의 `〈표 N〉` 제목 줄 6/6이 앞 빈칸 4
#   같은 오해가 오늘 도표 축(diagram_opt._TITLE_INDENT)에서도 4로 고쳐졌다
_TITLE_INDENT = 4

# ★ 점자 지면의 빈칸은 전부 U+2800 이다(대표 지적 R1, 2026-08-24). 표 경로는 그때 빠졌다 —
#   줄머리를 ASCII 공백 `"  "`로 적고 있었고 **눈으로는 `"⠀⠀"`와 구별이 안 돼** 넉 달을 살아남았다.
#   그래서 리터럴을 쓰지 않고 반드시 이 이름으로 적는다. 2026-08-28 실측(생명과학 body p0004
#   한 쪽): 우리 출력에 ASCII 공백 35자 · 점자 빈칸 544자. 표 줄이 전부 ASCII 쪽이었다.
#   폭 계산은 안 바뀐다 — `layout_braille._cell_count`가 `len()`이라 둘 다 1셀로 센다.
_PAD = "⠀"          # 점자 빈칸(U+2800)
_ROW_INDENT = 2     # 표 본문 "3칸에서 시작" = 앞 빈칸 2 (자료지침 §3.1.1(1)②)

# 표 위/아래 테두리 (자료지침 §3.1.3(2) `=GGG…=` / `=777…=`). 격자·선형이 같이 쓴다.
_TBL_TOP = "⠿" + "⠛" * (_COLS - 2) + "⠿"
_TBL_BOT = "⠿" + "⠶" * (_COLS - 2) + "⠿"


def _tn_transpose_line() -> str:
    """전치 점역자 주 한 줄. 지침 예 3-2는 3칸(빈칸 2)에서 적고 표 본문 위에 둔다."""
    return _PAD * _ROW_INDENT + _translate(_TN_SRC)


def _title_line(title: str) -> str:
    """표 제목(전사) → 5칸에서 시작(앞 빈칸 4)하는 점자 줄 (§3 5)(1)).

    layout이 폭을 건드리지 않도록 공백을 직접 적는다.
    """
    return _PAD * _TITLE_INDENT + _translate(title)


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


# ── 칸이 길면 한 줄에 칸 하나 (지침 §3.1.1(1)③ · 원장 C-30b) ────────────────
# §3.1.1(1): ②가로로 풀어 적었을 때 쉽게 이해할 수 있다면 열 항목을 두 칸씩 띄어 풀어 적는다.
#            ③**열 항목이 여러 단어와 문장으로 되어 있어** 가로로 풀어 적을 경우 표를
#              이해하기 어렵다면 번호 체계를 활용하여 풀어 적는다.
# 즉 규정은 ②와 ③을 **칸 내용 길이**로 가른다. 우리는 열 수만 봤다.
#
# gold 실측(dev-2027 900쪽, 표 186개):
#   행우선 127개 · 칸당 글자 중앙 25 (p75 36)
#   열우선  59개 · 칸당 글자 중앙 82 (p25 48)
# 사분위가 거의 안 겹친다 → 임계 40~45자. 기본 42.
#
# ★ **축은 바꾸지 않는다.** gold 가 어느 축을 레코드로 삼는지는 실측으로 안 갈렸다
#   (글자 대조 머리행 11 : 첫열 13). 축을 잘못 바꾸면 지금보다 나빠지므로, 축은 그대로
#   두고 **한 줄에 칸 하나만** 적는다. 대표가 지적한 증상(한 줄에 긴 칸 둘)은 이걸로 사라진다.
# ⚠ 기본은 끔. 채택은 A/B 로 판정한다(원장 C-01b·C-77 과 같이 놓고 본다).
# ⚠ CER 이 gold 배치와 어긋나 내려갈 수 있다 — 이 축은 배치라 CER 이 잘 못 잰다.
_RECORD_MIN_CELL = float(os.environ.get("TABLE_RECORD_MIN_CELL", "42"))


def record_rows_enabled() -> bool:
    """칸이 길 때 한 줄에 칸 하나로 적는 스위치(기본 끔). 원장 C-30b."""
    return os.environ.get("TABLE_RECORD_ROWS", "0") == "1"


def _mean_cell_len(rows: list[list[str]]) -> float:
    """머리행·행머리를 뺀 **값 칸**의 평균 글자수."""
    vals = [c.strip() for r in rows[1:] for c in r[1:] if c.strip()]
    return sum(len(c) for c in vals) / len(vals) if vals else 0.0


def _use_record_rows(rows: list[list[str]]) -> bool:
    return (record_rows_enabled() and len(rows) > 1 and len(rows[0]) > 2
            and _mean_cell_len(rows) >= _RECORD_MIN_CELL)


def _render_grid(corrected_text: str) -> list[str]:
    """지침 §3.1 표 표기(행 단위 전개, 예3-4·3-6 실측 형식, 2026-07-19 정정).

    위 테두리 ⠿⠛…⠿ · 아래 테두리 ⠿⠶…⠿ 안에, 각 행을 3칸(앞 빈칸 2)에서
    '행제목: 값  값'(쌍점 ⠐⠂ + 한 칸, 값 사이 두 칸)으로 적는다. 빈 셀 = ⠿⠿(§3.1.2(4)).
    (구 격자형 — 전체 ⠿ 채움 테두리·세로 ⠿ 벽·행 구분선 — 은 지침 예시와 달랐다.
     layout._is_border_line이 이 테두리 형을 정식 인정해 들여쓰기 미적용도 유지된다.)
    """
    rows = [ln for ln in corrected_text.splitlines() if ln.strip()]
    top, bot = _TBL_TOP, _TBL_BOT
    # ★ 테두리를 낸다 (2026-08-06 판정 번복 — 원장 C-01a).
    #   2026-07-29에는 "코퍼스 정답 14,382줄에 테두리형 줄 0개"를 근거로 뺐다. 그 표본이
    #   **구판 수능특강 한 종류**였던 게 문제다. 82권으로 다시 재니 정반대다:
    #     구 gold(수능특강) 0.00% / 신 gold(2027 EBS) 2.62% / 초등참고서 4.78% /
    #     중등교과서 3.37% / 고등교과서 2.97%  — 일반도서만 0%(표가 거의 없다)
    #   dev-2027 완결 테두리 블록 실측: 위 ⠿⠛…⠿ 1,096줄 · 아래 ⠿⠶…⠿ 1,783줄.
    #   메모리 [[gold-brl-fullcell-is-ong]]("정답의 ⠿는 약자 '옹'")은 **낱개 ⠿** 얘기지
    #   32칸 채움 줄 얘기가 아니다 — 그 둘을 같이 본 것이 오판의 원인이었다.
    #   BRAILLE_STYLE 게이팅을 걸지 않는다. 규정(지침 §3.1.3(2))과 관행이 이제 같다.
    #
    # ★ 행 구분선 ⠐⠐…⠐ (2026-08-06 신설).
    #   gold 표 445개 중 287개(64%)가 행 사이에 32칸 ⠐ 줄을 넣는다(EBS-E26-013 p8 실물).
    #   마지막 행 뒤에는 넣지 않는다 — 아래 테두리가 그 자리를 맡는다.
    rowsep = "⠐" * _COLS
    if not rows:
        return [top, bot]
    grid = [[c.strip() for c in r.split("|")] for r in rows]
    if _use_record_rows(grid):
        return [top] + _record_lines(grid) + [bot]
    lines: list[str] = [top]
    for k, row in enumerate(rows):
        cells = [c.strip() for c in row.split("|")]
        head = _translate(cells[0]) if cells[0] else "⠿⠿"
        vals = [(_translate(c) if c else "⠿⠿") for c in cells[1:]]
        body = head + ("⠐⠂⠀" + "⠀⠀".join(vals) if vals else "")
        lines.append("⠀⠀" + body)
        if k == 0 and len(rows) > 1 and len(cells) > 2:
            # ★ 2열 표에는 구분선을 넣지 않는다(2026-08-29 실측, 원장 C-30).
            #   지침은 구분선을 일관되게 **"열 제목과 열 항목 **사이**"** 로 정의한다
            #   (용어 정의 · §3.1.3(5) · §3.3.1 구분선 항). **열 제목이 없으면 구분선도 없다.**
            #   2열 표는 대개 키-값 나열이라 첫 행이 열 제목이 아니다.
            #   gold 실측: 2열 표 **339개 중 구분선이 있는 것은 40개(12%)** 뿐이다.
            #   넣지 않으면 **88.2%** 가 맞고, 지금처럼 늘 넣으면 **11.8%** 다.
            #   ⚠ 머리행이 진짜 있는 40개는 놓친다. 신호를 찾아봤으나 쓸 것이 없었다 —
            #     MinerU HTML 에 `<th>`·`<thead>` 가 577개 전부 없고, `행 수≥3 & 머리행 최대
            #     ≤12자` 조합이 F1 0.74(정확도 93.5%)로 제일 나았지만 **같은 339개에 임계
            #     둘을 맞춘 것이고 홀드아웃이 없다.** 규칙 없는 88.2% 를 택한다(과적합 금지).
            #   3열 이상은 종전대로 넣는다 — 거기는 열 제목이 실제로 있다.
            lines.append(rowsep)          # 머리행과 본문 사이(실측 위치)
    lines.append(bot)
    return lines


def _record_lines(grid: list[list[str]]) -> list[str]:
    """행마다 '행머리' 한 줄 + 칸마다 '머리행이름: 값' 한 줄 (원장 C-30b).

    축은 원본 그대로 둔다 — 머리행 이름을 이름표로 쓰므로 추측이 없다.
    """
    heads = grid[0]
    out: list[str] = []
    for row in grid[1:]:
        rh = row[0].strip()
        if rh:
            out.append("⠀⠀" + _translate(rh))
        for j, cell in enumerate(row[1:], start=1):
            name = heads[j].strip() if j < len(heads) else ""
            val = _translate(cell) if cell.strip() else "⠿⠿"
            out.append("⠀⠀⠀⠀" + ((_translate(name) + "⠐⠂⠀") if name else "") + val)
    return out


def _render_linear(corrected_text: str) -> list[str]:
    """2열 표 → 한 줄에 '키  값'. 3칸에서 시작하고 키와 값을 두 칸 띄운다.
        `  언어 문제  64.9`   (유도점·콜론 없음 — 코퍼스 확인)

    ★ 위/아래 테두리를 두른다 (2026-08-10 신설 — 원장 C-22). 종전에는 격자형만 테두리를
      냈고 선형은 맨몸으로 나갔다. 자료지침 §3.1.3(2)는 표에 테두리를 요구하고 열 수로
      예외를 두지 않으며, 도서지침 예 3-2(2열 표)가 테두리를 두른 실물을 싣는다.
      코퍼스도 같다 — 우리가 선형으로 낸 표를 gold에서 찾아 보니 **dev 69/75(92%) ·
      val 49/49(100%)가 테두리 안**이었다(temp/boxtbl/linear_probe2.py).
      머리행 구분선 ⠐×32는 넣지 **않는다**: dev gold 324 vs 우리 297로 이미 비슷하고
      val은 gold 7 vs 우리 18로 이미 넘친다 — 여기서 더 넣으면 val이 악화한다.

    ★ 이 렌더러만은 BRAILLE_STYLE을 타지 않는다(2026-07-17 판단, 2026-07-21 재확인).
      표 축 전체가 스위치를 안 탄다는 옛 주석은 이제 사실이 아니다 — 모듈 상단 _BOOK_STYLE
      게이팅 표를 볼 것. 여기가 예외인 이유는 따로다: 전에 여기 있던 '규정 모드'
      분기(`⠄키: 값`)가 실은 규정이 아니었다.
        · 지침 §(5)는 유도점을 "열 항목 **사이**, 간격이 **5칸 이상일 때만**" 넣으라 하는데
          그 분기는 **줄 맨 앞에 무조건** 붙였다. 열 제목 사이엔 아예 넣지 말라는 단서도 무시.
        · 유도점 글리프도 지침은 `"`인데 `⠄`를 썼고, 쌍점 `:`은 근거를 못 찾았다.
      즉 "기존 구현"에 규정 라벨이 붙어 있었을 뿐이라, 켜면 GriTS가 0.88→0.667로 떨어진다.
      진짜 규정 유도점(간격≥5칸일 때 열 사이 삽입)은 미구현 — 구현 후 다시 스위치에 걸 것.
    """
    result: list[str] = []
    for ln in corrected_text.splitlines():
        if "|" in ln:
            parts = [p.strip() for p in ln.split("|", 1)]
            if len(parts) > 1:
                head_br, val_br = _translate(parts[0]), _translate(parts[1])
                entry = f"{_PAD * _ROW_INDENT}{head_br}{_PAD * 2}{val_br}"
                if len(entry) > _COLS:
                    # 정답 관행(세계사 p009 실측): 키+값이 32칸을 넘치면 키를 단독 줄로
                    # 세우고 값을 다음 줄부터 — 한 줄에 이어붙이지 않는다.
                    result.append(f"{_PAD * _ROW_INDENT}{head_br}")
                    pad = _PAD * _ROW_INDENT
                    result.extend(_split_lines(f"{pad}{val_br}")
                                  if len(val_br) + _ROW_INDENT > _COLS else [f"{pad}{val_br}"])
                    continue
            else:
                entry = f"{_PAD * _ROW_INDENT}{_translate(parts[0])}"
        else:
            entry = _translate(ln)
        if len(entry) <= _COLS:
            result.append(entry)
        else:
            result.extend(_split_lines(entry))
    return [_TBL_TOP, *(result or [""]), _TBL_BOT]


_NUMERIC_CELL_RE = re.compile(r"^[\d.,()%~\-\s]+$")


def _header_extent(rows: list[list[str]]) -> tuple[int, int]:
    """(머리 행 수, 머리 열 수). 값이 숫자인지로 데이터 영역을 가른다.

    수능특강 표는 대분류/소분류 2단 머리(성별×나이수급분류 등)가 흔하다. 1단으로 가정하면
    대분류가 데이터처럼 섞여 정답과 어긋난다.

    ★ 숫자는 '데이터 영역이 여기서 시작한다'는 **양성 신호**일 뿐이다. 신호가 없다고
      해서 표 전체가 머리인 것은 아니다 — 2026-07-20 이전 구현은 숫자가 하나도 없는
      축에서 루프가 break되지 않아 h=n_rows-1 · k=n_cols-1까지 번졌고, 그 결과
      `_render_unfold`가 **마지막 행·열만 데이터로 취급**해 나머지 칸을 통째로 버렸다
      (생물 p122: 3x4 표에서 h=2·k=3 → 12칸 중 8칸 유실, 머리행·데이터행이
      '동공 B 억제'처럼 한 줄에 뒤섞임). 순수 텍스트 표는 이 코퍼스에서 흔하므로
      전체 표의 57%가 이 상태였다. 신호가 없는 축은 머리 1단으로 되돌린다.
    """
    def is_num(s: str) -> bool:
        return bool(s.strip()) and bool(_NUMERIC_CELL_RE.match(s))

    n_rows, n_cols = len(rows), len(rows[0])
    h = 0
    for r in rows:
        if any(is_num(c) for c in r[1:]):
            break
        h += 1
    else:
        h = 1          # 숫자 신호 없음 → 머리 1행(기본). 전체를 머리로 삼지 않는다.
    h = max(1, min(h, n_rows - 1))

    body = rows[h:]
    k = 0
    for j in range(n_cols):
        if any(is_num(r[j]) for r in body):
            break
        k += 1
    else:
        k = 1          # 숫자 신호 없음 → 머리 1열(기본).
    # k==0(첫 열부터 숫자)은 그대로 둔다 — 행 머리 없이 전 열을 데이터로 펴며 칸 유실이 없다.
    k = min(k, n_cols - 1)
    return h, k


# 셀이 '낱말 수준'인지 '문장 수준'인지 가르는 점자 길이 — **규정에서 유도한 값**이다.
#   자료지침 §3.1.1(1)①  한 행을 32칸 안에 배열할 수 있어야 한다      → 줄 폭 _COLS=32
#   자료지침 §3.3.1(3)    행 제목은 3칸에 적는다                      → 줄머리 빈칸 2
#   자료지침 §3.1.1(1)②·§3.3.1(3)  열 항목은 두 칸씩 띄어 적는다      → 구분자 2
# 즉 '행 제목 + 두 칸 + 열 항목' 한 쌍이 한 줄에 들어가려면
#     2(들여쓰기) + L(제목) + 2(구분자) + L(항목) ≤ 32  →  L ≤ 14
# 14 = (32 − 2 − 2) // 2 로 딱 떨어진다. 아래 식은 그 유도를 코드로 남긴 것이다.
# ⚠ 정직하게 밝혀 둔다 — 이 값은 2026-07-20 도입 당시엔 근거 없이 14로 적혀 있었고(5f7eeca),
#   유도는 2026-07-21에 사후 확인했다. 값이 바뀌지 않으므로 A/B는 불필요하다.
#   규정 모드에서는 애초에 쓰이지 않는다(_rowwise_ok·_sep_word_level 독스트링 참조).
_WORD_CELL_MAX = (_COLS - 2 - 2) // 2   # = 14

# 한 행을 통째로 한 줄에 적을 때 허용 폭.
#   규정(§3.1.1(1)①)은 32칸이다. 40은 "32 + 한 번 접힘"까지 행 단위로 적는 도서 관행으로,
#   gold 실측(폭 32–40 구간의 행 단위 채택률 58%가 최고)으로 정했다 → book 모드 한정.
_ROWWISE_MAX_WIDTH = 40 if _BOOK_STYLE else _COLS

_COLON = "⠐⠂⠀"          # 쌍점 + 한 칸 (정답 도서 실측: 사회문화 p087 '의미⠐⠂⠀하층의…')


def _word_level(rows: list[list[str]]) -> bool:
    """셀이 낱말 수준인가(↔ 여러 단어·문장).

    지침 §3.1.1(1)②는 '열 항목을 두 칸씩 띄어 풀어 적는다', ③은 '열 항목이 여러 단어와
    문장으로 되어 있어 가로로 풀어 적을 경우 표를 이해하기 어렵다면' 다른 방식으로 적으라
    한다. 즉 갈림길은 셀이 낱말 수준인가다.

    정답 도서 실측도 같다 — 낱말 수준 표(생물 p119·p122, 사회문화 p185)는 열 항목을
    **두 칸** 띄어 적고, 문장 수준 표(사회문화 p087·p174)는 **쌍점**으로 잇는다.

    ★ 이 '전 셀 ≤14' 판정은 **행 단위 전개 가능 여부**(`_rowwise_ok`) 전용이다. 구분자
      선택에는 `_sep_word_level`(중앙값)을 쓴다 — 근거는 그쪽 독스트링.
    """
    return all(len(_translate(c)) <= _WORD_CELL_MAX for r in rows for c in r if c.strip())


def _sep_word_level(rows: list[list[str]]) -> bool:
    """열 단위 전개의 구분자를 두 칸으로 할 것인가 — **중앙값** 셀로 판정한다.

    §3.1.1(1)③의 갈림길은 '열 항목이 여러 단어와 문장으로 되어 있는가', 즉 표의
    **전형적인** 셀이 어느 수준인가다. 그런데 `_word_level`은 전 셀 검사(all)라 셀 하나가
    14셀을 넘으면 표 전체가 쌍점으로 돌았다 — 긴 머리 셀 하나 때문에 나머지 수십 셀이
    전부 쌍점이 되는 병리가 실제로 있었다(사회문화 p114: 49셀 중 15셀짜리 **1개**가
    초과인데 우리는 쌍점 45개, gold는 페이지 전체에 1개. 생물 p067·p124도 같은 꼴).

    gold 실측으로 정한다 — 열 단위 표에서 셀 쌍 (a,b)가 gold에 `a+b`로 붙어 있으면 두 칸,
    `a⠐⠂b`면 쌍점으로 세어 표별 정답 구분자를 확정하고 규칙을 검정했다(판정 가능
    dev 36 · val 171요소):
        규칙                     dev 정합      val 정합
        전 셀 ≤14 (구현)         42% (15/36)   40% ( 68/171)   ← 쌍점 오판 dev 20·val 103
        초과비율 ≤0.25           61% (22/36)   61% (104/171)
        **중앙값 ≤14**           64% (23/36)   70% (120/171)   ← 채택
    현행의 오류는 한쪽으로 쏠려 있었다(gold가 두 칸인데 쌍점으로 적음 dev 20·val 103건,
    반대는 dev 1·val 0건). 중앙값은 새 상수를 들이지 않고 같은 _WORD_CELL_MAX를 쓴다.

    ★ 규정 모드에서는 항상 True — 즉 늘 두 칸이다. 쌍점은 규정 어디에도 없다. 자료지침이
      '여러 단어와 문장'인 표에 주는 답은 §3.3.3 번호 체계(미구현)와 §3.3.1(5) 세로선
      (조건부 '할 수 있다')이고, 기본형은 §3.1.1(1)②·§3.3.1(3)의 두 칸이다.
    """
    if not _BOOK_STYLE:
        return True
    lens = sorted(len(_translate(c)) for r in rows for c in r if c.strip())
    return not lens or lens[len(lens) // 2] <= _WORD_CELL_MAX


def _row_width(rows: list[list[str]]) -> int:
    """행을 통째로(두 칸 구분) 한 줄에 적었을 때의 최대 점자 폭."""
    widths = []
    for r in rows:
        cs = [_translate(c) for c in r if c.strip()]
        widths.append(sum(len(c) for c in cs) + 2 * max(0, len(cs) - 1))
    return max(widths) if widths else 0


def _rowwise_ok(rows: list[list[str]]) -> bool:
    """행 단위(가로) 전개가 가능한 표인가 — 낱말 수준 + 한 행이 좁을 것.

    §3.1.1(1)①은 '표의 한 행을 32칸 안에 배열할 수 있다면' 원본 정렬대로 적으라 한다.
    정답 도서는 조금 넘쳐 한 번 접히는 정도(생물 p122, 37칸)까지 행 단위로 적고, 크게
    넘치는 넓은 표(사회문화 p185, 8열 ~90칸)는 열 단위로 돌린다.

    ⚠ 임계 40 완화(50·60)는 gold 실측·전 코퍼스 A/B 양쪽에서 **기각**했다(2026-07-21).
      · gold 실측: 표를 행 단위로 적었는지를 '한 행의 셀 3개가 gold에 잇달아 나오는가'로
        판정(각 셀이 gold에 있는 구간만 모수에 넣는 조건부 검정, 확증 dev 40·val 195요소).
        폭 구간별 행 단위 채택률(val)은 32–40이 **58%로 최고**고 40을 넘으면 19~38%로
        떨어진다(100–150 12%, 150+ 4%). 즉 도서가 가르는 지점이 40 부근이다. 정책 정합률도
        현행이 최적(dev 78%·val 76%)이고 임계를 올리면 어느 값에서도 내려간다.
      · 전 코퍼스 A/B(재점역+채점): 편집셀 dev 57,178 → 50에서 57,212(+34) · 60에서
        57,196(+18)로 **악화**, val만 −717·−1,047. 한쪽 악화라 채택 규칙 미달.
      · 원인: ①이 (2)전치보다 먼저라 임계를 올리면 폭 40~w 표의 **전치가 사라진다**.
        생물 p119(gold 열 인접 123/123)·수학2 p016이 그렇게 깨진다.
      · '폭 245·435 표도 gold는 행 단위'라는 직전 라운드 관찰은 재현되지 않았다 — 그 표들
        (사회문화 p192·p107 등)은 `_word_level`이 False라 임계와 무관하게 열 단위로 간다.

    ★ 규정 모드는 폭 조건만 본다. §3.1.1(1)①이 거는 조건은 "한 행을 32칸 안에 배열할 수
      있는가" 하나뿐이고, 셀이 낱말 수준인지(_word_level)는 ③의 갈림길이지 ①의 조건이
      아니다. 즉 규정 모드에서 _WORD_CELL_MAX는 쓰이지 않는다.
    """
    if not _BOOK_STYLE:
        return _row_width(rows) <= _ROWWISE_MAX_WIDTH      # = 32
    return _word_level(rows) and _row_width(rows) <= _ROWWISE_MAX_WIDTH


def _render_rowwise(rows: list[list[str]], orig_len: list[int]) -> list[str]:
    """행 단위 전개 — 원본 한 행을 한 줄에, 열 항목을 두 칸씩 띄어 3칸에서 적는다.

    정답 도서 실측(생물 p122 표12):
        ⠀⠀자율 신경⠀⠀침 분비⠀⠀폐의 기관지⠀⠀동공     ← 32칸에서 layout이 접는다
        ⠀⠀A⠀⠀촉진⠀⠀수축⠀⠀축소
        ⠀⠀B⠀⠀억제⠀⠀이완⠀⠀확대
    (생물 p119도 같은 형식. 열 단위 전개와 달리 모서리·행 머리를 되풀이하지 않아
     원본 칸 수만큼만 찍힌다 — 과잉생산이 없다.)

    orig_len = 폭 맞춤(패딩) 전 각 행의 실제 칸 수. 원본에 있던 빈 칸은 ⠿⠿로 남기고
    (BBPG-3.1.2(4)), 짧은 행을 늘리려고 붙인 패딩만 버린다 — 둘을 구분하지 않으면
    진짜 빈 칸이 사라지거나 없던 ⠿⠿가 생긴다.
    """
    lines: list[str] = []
    for r, n in zip(rows, orig_len):
        cells = r[:n]
        if not any(c.strip() for c in cells):
            continue
        lines.append(_PAD * _ROW_INDENT + (_PAD * 2).join(
            _translate(c) if c.strip() else _EMPTY_CELL for c in cells))
    return lines or [""]


def _should_transpose(rows: list[list[str]], n_cols: int) -> bool:
    """§3.1.1(2) 발동 여부 — 행↔열을 바꿔 가로로 풀어 적을 표인가.

    지침: "원본 자료에서 열 항목을 세로 방향으로 읽어야 하고, 이를 원본 형태대로 점역할 수
    없다면 행과 열 제목의 배열을 바꾸어 가로 방향으로 풀어 적는다." 즉 세로로 긴 축을 행으로
    돌려 한 줄이 32칸에 들어가게 만드는 조작이다.

    조건 = **열 수 > 행 수**(넓은 표). 단 호출부가 §3.1.1①(원본 정렬 유지)을 먼저 보므로
    실효 규칙은 "원본이 행 단위로 안 들어가고 + 열 수 > 행 수"다. gold 실측으로 확정했다 —
    dev+val 표 396요소 중 방향이 확증되는 119요소(정답 도서가 표를 실었고 셀 인접이 한
    방향으로 잡히는 것)에 라벨을 붙여 후보 규칙을 검정한 결과:
        ①먼저 → C > R        정확 87.4%  (적중 24 / 오발동 5 / 미발동 10)  ← 채택
        C > R (①무시)        정확 88.2%  — 수치는 비슷하나 생물 p122를 깨서 기각
        ①먼저 → C>R and T폭<폭  정확 86.6%
        T폭 < 폭              정확 84.9%
        not _rowwise_ok and 전치 후 ok  정확 73.1%  (발동 3건뿐 — 너무 좁다)
    "전치 안 함" 고정이 71.4%이므로 +16.0p. 대표 근거는 생물 p119(3×6 → 6×3):
    gold가 열 인접쌍 123/123(100%)으로 전치본을 적었고, 원본 행 폭 52칸(>32)이 전치 후
    28칸(≤32)으로 줄어 §3.1.1(1)①을 만족한다.

    ⚠ "전치 후 행이 더 좁아질 때만"이라는 추가 가드는 검정 후 **기각**했다. 목적론적으로는
    그럴듯하지만(전치는 행을 줄 안에 넣으려고 하는 것) 실측은 반대였다 — 전 코퍼스 재점역
    A/B로 10페이지가 움직였는데, 사회문화 p100의 병리(+1372셀)를 없애는 대신 정당한 전치
    9건(사회문화 p125 -504, 생물 p006 -129, 세계사 p190 -96 … 합 -1085셀)을 막아서
    dev가 순악화(+90)했다. gold는 T폭이 원본보다 넓어도 전치하는 표가 많다.

    ★ 점역자 주는 **반드시 붙인다**(2026-07-21 복원, b04aba7의 생략을 되돌림). 직전 판단은
      "gold가 전치 46페이지에서 0회" → 관행 우선이었으나, 재감사에서 전제가 무너졌다:
      정답 도서는 전치뿐 아니라 **점역자 주 자체를 거의 안 쓴다**(마커 ⠠⠄가 전 코퍼스
      1131p 중 1p). 즉 0/46은 '전치에 주를 안 단다'는 관행의 증거가 아니라 그 출판사가
      점역자 주를 통째로 생략한다는 사실의 부분집합이다. 반면 §3.1.1(2)는 명시적으로
      요구하고 지침 예 3-2는 실물까지 싣는다. 무엇보다 이건 표기 형태 문제가 아니라
      **독자가 표의 가로세로가 바뀐 사실 자체를 모르게 되는** 정확성 문제다.
      두 모드 공통 — 규정이 요구하는 것이므로 book 모드에서도 뺀다.

    모드별 발동 조건:
      book       열 수 > 행 수 (위 실측 근거)
      regulation §3.1.1(2)의 조건 그대로 — "원본 형태대로 점역할 수 없다면"(호출부가 ①을
                 먼저 보므로 이미 참) 행과 열을 바꿔 "가로 방향으로 풀어 적는다". 전치해서
                 한 행이 32칸에 들어갈 때만 목적이 달성되므로 그것을 조건으로 쓴다.
                 (이 조건은 book 모드에선 실측으로 기각됐다 — 위 ⚠ 참조.)
    """
    if not _BOOK_STYLE:
        return _row_width([list(col) for col in zip(*rows)]) <= _COLS
    return n_cols > len(rows)


def _transpose_rows(
    rows: list[list[str]], orig_len: list[int]
) -> tuple[list[list[str]], list[int], int]:
    """행↔열 교환. 폭 맞춤(패딩)으로 채운 자리는 '실제 칸'에서 빼고 돌린다.

    패딩을 실제 칸으로 착각한 채 전치하면 없던 빈 셀 ⠿⠿가 생긴다(BBPG-3.1.2(4)는
    '내용이 없는 빈칸'에만 쓴다). 전치 후 각 행의 꼬리 패딩만 잘라낸다.
    """
    real = [[j < orig_len[i] for j in range(len(rows[i]))] for i in range(len(rows))]
    t_rows = [list(col) for col in zip(*rows)]
    t_len = []
    for col in zip(*real):
        n = len(col)
        while n > 0 and not col[n - 1]:
            n -= 1
        t_len.append(n)
    return t_rows, t_len, (len(t_rows[0]) if t_rows else 0)


def _render_unfold(corrected_text: str) -> list[str]:
    """표 → 풀어쓰기 (BBPG-3.1.2). 셀 길이에 따라 행 단위 / 열 단위로 갈린다(§3.1.1(1)).

    정답 도서(수능특강 점역본) 관찰:
        수급 분류  60—64세      ← 모서리 라벨 + 열 머리
        연금 수급자  68.3        ← 행 머리 + 값
        기초 수급자  3.2
    즉 열마다 "열 머리" 줄을 세우고 그 아래 "행 머리  값"을 한 줄씩 적는다. 32칸 안에
    한 항목이 들어가 점역사가 표를 좌우로 훑지 않아도 된다.
    (구현 전에는 격자를 그대로 폭 맞춤해 냈다 — 넓은 표가 줄바꿈으로 뭉개지고 빈 셀 ⠿⠿가
     열 어긋남과 겹쳐 정답과 크게 벌어졌다.)
    행이 1줄뿐이거나 열이 2개뿐인 표는 전개할 게 없으므로 값만 나열한다.
    """
    rows = [[c.strip() for c in ln.split("|")] for ln in corrected_text.splitlines() if ln.strip()]
    if not rows:
        return [""]
    n_cols = max(len(r) for r in rows)
    orig_len = [len(r) for r in rows]            # 패딩 전 실제 칸 수(빈 칸 ⠿⠿ 판정용)
    rows = [r + [""] * (n_cols - len(r)) for r in rows]

    if len(rows) < 2 or n_cols < 2:              # 전개할 축이 없음 → 값 나열
        return [f"{_PAD * _ROW_INDENT}{_translate('  '.join(c for c in r if c))}"
                for r in rows] or [""]

    # §3.1.1은 순서가 있는 판정이다 — ①"한 행을 32칸 안에 배열할 수 있다면 표의 정렬
    # 형태대로" 가 먼저고, (2)전치는 "원본 형태대로 점역할 수 **없다면**" 쓰는 뒷수단이다.
    # 이 순서를 뒤집어 전치를 먼저 보면 원본대로 잘 적히던 표까지 돌아간다(생물 p122 실측:
    # 3×4라 C>R이 참이지만 gold는 원본 정렬 그대로 — 행 인접 79/79).
    if _rowwise_ok(rows):                        # §3.1.1(1)① 원본 정렬 유지 → 행 단위
        return _render_rowwise(rows, orig_len)

    head: list[str] = []                         # 전치 점역자 주(§3.1.1(2))가 들어갈 자리
    if _should_transpose(rows, n_cols):          # §3.1.1(2) 넓은 표 → 행↔열 교환
        rows, orig_len, n_cols = _transpose_rows(rows, orig_len)
        head = [_tn_transpose_line()]            # "변경한 내용은 점역자 주로 알린다"
        if _rowwise_ok(rows):                    # 전치 후 한 행이 들어가면 행 단위
            return head + _render_rowwise(rows, orig_len)
    # 열 단위 전개의 구분자: 낱말 수준이면 두 칸, 문장 수준이면 쌍점(정답 도서 실측).
    sep = "⠀⠀" if _sep_word_level(rows) else _COLON

    n_head_rows, n_head_cols = _header_extent(rows)
    body = rows[n_head_rows:]
    col_names = rows[n_head_rows - 1]
    # 모서리 라벨: 행 머리 축의 이름(예: "수급 분류") — 각 열 머리 줄 앞에 붙는다.
    # 머리가 2단 이상이면 모서리 블록(머리 행 × 머리 열)의 이름을 순서대로 모두 잇는다.
    # 옛 구현은 col_names[n_head_cols-1] 한 칸만 썼기 때문에 나머지 모서리 칸("구분",
    # "혈액 성분" 등)이 출력 어디에도 실리지 않고 사라졌다.
    corner_cells: list[str] = []
    for hi in range(n_head_rows):
        for c in rows[hi][:n_head_cols]:
            c = c.strip()
            if c and c not in corner_cells:
                corner_cells.append(c)
    corner = " ".join(corner_cells)
    corner_br = _translate(corner) if corner else ""

    def _cell(v: str) -> str:                    # 빈 셀 = ⠿⠿ (BBPG-3.1.2(4))
        return _translate(v) if v else _EMPTY_CELL

    # 행 그룹(예: 성별) — 행 머리 열 중 마지막을 뺀 나머지가 그룹 키
    groups: list[tuple[tuple[str, ...], list[list[str]]]] = []
    for r in body:
        key = tuple(r[: max(0, n_head_cols - 1)])
        if groups and groups[-1][0] == key:
            groups[-1][1].append(r)
        else:
            groups.append((key, [r]))

    lines: list[str] = []
    prev_section = None
    for key, rows_in in groups:
        for j in range(n_head_cols, n_cols):
            # 상위 열 머리(병합된 대분류) + 그룹 키 → 구간 제목
            tops: list[str] = []
            for h in range(n_head_rows - 1):
                v = rows[h][j]
                if v and v not in tops:
                    tops.append(v)
            section = " ".join([*tops, *(k for k in key if k)]).strip()
            if section and section != prev_section:
                lines.append(f"{_PAD * _ROW_INDENT}{_translate(section)}")
                prev_section = section
            # 열 머리 줄 = 구간 머리. 정답 도서 실측(사회문화 p087·p174)은 5칸(빈칸 4)에
            # 적고, 그 아래 딸린 줄은 3칸에서 '행 머리{쌍점}{한 칸}값'으로 적는다.
            # 쌍점 ⠐⠂ + 한 칸은 gold 원문과 셀 단위로 일치(p087 3행 ⠺⠑⠕⠐⠂⠀…).
            head_br = (f"{corner_br}{sep}" if corner_br else "") + _cell(col_names[j])
            lines.append(f"{_PAD * _TITLE_INDENT}{head_br}")
            for r in rows_in:
                row_head = r[n_head_cols - 1] if n_head_cols else ""
                row_br = f"{_translate(row_head)}{sep}" if row_head else ""
                entry = f"{_PAD * _ROW_INDENT}{row_br}{_cell(r[j])}"
                if len(entry) <= _COLS or not row_br:
                    lines.append(entry)
                elif _BOOK_STYLE:
                    # 정답 관행(세계사 p009·사회문화 p174 실측): 값이 32칸을 넘치면 행 머리를
                    # 단독 줄로 세우고(이때는 쌍점 없이) 값을 다음 줄부터 적는다.
                    lines.append(f"{_PAD * _ROW_INDENT}{_translate(row_head)}")
                    lines.append(f"{_PAD * _ROW_INDENT}{_cell(r[j])}")
                else:
                    # 규정: 행 제목 단위로 줄을 바꾸고(§3.3.1(4)) 한 셀이 두 줄로 나뉘면
                    # 다음 줄 **첫 칸부터** 이어 적는다(도서지침 제3장 6)(3)).
                    lines.extend(_split_lines(entry))
    return head + lines if lines else (head or [""])


def print_layout(corrected_text: str, mode: str) -> str:
    """표 초안의 **묵자** 배치 (2026-08-06).

    FE 피커는 묵자와 점자를 나란히 보여 준다(와이어프레임). 종전에는 초안 4개가 전부
    `text=원문`이라 묵자 칸이 똑같아 무엇을 고르는지 알 수 없었다.

    ★ 점자 렌더러(`_render_*`)를 재활용하지 않는다 — 그쪽은 `_translate`가 19곳에 박혀
      있어 파라미터화하면 점자 출력이 흔들린다. 배치 규칙만 같은 별도 함수로 둔다.
    ★ 32칸 접기는 하지 않는다. 묵자는 그 제약이 없고, 피커는 **배치 모양**을 보이는 게 목적이다.
    """
    if mode == "transposed":
        corrected_text = _transpose_text(corrected_text)
    rows = [[c.strip() for c in ln.split("|")]
            for ln in corrected_text.splitlines() if ln.strip()]
    if not rows:
        return corrected_text
    out: list[str] = []
    if mode == "linear":                      # 키  값 (2열 표)
        for r in rows:
            out.append("  ".join(c for c in r if c) if len(r) > 1 else (r[0] if r else ""))
    elif mode == "unfold":                    # 행머리 + 값들을 줄마다 (§3.1.2)
        for r in rows:
            head, vals = (r[0] if r else ""), [c for c in r[1:] if c]
            out.append(f"{head}  " + "  ".join(vals) if vals else head)
    else:                                     # table_grid · transposed — 행머리: 값  값
        for r in rows:
            head, vals = (r[0] if r else ""), [c or "(빈칸)" for c in r[1:]]
            out.append(f"{head}: " + "  ".join(vals) if vals else head)
    if mode == "transposed":
        out.insert(0, "[점역자 주] 행과 열을 바꾸어 표기함")
    return "\n".join(out)


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
                # 플레이스홀더는 점역 안 된 원문 그대로 — 내용 규정 emit 금지(환각 0).
                rule_trail=_base_trail(lines, text, content=False),
            )

        # <!표> 구조 태그 → 내부 '|' 격자로 변환해 기존 4안 렌더러에 위임(1:1).
        parsed_rows = parse_table_tags(text)
        if parsed_rows is not None:
            text = "\n".join(" | ".join(r) for r in parsed_rows)

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
        # 전치 초안도 점역자 주를 태그로 낸다 — 옛 구현은 _translate(_TN_TRANSPOSE)라
        # 양끝 마커 ⠠⠄가 빠져 '그냥 한 줄 문장'으로 나갔고 rule_trail도 안 잡혔다.
        transposed_lines = _wt([_tn_transpose_line()] + _render_grid(_transpose_text(text)))
        linear_lines = _wt(_render_linear(text))
        # 자동 경로가 전치했으면 그 점역자 주가 출력에 실린다 → 태그를 트레일 원본에 얹어
        # BBPG-1.2.6이 emit되게 한다(_base_trail은 원본에 태그가 있을 때만 emit).
        unfold_src = text + ("\n" + _TN_SRC if any(_TN_SRC_MARK in ln for ln in unfold_lines) else "")
        drafts = [
            Draft(option=1, text=print_layout(text, "unfold"), render_mode="unfold", label="테두리 없음",
                  braille_lines=unfold_lines,
                  rule_trail=_base_trail(unfold_lines, unfold_src) + [make_rule("BBPG-3.1.2")]),
            Draft(option=2, text=print_layout(text, "table_grid"), render_mode="table_grid", label="테두리+구분선",
                  braille_lines=grid_lines, rule_trail=_base_trail(grid_lines, text)),
            Draft(option=3, text=print_layout(text, "transposed"), render_mode="transposed", label="행열 바꿈",
                  braille_lines=transposed_lines,
                  rule_trail=_base_trail(transposed_lines, text + "\n" + _TN_SRC)
                             + [make_rule("BBPG-3.1.2")]),
            Draft(option=4, text=print_layout(text, "linear"), render_mode="linear", label="테두리만",
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
