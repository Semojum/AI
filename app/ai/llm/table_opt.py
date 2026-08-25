"""PART 6-2 — 표 점역 최적화 (HyperCLOVA X SEED Think 14B INT4, GPU 1).

점역사주 복수 초안 생성 + render_mode 결정.
render_mode 우선순위: table_structure['render_mode'] → 행/열 수 기반 추론 → unfold(풀어쓰기)

공통 추론·폴백·재시도는 base_opt — 여기서는 표에 최적화된 프롬프트·구조 추론만 정의한다.
"""

from __future__ import annotations

import logging
import re
import time
from html import unescape as _html_unescape
from typing import Optional

from app.ai.braille.nested_block import box_narrative
from app.ai.braille.regulations import make_rule
from app.ai.braille.table_braille import build_table_tags, parse_table_tags, print_layout
from app.ai.llm.base_opt import BaseOpt, decide_tier_timeout, generate_with_retry
from app.ai.llm.draft_utils import ensure_tn_prefix
from app.core.model_manager import model_manager  # noqa: F401 (단위 테스트가 이 네임스페이스를 patch)
from app.schemas.content import Draft, ExtractedContent, LLMOutput, RuleApplication

logger = logging.getLogger(__name__)

_NESTED_IMAGE_TYPES = {"image", "picture", "photo", "그림", "사진", "illustration"}


def _nested_image_text(ext: ExtractedContent) -> Optional[str]:
    """표 안 그림(Q11) → 그림을 글상자처럼 1단으로 풀어 쓴 보조 narrative. 없으면 None."""
    for src in (ext.structure, ext.table_structure):
        if src and src.get("nested"):
            blocks = [n for n in src["nested"]
                      if (n.get("type") or "").strip() in _NESTED_IMAGE_TYPES]
            if blocks:
                return box_narrative(blocks, default_label="그림")
    return None


# ★ 2026-08-25 — 이름을 규정 낱말로 맞췄다(계획서 §5, 동작 무수정).
#   · "격자형" → **"정렬 유지"**: §3.2 절 제목이 "원본의 정렬 형태를 유지하는 표"다.
#   · "행↔열 전치"(table_braille)와 "행열 바꿈"(여기)이 **같은 것의 두 이름**이었다 → 하나로.
#   · "선형(키:값)" 조어는 지우되 unfold 와 구별되게 **"키·값 풀어쓰기"**로 둔다.
#     초안에서 빼는 것은 실측이 막았다 — `_TABLE_DRAFT_MODES` 주석 참조.
_RENDER_LABEL = {"table_grid": "정렬 유지", "transposed": "행열 바꿈",
                 "linear": "키·값 풀어쓰기", "text_only": "풀어쓰기"}


def _min_trail(render_mode: str = "") -> list[RuleApplication]:
    """표 점역 일반 사항(BBPG-3.1.1) — 요소 전체(line_no=-1).

    이 조항은 그 자체가 (B)다: "표는 …풀어주는 것을 원칙으로 하며 **점역자에 따라서
    표기 형식이 다를 수 있다**". 그래서 남기되, Step17에서 **우리가 고른 형식**을 tag에
    담는다 — 격자/행열바꿈/선형 중 어느 것으로 냈는지가 점역사가 제일 먼저 바꿀 자리다
    (원장 C-01a 표 격자 테두리도 같은 갈림길이다).
    """
    label = _RENDER_LABEL.get(render_mode, "")
    return [make_rule("BBPG-3.1.1", tag=label)]

_PROMPT_TABLE_GRID = """당신은 한국어 점역 전문가입니다.
다음 표 내용을 점역사주([점역사주])로 표현하는 2가지 방식을 제안하세요.

표 내용:
{table_text}

형식:
[방식1] [점역사주] ...
[방식2] [점역사주] ...

가장 적합한 방식 번호(1 또는 2)를 마지막 줄에 "선택: N" 형식으로 기재하세요."""

_PROMPT_IRREGULAR = """당신은 한국어 점역 전문가입니다.
다음 비정형 표 내용을 점역사주로 간결하게 표현하세요.

원문:
{text}

[점역사주]로 시작하는 설명 1문장만 반환하세요."""


