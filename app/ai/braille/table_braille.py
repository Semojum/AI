"""PART 6-3 — 표 점역 (render_mode 기반 조판).

표의 복수 초안(3안)은 LLM 텍스트가 아니라 **레이아웃 3종**이다
(stage4_complex.md 'T4-2 공통 규약' — 표=레이아웃 차이, 셀 값 동일):
  table_grid : ⠿ 테두리 + ⠒ 행 구분선 (격자 원형)
  transposed : 행↔열 전치 (점자 도서 제작 지침 3장1절 BBPG-3.1.2, 점역자 주 동반)
  linear     : '  키  값' 선형 풀어쓰기 (3칸 시작, 유도점·콜론 없음)
격자 구조가 아닌 비정형(narrative)·처리불가는 단일안으로 처리한다.
"""

from __future__ import annotations

import re

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
_EMPTY_CELL = "⠿⠿"  # 빈 셀 (BBPG-3.1.2(4))
_SEP     = "⠒"  # 행·셀 구분선

# ── 표 구조 태그 (plan §3-5 확장) ─────────────────────────────────────────────
# table_opt가 stage②(점역 직전 텍스트)에 <!표>/<!행>/<!칸>으로 표 구조를 출력하고,
# 여기서 행렬로 파싱해 기존 4안 렌더러(풀어쓰기/격자/전치/선형)에 1:1 위임한다.
_TBL_OPEN, _TBL_CLOSE = "<!표>", "<!/표>"
_TBL_ROW_OPEN, _TBL_ROW_CLOSE = "<!행>", "<!/행>"
_TBL_CELL = "<!칸>"
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
        cells = m.group(1).split(_TBL_CELL)
        if cells and cells[0] == "":
            cells = cells[1:]   # 첫 <!칸> 앞 빈 셀 제거
        rows.append([c.strip() for c in cells])
    return rows or None
# 유도점: 지침 §(5)는 열 항목 간격이 5칸 이상일 때 열 **사이**에 `"`를 연속으로 적으라 한다
# (열 제목 사이는 제외). 줄머리에 무조건 붙이던 옛 구현을 제거 — 진짜 규정 유도점은 미구현.
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
    """지침 §3.1 표 표기(행 단위 전개, 예3-4·3-6 실측 형식, 2026-07-19 정정).

    위 테두리 ⠿⠛…⠿ · 아래 테두리 ⠿⠶…⠿ 안에, 각 행을 3칸(앞 빈칸 2)에서
    '행제목: 값  값'(쌍점 ⠐⠂ + 한 칸, 값 사이 두 칸)으로 적는다. 빈 셀 = ⠿⠿(§3.1.2(4)).
    (구 격자형 — 전체 ⠿ 채움 테두리·세로 ⠿ 벽·행 구분선 — 은 지침 예시와 달랐다.
     layout._is_border_line이 이 테두리 형을 정식 인정해 들여쓰기 미적용도 유지된다.)
    """
    rows = [ln for ln in corrected_text.splitlines() if ln.strip()]
    top = "⠿" + "⠛" * (_COLS - 2) + "⠿"
    bot = "⠿" + "⠶" * (_COLS - 2) + "⠿"
    if not rows:
        return [top, bot]
    lines: list[str] = [top]
    for row in rows:
        cells = [c.strip() for c in row.split("|")]
        head = _translate(cells[0]) if cells[0] else "⠿⠿"
        vals = [(_translate(c) if c else "⠿⠿") for c in cells[1:]]
        body = head + ("⠐⠂⠀" + "⠀⠀".join(vals) if vals else "")
        lines.append("⠀⠀" + body)
    lines.append(bot)
    return lines