def _table_title(ext: ExtractedContent) -> Optional[str]:
    """표 제목(전사) — 도서 제작 지침 제3장 5)(1) 5칸·(2) 표 위에 먼저.

    구조화 입력(table_structure 또는 structure)의 'title'을 그대로 전사한다(rule-based).
    원본에서 제목이 표 안에 있어도 점역 자료에서는 표 위로 올린다(§3 5)(2)).

    ⚠ **지금 이 함수는 실동작에서 한 번도 안 돈다 — 채우는 쪽이 없다**(2026-08-10 실측).
      10쪽 표본에서 발동 0회였고, 파이프라인 어디에도 `table_structure['title']`을 쓰는
      코드가 없다. 소비자만 있고 생산자가 없는 상태다.

      문을 열까 재봤는데 **열 값어치가 없었다.** MinerU는 `table_caption`을 표마다 주지만
      (키 자체는 286/286), 실측 표 326개 중 캡션이 **있는 것이 13개(4%)**뿐이고
      그중 괄호형 제목처럼 보이는 4개도 **절반이 문항 번호**다(`[26022-0184]`).
      나머지는 발문·본문 조각이라 제목이 아니다. 규칙으로 가려도 유효 신호가 두어 건이다.

      즉 **교재 표에는 애초에 제목이 거의 없다.** 지침 §3 5)는 제목이 있을 때의 조판을
      정한 것이지 없는 제목을 만들라는 게 아니다.

      그래서 이 코드는 **지우지 않고 둔다** — 제목을 주는 입력(현주 구조화 핸드오프,
      다른 교재)이 오면 그대로 동작한다. 다만 **"표 제목 조판을 고쳤다"를 성과로 세지 마라.**
      실물에서 안 돈다. 앞 빈칸 4(= "5칸에서 시작")로 맞춘 것은 규정 준수일 뿐 점수 영향 0이다.
    """
    for src in (ext.table_structure, ext.structure):
        if src:
            t = (src.get("title") or "").strip()
            if t:
                return t
    return None


def _table_to_grid(table_structure: dict) -> list[list[str]]:
    """table_structure dict → 행렬(list[list[str]]). 셀 없으면 빈 리스트."""
    cells: list[dict] = table_structure.get("cells", [])
    if not cells:
        return []
    max_row = max((c.get("row", 0) for c in cells), default=0) + 1
    max_col = max((c.get("col", 0) for c in cells), default=0) + 1
    grid: list[list[str]] = [[""] * max_col for _ in range(max_row)]
    for cell in cells:
        r, c = cell.get("row", 0), cell.get("col", 0)
        if r < max_row and c < max_col:
            grid[r][c] = str(cell.get("text", ""))
    return grid


def _table_to_text(table_structure: dict) -> str:
    """table_structure dict → '|' 구분 텍스트(LLM 프롬프트·render_mode 추론용)."""
    grid = _table_to_grid(table_structure)
    if not grid:
        return table_structure.get("text", "") or ""
    return "\n".join(" | ".join(row) for row in grid)


def _pipe_to_grid(text: str) -> list[list[str]]:
    """'|' 구분 텍스트 → 행렬(현주 핸드오프가 파이프 텍스트만 줄 때 대비)."""
    return [[c.strip() for c in ln.split("|")] for ln in text.splitlines() if ln.strip()]


# MinerU는 표를 <table><tr><td>… HTML로 낸다(P5). 셀을 보존하려면 격자로 파싱해야
# narrative(산문 요약)로 오분류되지 않고 unfold/linear로 점역된다.
# ★ colspan/rowspan을 펼쳐야 한다 — 무시하면 행마다 셀 수가 달라져 열이 어긋나고
#   빈칸(⠿⠿)이 엉뚱한 자리에 찍힌다(정답과 대조해 확인, 2026-07-13).
_TR_RE = re.compile(r"<tr[^>]*>(.*?)</tr>", re.DOTALL | re.IGNORECASE)
_TD_RE = re.compile(r"<(t[dh])([^>]*)>(.*?)</\1>", re.DOTALL | re.IGNORECASE)
_HTML_TAG_RE = re.compile(r"<[^>]+>")
_SPAN_RE = re.compile(r"(col|row)span\s*=\s*[\"']?(\d+)", re.IGNORECASE)


def _is_html_table(text: str) -> bool:
    return "<table" in (text or "").lower()


def _spans(attrs: str) -> tuple[int, int]:
    """(colspan, rowspan)."""
    col = row = 1
    for kind, n in _SPAN_RE.findall(attrs or ""):
        v = max(1, int(n))
        if kind.lower() == "col":
            col = v
        else:
            row = v
    return col, row


# MinerU가 밀집 숫자표에서 소수점 '.'을 쉼표 ','로 자주 오독한다(PDF 원문 대조로 확정:
# '42.8'→'42,8'). 규정 제48항 소수점은 ⠲, 제41항 자릿점(천단위)은 ⠂로 서로 다르므로
# 오독을 그대로 두면 엉뚱한 점형이 된다. 쉼표 뒤 1~2자리+경계면 소수(복원 '.'),
# 3자리면 천단위(그대로)로 판별 — '2,575'(천단위)는 건드리지 않고 '42,8'만 '42.8'로.
_DECIMAL_COMMA_RE = re.compile(r"(?<=\d),(?=\d{1,2}(?:\D|$))")


def _fix_decimal_comma(text: str) -> str:
    return _DECIMAL_COMMA_RE.sub(".", text)


# 대각선으로 나뉜 머리칸(`문항\학생`·`인구 구조 \ 연도`) — 인쇄본의 구획선이다.
# MinerU가 그 선을 `\`로 넘기면 점역이 ⠸⠡(역빗금)을 찍는다. 두 머리말은 남기고 선만
# 없앤다(한 칸으로).
#
# ⚠ 규정과 도서 관행이 갈리는 자리다. 규정은 이 자리를 직접 정한다 —
#     「2025년도 개정 …점자교과서 및 교수학습 자료 제작 지침」 §3.1.3(4)
#       "표의 1행 1열의 대각선은 빗금 _/으로 적는다."   (_/ = ⠸⠌)
#   정답 도서는 **대체로** 빗금도 역빗금도 쓰지 않고 두 라벨을 다른 자리에 나눠 적는다 —
#   사회문화 p100 gold는 표를 연도별로 묶고 `연도`를 각 묶음 머리로, `인구 구조`를 그 다음
#   줄 제목으로 올린다. 우리 렌더러(unfold/linear)에는 그 재구조화가 없다.
#   ★ 단 **gold는 만장일치가 아니다**(2026-07-27 독립 검증에서 정정): 생물 p058 gold 6행이
#     ⠰⠞⠠⠍⠸⠌⠻⠚⠺(철수+⠸⠌+영희)로 §3.1.3(4) 규정형 빗금을 실제로 쓴다. 대각선 20건 중 1건.
#     구 주석의 "둘 다 0회"는 거짓이었다.
#   ⚠ 규정형(빗금) 발행 A/B 수치도 재현되지 않았다. 구 주석은 "dev +138·val +358 양쪽 악화"였으나
#     독립 재현은 **dev −5(개선)·val +305**로 dev 부호가 뒤집힌다(규정형이 개선시키는 페이지가
#     사회문화 p178·생물 p058로 실재하고, val 악화는 수학2 p016 한 장이 대부분).
#   → 따라서 "gold가 0회라 관행 우선"이라는 근거는 무너졌고, **대각선을 어떻게 적을지는 열린
#     질문**이다. 지금 '없앤다'까지만 하는 것은 잠정 조치이며, 규정형 채택 여부는 점역사 확인
#     대상이다(대괄호 D-12·제29항 종료표 건과 같은 성격).
#
# ★ 적용 범위는 규정이 말하는 **1행 1열**뿐이고, 양옆이 라벨(글자)일 때만이다. 대각선은
#   두 머리말을 가르는 선이므로 앞뒤가 글자다. 이 조건을 빼면 대각선이 아닌 백슬래시를
#   망가뜨린다 — 실측: 표 안 LaTeX(`$\frac{1}{2600}$`·`$\alpha$` 등 dev+val 71칸)이
#   셀 단위 배선에 걸려 `$ frac{1}{2600}$`로 뭉개지고 있었다. 추출이 흘리는 마크다운
#   이스케이프(`32\~33`·`\- 항목`)도 같은 꼴이다.
#   '글자'에는 그리스 문자와 성별 기호도 넣는다 — 표 머리 라벨로 실제로 쓰인다
#   (생물 p161 격자 머리 `♀\δ`). 반대로 LaTeX·마크다운 이스케이프의 백슬래시 앞은
#   늘 `$ { [ = , ~ -` 같은 구분자라 이 집합에 들지 않는다.
_LABEL_CH = r"0-9A-Za-z가-힣Ͱ-Ͽ♀♂"
_DIAGONAL_HEAD_RE = re.compile(
    rf"(?<=[{_LABEL_CH}])\s*\\\s*(?=[{_LABEL_CH}])")