def _render_linear(corrected_text: str) -> list[str]:
    """2열 표 → 한 줄에 '키  값'. 3칸에서 시작하고 키와 값을 두 칸 띄운다.
        `  언어 문제  64.9`   (유도점·콜론 없음 — 코퍼스 확인)

    ★ BRAILLE_STYLE을 타지 않는다(2026-07-17). 다른 항목은 기본이 규정이지만 표는 아니다 —
      여기 있던 '규정 모드' 분기(`⠄키: 값`)가 규정이 아니었기 때문이다:
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
                entry = f"  {head_br}⠀⠀{val_br}"
                if len(entry) > _COLS:
                    # 정답 관행(세계사 p009 실측): 키+값이 32칸을 넘치면 키를 단독 줄로
                    # 세우고 값을 다음 줄부터 — 한 줄에 이어붙이지 않는다.
                    result.append(f"  {head_br}")
                    result.extend(_split_lines(f"  {val_br}") if len(val_br) + 2 > _COLS
                                  else [f"  {val_br}"])
                    continue
            else:
                entry = f"  {_translate(parts[0])}"
        else:
            entry = _translate(ln)
        if len(entry) <= _COLS:
            result.append(entry)
        else:
            result.extend(_split_lines(entry))
    return result or [""]


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


_WORD_CELL_MAX = 14      # 셀이 '낱말 수준'인지 '문장 수준'인지 가르는 점자 길이
_ROWWISE_MAX_WIDTH = 40  # 한 행을 통째로 한 줄에 적을 때 허용 폭(§3.1.1(1)① 32칸 + 한 번 접힘)
_COLON = "⠐⠂⠀"          # 쌍점 + 한 칸 (정답 도서 실측: 사회문화 p087 '의미⠐⠂⠀하층의…')


def _word_level(rows: list[list[str]]) -> bool:
    """셀이 낱말 수준인가(↔ 여러 단어·문장).

    지침 §3.1.1(1)②는 '열 항목을 두 칸씩 띄어 풀어 적는다', ③은 '열 항목이 여러 단어와
    문장으로 되어 있어 가로로 풀어 적을 경우 표를 이해하기 어렵다면' 다른 방식으로 적으라
    한다. 즉 갈림길은 셀이 낱말 수준인가다.

    정답 도서 실측도 같다 — 낱말 수준 표(생물 p119·p122, 사회문화 p185)는 열 항목을
    **두 칸** 띄어 적고, 문장 수준 표(사회문화 p087·p174)는 **쌍점**으로 잇는다.
    """
    return all(len(_translate(c)) <= _WORD_CELL_MAX for r in rows for c in r if c.strip())


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
    """
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
        lines.append("  " + "⠀⠀".join(_translate(c) if c.strip() else _EMPTY_CELL
                                      for c in cells))
    return lines or [""]


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
        return [f"  {_translate('  '.join(c for c in r if c))}" for r in rows] or [""]

    if _rowwise_ok(rows):                        # §3.1.1(1)② 낱말 수준·좁은 표 → 행 단위
        return _render_rowwise(rows, orig_len)
    # 열 단위 전개의 구분자: 낱말 수준이면 두 칸, 문장 수준이면 쌍점(정답 도서 실측).
    sep = "⠀⠀" if _word_level(rows) else _COLON

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
                lines.append(f"  {_translate(section)}")
                prev_section = section
            # 열 머리 줄 = 구간 머리. 정답 도서 실측(사회문화 p087·p174)은 5칸(빈칸 4)에
            # 적고, 그 아래 딸린 줄은 3칸에서 '행 머리{쌍점}{한 칸}값'으로 적는다.
            # 쌍점 ⠐⠂ + 한 칸은 gold 원문과 셀 단위로 일치(p087 3행 ⠺⠑⠕⠐⠂⠀…).
            head_br = (f"{corner_br}{sep}" if corner_br else "") + _cell(col_names[j])
            lines.append(f"    {head_br}")
            for r in rows_in:
                row_head = r[n_head_cols - 1] if n_head_cols else ""
                row_br = f"{_translate(row_head)}{sep}" if row_head else ""
                entry = f"  {row_br}{_cell(r[j])}"
                if len(entry) <= _COLS or not row_br:
                    lines.append(entry)
                else:
                    # 정답 관행(세계사 p009·사회문화 p174 실측): 값이 32칸을 넘치면 행 머리를
                    # 단독 줄로 세우고(이때는 쌍점 없이) 값을 다음 줄부터 적는다.
                    lines.append(f"  {_translate(row_head)}")
                    lines.append(f"  {_cell(r[j])}")
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