def _strip_diagonal_rule(text: str) -> str:
    """1행 1열 대각선 `\\` 제거 — 두 머리말을 한 칸으로 잇는다."""
    return _DIAGONAL_HEAD_RE.sub(" ", text)


# 병합 헤더 코너의 범용(의미 없는) 라벨 — 점역은 반복하지 않는다(2026-07-20 실측).
# '구분'은 행·열 축 이름이 따로 없을 때 표 좌상단을 채우는 관용적 필러 단어로, 정보값이
# 없다. 사회문화·생물 8개 표(15건, val+dev 양쪽)를 정답과 대조: colspan/rowspan으로
# 펼쳐진 '구분' 복제 중 정답에 그대로 남아 있는 사례는 0/8 — 나머지는 좌표만 다른
# 실제 열/행 라벨(예 '어느 계층에 속한다고 생각하는가?', '소득 계층')로 대체돼 있었다.
# 대조군: 같은 방식으로 반복되는 '제재'(표 주제, 언어 7개 표)는 정답에 그대로
# 유지된다(개수까지 일치) — 의미 있는 열 그룹 제목은 유지, 값 없는 필러만 접는다.
# 앵커(펼침의 첫 칸)만 남기고 나머지 칸은 빈칸으로 접는다 — 격자 폭(열 정렬)은 그대로
# 유지되므로 _render_grid/_render_unfold 등 다른 렌더러의 폭 계산에 영향 없다.
_GENERIC_CORNER_LABELS = {"구분"}

# 표 안 유도점(leader dots) — 인쇄본은 열 항목 사이 긴 간격을 점선으로 시각 정렬하지만
# 그 점선 자체가 MinerU에서 독립된 <td>로 추출된다(외국어 p014/p236 실측, colspan 없음
# — 병합 복제가 아니라 원본 HTML 자체가 빈 칸을 별도 셀로 낸 것). 정답은 이 칸을 아예
# 없는 것처럼 취급하고 값 칸 사이를 그냥 빈칸으로 잇는다("EXAMPLE␣␣MOREOVER", 점형
# 없음, 2026-07-20 실측) — 표 안 말줄임표(⠲⠲⠲, 문장부호 규정)로 잘못 옮기면 안 된다.
# 규정(점자 자료 제작 지침 §3.2.1(5))의 진짜 유도점(열 간격 5칸 이상일 때 " 연속)은
# 열 너비 인지가 필요해 미구현(table_braille.py 기존 주석) — 여기서는 최소한 오기호
# (⠲⠲⠲)를 내지 않도록 빈 칸으로만 접는다.
_LEADER_DOTS_RE = re.compile(r"^\.{3,}$")


def _cell_text(body: str) -> str:
    """<td> 본문 → 셀 원문. 태그 제거 → **엔티티 해제** → 소수점 오독 정정.

    ★ 엔티티 해제(html.unescape)가 없으면 마크업 이스케이프가 본문 글자로 새어 나간다.
      MinerU가 셀 안의 부등호를 HTML 규약대로 `&gt;`/`&lt;`로 내는데, 그대로 점역하면
      `A>C`가 `⠠⠁⠯⠛⠞⠰⠆⠠⠉`(= 문자열 "A&gt;C"를 한 글자씩 점역한 것)가 된다.
      규정은 이 자리에 부등호 한 기호만 요구한다 —
        한국 점자 규정 제45항 표: '보다 크다' `>` = 55 = ⠢⠢ / '보다 작다' `<` = 99 = ⠔⠔
        (수학 점자 제4항 2·4도 같은 점형: `a55b`, `x99#j`)
      즉 `&gt;` 5글자를 옮기는 것은 규정 이전에 원문에 없는 글자를 찍는 결함이다.
      unescape는 태그 제거 **뒤에** 해야 한다 — 먼저 하면 `&lt;`가 `<`로 풀려
      _HTML_TAG_RE에 태그로 잡아먹힌다.
    """
    return _fix_decimal_comma(_html_unescape(_HTML_TAG_RE.sub("", body)).strip())


def _html_to_grid(html: str, *, expand: bool = True) -> list[list[str]]:
    """MinerU <table> HTML → 행렬. 내부 태그 제거(이미지 셀=빈칸).

    expand=True  colspan/rowspan을 같은 값으로 복제해 **직사각 격자**를 만든다.
                 열 수를 세거나(`_infer_render_mode`) 열 정렬이 필요한 곳 전용.
    expand=False 병합 셀을 **원본대로 한 번만** 낸다(행 길이가 들쭉날쭉해진다).
                 점역 출력에 쓰는 표기다.

    ★ 병합 복제를 그대로 찍던 것이 표 축 과잉생산의 최대 원인이었다(2026-08-08).
      실측: dev-2027 표 4,311개에서 비어 있지 않은 칸 78,525개 중 **11,145개(14.2%)가
      병합 복제**다. gold는 병합 셀을 한 번만 적는다 — 지침 §3.1.3에 복제를 적으라는
      조항이 없고 §3.1.4(3)은 되레 "반복된 열 제목은 생략한다"이며, 실물
      (EBS-E26-009 p0091·EBS-E26-004 p0002)에서도 한 번씩만 나온다.
      우리는 colspan="8" 셀을 여덟 번 찍어, 한 표가 gold 1,648셀 자리에 6,304셀을 냈다.
      ⚠ 값이 같은 인접 칸을 지우는 '값 기준' 축약으로 대체하지 말 것 — 같은 실측에서
        후보의 31.4%(3,618칸)가 병합이 아닌 **진짜 반복 값**('+', '-', '없다')이라
        내용을 지운다. 병합 여부는 파싱 시점에만 알 수 있다.
      ※ 규정·관행이 같은 방향이라 원장(규정-관행_대조원장.md) 등재 대상이 아니다 —
        충돌이 아니라 우리 결손이다.
    단, 값 없는 범용 코너 라벨(_GENERIC_CORNER_LABELS)은 앵커 칸에만 남긴다.
    """
    grid: list[list[str]] = []
    pending: dict[tuple[int, int], str] = {}   # (row, col) → rowspan으로 내려오는 값
    for r, tr in enumerate(_TR_RE.findall(html)):
        row: list[str] = []
        c = 0
        for _tag, attrs, body in _TD_RE.findall(tr):
            while (r, c) in pending:            # 위에서 내려온 rowspan 자리 먼저 채움
                v = pending.pop((r, c))
                if expand:
                    row.append(v)
                c += 1
            text = _cell_text(body)
            if _LEADER_DOTS_RE.match(text):
                text = ""                        # 유도점 칸 — 값처럼 옮기지 않는다
            colspan, rowspan = _spans(attrs)
            is_generic_merge = (
                text in _GENERIC_CORNER_LABELS and (colspan > 1 or rowspan > 1))
            for dc in range(colspan):
                keep = (not is_generic_merge) or (dc == 0)
                if expand or dc == 0:
                    row.append(text if keep else "")
                for dr in range(1, rowspan):
                    pending[(r + dr, c + dc)] = "" if is_generic_merge else text
            c += colspan
        while (r, c) in pending:                 # 행 끝에 남은 rowspan 자리
            v = pending.pop((r, c))
            if expand:
                row.append(v)
            c += 1
        if row:
            grid.append(row)
    if grid and expand:                          # 행 길이 정규화(직사각일 때만)
        w = max(len(r) for r in grid)
        grid = [r + [""] * (w - len(r)) for r in grid]
    return grid


def _normalize_grid(grid: list[list[str]]) -> list[list[str]]:
    """격자 소스 3종(table_structure·HTML·파이프) 공통 정정.

    지금은 1행 1열 대각선뿐이다 — 규정이 **1행 1열**만 다루므로 셀 단위 파서가 아니라
    격자 좌표를 아는 여기서 건다. 셀 단위로 걸면 대각선이 아닌 백슬래시(표 안 LaTeX
    `$\\frac{1}{2600}$`·`$\\alpha$` 등 dev+val 71칸)까지 망가뜨린다.

    ★ 병합 복제분도 같이 바꾼다. 대각선 머리칸은 2단 머리에서 rowspan/colspan을 갖는
      일이 흔해(사회문화 p185·p092, 생물 p024 …) _html_to_grid가 같은 값을 아래·옆
      칸에 복제한다. 코너만 고치면 복제분에 역빗금이 그대로 남는다.
    """
    if not (grid and grid[0] and grid[0][0]):
        return grid
    src = grid[0][0]
    dst = _strip_diagonal_rule(src)
    if dst == src:
        return grid
    for row in grid:
        for i, cell in enumerate(row):
            if cell == src:              # 코너 자신 + 병합 복제분
                row[i] = dst
    return grid


def _table_tags(table_structure, table_text: str) -> str:
    """표 구조 → <!표> 태그(stage② 표시·table_braille 입력). 비정형은 원문 유지."""
    grid = _table_to_grid(table_structure) if table_structure else []
    if not grid and _is_html_table(table_text):
        grid = _html_to_grid(table_text, expand=False)   # 병합은 원본대로 한 번만
    if not grid and "|" in table_text:
        grid = _pipe_to_grid(table_text)
    return build_table_tags(_normalize_grid(grid)) if grid else table_text


def _infer_render_mode(table_structure: Optional[dict], text: str = "") -> str:
    if table_structure:
        if rm := table_structure.get("render_mode"):
            return rm
        cells = table_structure.get("cells", [])
        if cells:
            max_row = max((c.get("row", 0) for c in cells), default=0) + 1
            max_col = max((c.get("col", 0) for c in cells), default=0) + 1
            if max_col == 2:
                return "linear"
            if max_row == 1:
                return "transposed"
            # 3열 이상 = **격자형**(2026-08-06 판정 번복 — 원장 C-01a).
            # 종전 기본은 풀어쓰기였다. gold 실측이 뒤집었다 — dev-2027의 테두리 표 445개 중
            # 383개(86%)가 격자형 '행제목: 값  값' 형식이고, 우리 격자형 렌더러가 내는
            # 내용 배치와 **동일**하다(EBS-E26-013 p8 실물 대조). 풀어쓰기는 행을 쪼개
            # 배치가 통째로 다르다. 기본이 비선택 초안이면 contents에 안 실린다.
            return "table_grid"
    # `<!표>` 구조 태그로 직접 들어오는 경로(mode b — BE가 txt에 태그를 실어 보낸다).
    # 열 수 세는 규칙은 아래 HTML·파이프 갈래와 같다. 이게 없으면 태그가 HTML도 파이프도
    # 아니라 narrative로 떨어져, 격자로 나가야 할 표가 풀어쓰기로 나갔다.
    if (tag_rows := parse_table_tags(text or "")):
        max_col = max(len(r) for r in tag_rows)
        return "linear" if max_col == 2 else "table_grid"
    # table_structure 없음/빈 셀: HTML 표(MinerU) 또는 '|' 격자로 추론(narrative 오분류 방지).
    if _is_html_table(text):
        grid = _html_to_grid(text)      # 여기만 expand=True — 진짜 열 수를 세야 한다
        if grid:
            max_col = max(len(r) for r in grid)
            return "linear" if max_col == 2 else "table_grid"
    rows = [ln for ln in (text or "").splitlines() if "|" in ln]
    if not rows:
        return "narrative"
    max_col = max(len(r.split("|")) for r in rows)
    return "linear" if max_col == 2 else "table_grid"


# 모델이 변환 대신 **상의를 답할 때** 나오는 말들. 이게 점자로 인쇄되면 점역사는 표 자리에서
# 회의록을 읽는다(eval 실측 2026-08-22: 7쪽 11,993셀, 한 쪽은 2,507셀).
_TN_META_RE = re.compile(
    r"점역\s*방식|방식을?\s*제안|제안합니다|일반적이므로|다음 두 가지|어떻게 (?:점역|표현)"
)
_TN_FAIL = "[처리 불가: 표 점역사주 생성 실패]"


def _parse_tn_from_response(response: str) -> str:
    """LLM 응답에서 [점역사주] 텍스트 추출. 선택된 방식 우선.

    ★ 2026-08-22 — 종전에는 초안 줄을 못 찾으면 **응답 전체를 그대로 돌려줬다**
      ("응답 전체가 TN인 경우"라는 낙관). 모델이 변환 대신 "이렇게 점역하면 어떨까요"를
      답하면 그 상의가 통째로 점자가 됐다. 실측 7쪽 11,993셀.
      → ① 여는 대괄호만 맞으면 살린다(`[점역사주:` 처럼 콜론을 붙이는 변형이 실제 원인이었다)
        ② 그래도 없으면 **원문을 흘리지 않고** 실패 표시를 낸다
        ③ 살린 줄에 상의 말투가 남아 있으면 실패로 본다.
      실패 표시는 짧고 눈에 띄어 점역사가 그 자리를 바로 찾는다.
    """
    lines = [ln.strip() for ln in response.splitlines() if ln.strip()]
    selected_idx = None
    for ln in lines:
        if ln.startswith("선택:"):
            try:
                selected_idx = int(ln.split(":")[1].strip()) - 1
            except (ValueError, IndexError):
                pass

    drafts = [ln for ln in lines if "[점역사주" in ln and not _TN_META_RE.search(ln)]
    if not drafts:
        return _TN_FAIL

    picked = drafts[selected_idx] if (selected_idx is not None and 0 <= selected_idx < len(drafts)) else drafts[0]
    return _strip_tn_labels(picked)


# 골라낸 줄에 남는 포장 — 방식 번호와 [점역사주] 표지는 **점역사에게 줄 내용이 아니다.**
# 종전에는 이것까지 점자로 찍혀 나갔다(실물 "※※[방식1]※※ [점역사주: …]").
_TN_LABEL_RE = re.compile(r"^[\s*※#\-]*\[?\s*방식\s*[0-9]+\s*\]?[\s*※:.)]*")
_TN_MARK_RE = re.compile(r"\[\s*점역사주\s*[:\]]\s*")


def _strip_tn_labels(line: str) -> str:
    s = _TN_LABEL_RE.sub("", line).strip()
    s = _TN_MARK_RE.sub("", s, count=1).strip()
    return s.rstrip("]").strip() or _TN_FAIL



# 표 배치 4안의 **묵자** — 점역 전 산출물이라 opt 단계에서 만든다 (2026-08-06).
# mode a는 점역을 하지 않으므로(include_braille=False) 여기서 안 만들면 대체 초안이 아예 없다.
# mode b·c에서는 table_braille가 같은 배치에 점자를 붙여 덮어쓴다(값은 같다 — 같은 함수).
# ★ 2026-08-25 — 이름만 고쳤다. '선형(키:값)'은 규정에도 점역사 어휘에도 없는 조어라
#   **빼려고 했는데 실측이 막았다**: linear 와 unfold 는 점자 출력이 다르다
#   (코퍼스 2열 표 106개 전수 대조 — 같은 것 0 · 다른 것 106. linear 는 테두리를 두르고
#   행 배치도 다르다). 겹치는 것은 묵자 배치뿐이고 점자는 겹치지 않는다. 빼면 2열 표가
#   전부 다시 흘러 **동작이 바뀐다** — 이 단계는 "라벨만, 동작 무수정"이라 이름만 고친다.
#   조어를 지우되 unfold 와 구별되게 "키·값 풀어쓰기"로 둔다. 실제 제거는 A/B 대상이다.
#   option 번호는 BE·FE 계약이라 1~4 그대로다.
_TABLE_DRAFT_MODES = [
    (1, "unfold", "풀어쓰기(3칸·2칸)"),
    (2, "table_grid", "정렬 유지"),
    (3, "transposed", "행열 바꿈"),
    (4, "linear", "키·값 풀어쓰기"),
]


def _print_drafts(table_text: str, render_mode: str) -> tuple[list[Draft], int]:
    """표 묵자 초안 4안 + 기본 선택 번호. `|`가 없으면(비정형) 초안을 만들지 않는다."""
    if "|" not in (table_text or ""):
        return [], 0
    drafts = [Draft(option=n, text=print_layout(table_text, m), render_mode=m, label=lb)
              for n, m, lb in _TABLE_DRAFT_MODES]
    sel = {"unfold": 0, "table_grid": 1, "transposed": 2, "linear": 3}.get(render_mode, 0)
    return drafts, sel


class TableOpt(BaseOpt):
    """ExtractedContent 목록 → LLMOutput 목록 (표)."""

    async def _optimize_one(self, ext: ExtractedContent, routing_tier: str) -> LLMOutput:
        start = time.monotonic()
        title = _table_title(ext)              # §3 5) 표 제목 5칸(전사). 없으면 None.
        nested_text = _nested_image_text(ext)  # 표 안 그림(Q11) → 글상자 1단. 없으면 None.
        render_mode = _infer_render_mode(ext.table_structure, ext.corrected_text or "")
        is_irregular = render_mode == "narrative" or (
            ext.table_structure is not None
            and ext.table_structure.get("irregular", False)
        )

        # C4: 표 신뢰도 낮음
        if "C4_FALLBACK" in ext.flags:
            return LLMOutput(
                element_id=ext.element_id,
                corrected_text="[표 수동 입력 필요]",
                render_mode="narrative",
                routing_tier="FALLBACK",
                processing_time_ms=0,
                rule_trail=_min_trail(),
            )

        # 텍스트 준비
        if ext.table_structure:
            table_text = _table_to_text(ext.table_structure)
        else:
            table_text = ext.corrected_text or ""
        # MinerU HTML 표 → '|' 격자 텍스트로 정규화(셀 보존·tn 요약·rule_trail용, P5)
        # 병합 복제는 펴지 않는다 — 이 텍스트가 묵자 4안(print_layout)에도 그대로 간다.
        if _is_html_table(table_text):
            grid = _html_to_grid(table_text, expand=False)
            if grid:
                table_text = "\n".join(" | ".join(row) for row in grid)

        if not table_text.strip():
            return LLMOutput(
                element_id=ext.element_id,
                corrected_text="[처리 불가: 표 내용 없음]",
                render_mode="narrative",
                routing_tier="FALLBACK",
                processing_time_ms=0,
                rule_trail=_min_trail(),
            )

        # 점역 직전 텍스트(stage②) = 표 구조 태그. table_braille가 파싱해 4안 렌더에 위임.
        # table_text(파이프)는 LLM 프롬프트·render_mode 추론·rule_trail 소스로만 사용.
        table_tags = _table_tags(ext.table_structure, table_text)

        if routing_tier == "ZERO":
            tn = ensure_tn_prefix(f"표. {table_text[:100]}")  # <!주>…<!/주>
            return LLMOutput(
                element_id=ext.element_id,
                corrected_text=table_tags,
                render_mode=render_mode,
                tn_text=tn,
                routing_tier="ZERO",
                processing_time_ms=0,
                rule_trail=_min_trail(render_mode),
                table_title=title,
                nested_text=nested_text,
                **dict(zip(("drafts", "selected_idx"), _print_drafts(table_text, render_mode))),
            )

        tier, timeout = decide_tier_timeout(ext.ocr_confidence)   # 요소당 상한 = config(작게)
        if is_irregular:
            prompt = _PROMPT_IRREGULAR.format(text=table_text[:500])
        else:
            prompt = _PROMPT_TABLE_GRID.format(table_text=table_text[:800])

        response, used_fb = await generate_with_retry(
            prompt, timeout=timeout, element_id=ext.element_id, kind="표",
            # 폴백 상한만 올린다(HCXT 512는 그대로). 프롬프트가 **두 방식**을 요구하는데
            # 표 opt 산출이 p95 560자라 두 벌이면 1,120자 ≈ 1,150토큰으로 1024를 넘는다.
            # 실측 상위 5% 표가 여기 걸렸고, 잘리면 행이 통째로 사라지는데 응답만 봐서는
            # 멀쩡해 보인다. max_tokens는 천장이라 안 잘리던 호출의 비용은 안 오른다.
            max_new_tokens=512, fallback_max_tokens=1536,
        )
        if used_fb:
            tier = "FALLBACK"

        if response:
            parsed = _parse_tn_from_response(response)
            # 처리불가 플레이스홀더는 TN 태그로 감싸지 않는다
            tn_text = parsed if parsed.startswith("[처리 불가") else ensure_tn_prefix(parsed)
        else:
            tn_text = ensure_tn_prefix(f"표. {table_text[:80]}")
        elapsed_ms = int((time.monotonic() - start) * 1000)
        return LLMOutput(
            element_id=ext.element_id,
            corrected_text=table_tags,
            render_mode=render_mode,
            tn_text=tn_text,
            routing_tier=tier,
            processing_time_ms=elapsed_ms,
            rule_trail=_min_trail(render_mode),
            table_title=title,
            nested_text=nested_text,
            **dict(zip(("drafts", "selected_idx"), _print_drafts(table_text, render_mode))),
        )
