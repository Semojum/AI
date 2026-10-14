"""인라인 태그 이름 정본 (§3-5). 이름은 **여기서만** 정의한다.

## 왜 짧게 바꿨나 (2026-08-12, 대표 지시)

`<!이름>` 태그는 점역 직전 텍스트에 그대로 남고, 그 텍스트가 **점역사 편집창에 보인다**
(mode a 우측 · mode b 좌측). FE가 회색으로 죽여 두긴 해도 이름이 길면 본문을 밀어낸다 —
실측(코퍼스 job 전수, `temp/measure_visual_tags.py`): 점역 직전 텍스트 2,711만 자 중
**223만 자(8.22%)가 태그 문자**였다. 점역자주 한 쌍이 17자인데 감싸는 본문이 그보다 짧은
경우가 흔하다(`<!점역자주>그림<!/점역자주>` = 태그 17자 : 본문 2자).

그래서 이름을 줄였다. 점역 결과(점자)는 **한 셀도 바뀌지 않는다** — 태그는 translator가
점자 글리프로 치환하고 사라지는 것이라, 이건 순전히 사람이 읽는 중간 텍스트의 문제다.

## 구 이름은 안 받는다 (2026-08-12 대표 지시)

한때 구 이름을 별칭으로 같이 등록했으나 걷어냈다. 두 이름이 동시에 유효하면 산출물마다
이름이 갈려 "어느 쪽이 정본인가"를 매번 다시 물어야 하고, 프롬프트·테스트·문서가
서서히 옛 이름으로 되돌아간다. **이름은 한 벌만 둔다.**

⚠ 그래서 이 변경 이전에 만들어진 `storage/jobs/**` 산출물은 다시 못 읽는다(태그가
  미지 태그로 안전 제거된다 — 점자는 나오되 점역자주·테두리 마커가 빠진다).
  옛 job을 다시 점역할 일이 있으면 그 job을 다시 돌려라.

## 이름표

| 이름 | 쌍 길이(전→후) | 무엇 |
|---------------|----------|---------|------|
| `점역자주`    | `주`     | 17→9    | 점역자 주 (NLD-1.2.6) |
| `드러냄`      | `강조`   | 13→11   | 드러냄표·밑줄 강조 (규정 제56항) |
| `테두리_위`   | `상자`   | 19→11   | 글상자 위 테두리 (NLD-1.2.5) |
| `테두리_아래` | `상자끝` | 21→15   | 글상자 아래 테두리 |
| `빈칸_표`     | `빈칸`   | 9→6     | 표 기입칸 (제73항) |
| `빈칸_밑줄`   | `밑줄`   | 11→6    | 밑줄 빈칸 (제73항, 표와 다른 기호) |
| `빈칸_네모`   | `네모`   | 11→6    | 네모 빈칸 (제73항) |

`표`·`행`·`칸`·`수식`은 손대지 않는다 — 앞 셋은 이미 한 글자라 줄일 게 없고, `수식`은
translator의 라우팅 앵커(`_INLINE_MATH_RE`)라 파급 대비 이득이 작다.
"""
from __future__ import annotations

import os
import re

# ── 현행 이름 ────────────────────────────────────────────────────────────────
TN = "주"                 # 점역자 주
EMPH = "강조"             # 드러냄표
BOLD = "굵은"             # 굵은 글자 (규정 제56항 · 원장 B-05)
BOX_TOP = "상자"          # 글상자 위 테두리
BOX_BOTTOM = "상자끝"     # 글상자 아래 테두리
BLANK_TABLE = "빈칸"      # 표 기입칸
BLANK_RULE = "밑줄"       # 밑줄 빈칸
BLANK_SQUARE = "네모"     # 네모 빈칸
# 규정 제64항 "네모 문자" — 네모 **안에 글자가 든** 자리를 감싸는 쌍 태그.
# `네모`(빈칸)와 다른 태그다: 저쪽은 안이 빈 네모라 단독으로 쓰고 여기는 내용을 감싼다.
BOX_CHAR = "네모글"      # 네모 문자 (제64항 · 원장 C-16-2)
# 영어 줄의 기울임 글자(#1205). 추출(`pdf_analyzer`)만 붙이고 점역기는 아직 걷어 낸다 — UEB 이탤릭
# 표지(⠨⠂ · ⠨⠶…⠨⠄)를 맞댈 묵자 짝이 없다(gold 이탤릭 242곳이 전부 짝 없는 책).
ITALIC = "기울임"
# 점자 태깅 목록표(docs/spec_v4/점자_태깅_목록표.md) 한글 강조 둘(#1382). 「한국 점자 규정」 제56항 [붙임](재추출
#   2477~2478행)의 제1 · 제2점역자 정의 글자체표다. 검출은 없다 — 앱 삽입 메뉴로만 들어온다.
COLOR_EMPH = "색강조"     # 색상 · 모양 강조 = ⠐⠤ … ⠤⠂ (목록표 63행)
STRIKE = "취소선"         # 취소선 = ⠈⠤ … ⠤⠁ (목록표 64행)
# 목록표 이름 → 엔진 이름(#1382, 목록표 70 · 71행). 교열(LLM)은 엔진 이름을 낸다(`text_opt` 지시) — 프롬프트를 고치면
#   캐시 열쇠가 바뀌므로 목록표 이름을 별칭으로 받는다. 번역기 입구(`translate_tagged_text`)에서 엔진 이름으로 푼다.
ALIASES = {"밑줄빈칸": BLANK_RULE, "네모빈칸": BLANK_SQUARE}
ITALIC_TAG_RE = re.compile(f"<!/?{ITALIC}>")   # 판정은 태그 없는 글로(mineru_runner) · 점역기는 걷어 낸다


def tn(text: str) -> str:
    """점역자 주로 감싼다 — 이 한 줄을 여기저기서 문자열로 짓다 이름이 갈렸다."""
    return f"<!{TN}>{text}<!/{TN}>"


def box(title: str = "") -> tuple[str, str]:
    """(위 테두리, 아래 테두리). 제목 없으면 빈 쌍."""
    return f"<!{BOX_TOP}>{title}<!/{BOX_TOP}>", f"<!{BOX_BOTTOM}><!/{BOX_BOTTOM}>"


# ── 들여쓰기 태그 (2026-08-25 대표 지시) ──────────────────────────────────────
# 줄별 들여쓰기를 **글 안에 태그로** 박는다. 종전에는 `line_indents` 목록을 요소 한 곳에만
# 실어, 안이 여럿일 때 **선택 안의 값이 다른 안에도 씌워졌다**(가계도 상향식에 하향식
# 들여쓰기가 붙고 줄 수가 같아 길이 검사도 통과했다). 태그는 자기 글에 붙어 다니므로
# 안을 바꿔도 어긋나지 않는다.
#
# ★★ **태그 숫자는 앞 빈칸 수다. 지침의 칸 번호가 아니다.**(대표가 직접 못 박음)
#      지침 "3칸에서 적는다" = <!2칸>      지침 "5칸에서 적는다" = <!4칸>
#      지침 "7칸에서 적는다" = <!6칸>
#    2026-08-10 에 `_TITLE_INDENT` 를 5→4 로 고치며 한 번 밟은 자리다. 다시 밟지 말 것.
#
# ★★★ **태그는 묵자에서 점자로 갈 때 달라지는 것만 표기한다.**(대표 지시 2026-08-25)
#    이 원칙은 이 태그만의 것이 아니라 **인라인 태그 전체의 기준**이다.
#    그래서 **들여쓰기 0에는 태그를 안 붙인다** — 0은 기본값이라 달라지는 게 없고,
#    표기할 것이 없으면 태그도 없다. 지침 "1칸에서 적는다"는 태그 없는 줄이다.
#      해모수            ← 태그 없음(앞 빈칸 0)
#      <!2칸>주몽
#      <!4칸>유리
#
# ⚠ 표 셀 태그 `<!칸>` 과 글자가 겹쳐 보이지만 정규식이 **줄머리 + 숫자**를 요구하므로
#   섞이지 않는다(`<!칸>` 에는 숫자가 없다).
_INDENT_TAG_RE = re.compile(r"^<!(\d+)칸>")


def indent_tag(spaces: int) -> str:
    """앞 빈칸 수 → 들여쓰기 태그. 0이면 빈 문자열(태그 없음) — 위 원칙 참조."""
    n = int(spaces)
    return f"<!{n}칸>" if n > 0 else ""


def split_indent(line: str) -> tuple[int | None, str]:
    """줄 → (앞 빈칸 수 | None, 태그 뗀 줄). 태그가 없으면 (None, 원문)."""
    m = _INDENT_TAG_RE.match(line)
    if not m:
        return None, line
    return int(m.group(1)), line[m.end():]


# ── 점역자 주 구간 정규화 — **양식은 코드가 정한다**(2026-09-08 대표 지시) ──────────
#
# 종전에는 조립기·LLM·상위 경로가 저마다 `<!주>` 를 붙였고, 그 결과가 그대로 나갔다.
# 대표 QA 실물(배포판 499afac)에서 세 꼴이 한 문서에 섞여 나왔다:
#     <!주>만화: …            ← 열고
#     <!주>장면 1<!/주><!/주> ← 안에서 또 열고, 닫는 태그가 둘
#     장면 1(현재)            ← 아예 안 감싸고
#     60년 후                 ← 주가 닫힌 뒤 남은 조각
# 이제 태그는 **여기서만** 짓는다. 들어온 태그는 "이 줄이 주 안이었나"를 읽는 신호로만
# 쓰고 전부 떼어 낸다. 그래서 위쪽이 무엇을 붙여 보내든 나가는 꼴은 늘 같다:
#   · 한 겹만 연다(중첩 없음)          · 여는 태그 하나에 닫는 태그 하나
#   · 잇닿은 주-안 줄은 한 덩이로 묶는다 · 주가 닫힌 뒤 조각이 안 남는다
# 줄 수는 절대 안 바꾼다 — `indents` 와 줄 단위로 짝지어지는 자리라 어긋나면 조판이 깨진다.
_TN_OPEN, _TN_CLOSE = f"<!{TN}>", f"<!/{TN}>"


_TN_SPLIT_RE = re.compile(r"(<!/?%s>)" % re.escape(TN))


def normalize_tn_spans(text: str) -> str:
    """점역자 주 태그를 **성한 꼴로 고친다.** 자리는 안 옮기고 줄 수도 안 바꾼다.

    고치는 것 넷 — 중첩된 여는 태그를 버리고 · 짝 없는 닫는 태그를 버리고 · 열린 채로
    끝나면 마지막 내용 줄에서 닫고 · 그래서 여는 하나에 닫는 하나만 남긴다.
    **어디를 감쌀지는 여기서 안 정한다** — 그건 조립기가 조항을 보고 정할 일이고
    (§6.3.4(1)·§5.3.3(5)·NLD-1.2.6), 여기는 그 결과가 깨지지 않게만 한다.
    그래서 `<!주>그림<!/주>:` 처럼 규정이 정한 자리(쌍점 주 밖)는 그대로 지나간다.
    """
    if _TN_OPEN not in text and _TN_CLOSE not in text:
        return text
    depth = 0
    out: list[str] = []
    for ln in text.split("\n"):
        buf: list[str] = []
        for part in _TN_SPLIT_RE.split(ln):
            if part == _TN_OPEN:
                if depth == 0:                  # 중첩은 버린다 — 한 겹만 연다
                    depth = 1
                    buf.append(part)
            elif part == _TN_CLOSE:
                if depth == 1:                  # 짝 없는 닫힘은 버린다
                    depth = 0
                    buf.append(part)
            else:
                buf.append(part)
        out.append("".join(buf))
    if depth == 1:                              # 열린 채로 끝났다 — 마지막 내용 줄에서 닫는다
        for k in range(len(out) - 1, -1, -1):
            if out[k].strip():
                out[k] += _TN_CLOSE
                break
    return "\n".join(out)


def tn_spans_ok(text: str) -> bool:
    """점역자 주 태그가 성한가 — 짝이 맞고 · 중첩이 없고 · 열린 채로 안 끝나는가."""
    depth = 0
    for tok in re.findall(r"<!/?%s>" % re.escape(TN), text):
        depth += 1 if tok == _TN_OPEN else -1
        if depth < 0 or depth > 1:
            return False
    return depth == 0


def apply_indent_tags(text: str, indents: list[int] | None) -> str:
    """(글, 줄별 앞 빈칸) → 줄머리에 태그를 박은 글. 줄 수가 안 맞으면 들여쓰기만 건너뛴다.

    ★ 시각 자료 산출물이 **전부 지나는 한 자리**다(`visual_drafts` 2 · `diagram_opt` 4).
      점역자 주 양식 강제를 여기 두면 호출부마다 막지 않아도 된다.
    """
    text = normalize_tn_spans(text)
    lines = text.split("\n")
    if not indents or len(indents) != len(lines):
        return text
    return "\n".join(indent_tag(n) + ln for n, ln in zip(indents, lines))


def strip_indent_tags(text: str) -> tuple[str, list[int] | None]:
    """태그 박힌 글 → (태그 뗀 글, 줄별 앞 빈칸). 태그가 하나도 없으면 (원문, None)."""
    out: list[str] = []
    indents: list[int] = []
    found = False
    for ln in text.split("\n"):
        n, rest = split_indent(ln)
        if n is None:
            indents.append(0)
        else:
            found = True
            indents.append(n)
        out.append(rest)
    return "\n".join(out), (indents if found else None)


# ── 교열 · 점역 공용 어휘 (이관 1단계, 2026-10-13 · #1364) ─────────────────────────────
# AI 비엔진 모듈(교열 · 파이프라인 · 품질 검사)이 엔진에서 가져오는 어휘는 이 모듈 · `regulations` ·
# `constants` 셋으로 모은다. 아래 셋은 엔진(`table_braille`)과 교열(`table_opt` · `pipeline` ·
# `quality_checker`)이 같이 써서 `table_braille` 에서 옮겼다. 점자가 한 셀도 안 나오는 묵자 규약이다.
# 이관 5단계에서 엔진 사본을 지울 때 이 모듈이 패키지 쪽(`semojum_braille.tags`)으로 간다.

# ── 표 구조 태그 (plan §3-5 확장) ─────────────────────────────────────────────
# table_opt가 stage②(점역 직전 텍스트)에 <!표>/<!행>/<!칸>으로 표 구조를 출력하고,
# `parse_table_tags` 가 행렬로 되돌려 `table_braille` 의 4안 렌더러(풀어쓰기/격자/전치/선형)에 1:1 위임한다.
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


# ── 묵자 초안 표 테두리 표시 ─────────────────────────────────────────────────────
# 엔진 `table_braille.print_layout` 이 그리고, 교열 `table_opt.parse_print_frames`(mode b)가 되읽는다.
_PRINT_BOX_TOP, _PRINT_BOX_BOTTOM, _PRINT_RULE = "┌", "└", "├"


# ── 정답 상자 판정 ────────────────────────────────────────────────────────────────
# 꼴과 근거는 `table_braille` 의 '정답 상자' 절에 있다. 판정은 엔진(테두리만 자리의 정답 상자 꼴)과
# 교열(`table_opt` 렌더 모드 · `pipeline` 정답 띠 되살리기 · `quality_checker` R4)이 같이 쓴다.
_ANS_PAIR_RE = re.compile(r"^(\d{1,2})\s+([①-⑳]|\d{1,4})$")
_ANS_BARE_NO_RE = re.compile(r"^\d{1,2}$")
_ANS_LABEL_MAX = 4        # 쌍 사이 소제목은 넉 자 이하('언어'·'1회'·'02')
_ANS_MIN_PAIRS = 6
_ANS_MIN_PAIRS_PAGED = 1  # 제목에 '본문 87~89쪽' 이 있으면(정답 상자 머리 표지) 한 쌍이면 된다. 사회문화 '기출 플러스' 는 답이 하나 · 둘이고
                          #   gold 도 글상자로 적는다(ans p21 `1 ④  2 ②` · p44 `1 ⑤` · p49 `1 ②`, #1353). 셋에서 내려 판정이 바뀐 표는
                          #   2027 dev · val 표 899개 중 그 띠 5개뿐이다
_ANS_PAGE_REF_RE = re.compile(r"본문\s*\d+(?:\s*~\s*\d+)?\s*쪽")


def answer_box_on() -> bool:
    return os.environ.get("ANSWER_BOX_FORM", "1") != "0"


def answer_box_parts(rows: list[list[str]]):
    """표 격자 → `(제목 줄, [(소제목 줄, [(번호, 답)…])…])`. 정답 상자가 아니면 None.

    · 첫 쌍 앞 칸에 다섯 자 이상 글이 있으면 그 칸들은 상자 위 제목이다(두 자 이하 칸은
      앞 제목에 붙인다: `Level` + `1`). 짧은 칸뿐이면 상자 안 소제목이다.
    · 쌍 사이 짧은 칸은 새 묶음의 소제목이다. 긴 글이 끼면 자료 표다 → None.
    · 한 묶음의 번호는 1에서 시작해 1씩 는다. MinerU 가 두 쌍을 한 칸에 붙이면(`01 405 3`) 여기서
      걸러진다 — 안 거르면 붙은 칸이 제목 줄로 샌다.
    · 쌍이 여섯 개 안 되면 None. 제목에 '본문 N~M쪽' 이 있으면 세 개면 된다(작은 단원 상자).
    """
    cells = [(c or "").strip() for r in rows for c in r]
    cells = [c for c in cells if c]
    first = next((i for i, c in enumerate(cells) if _ANS_PAIR_RE.match(c)), None)
    if first is None:
        return None
    head, rest = cells[:first], cells[first:]
    titles: list[str] = []
    labels: list[str] = []
    if any(len(c) > _ANS_LABEL_MAX for c in head):
        for c in head:
            if titles and len(c) <= 2:
                titles[-1] += " " + c
            else:
                titles.append(c)
    else:
        labels = head
    groups: list[tuple[list[str], list[tuple[str, str]]]] = []
    pairs: list[tuple[str, str]] = []
    for c in rest:
        m = _ANS_PAIR_RE.match(c)
        if m:
            if int(m.group(1)) != (int(pairs[-1][0]) + 1 if pairs else 1):
                return None
            pairs.append((m.group(1), m.group(2)))
            continue
        if len(c) > _ANS_LABEL_MAX:
            return None
        if pairs:
            groups.append((labels, pairs))
            labels, pairs = [], []
        labels.append(c)
    if pairs:
        groups.append((labels, pairs))
    need = _ANS_MIN_PAIRS_PAGED if any(_ANS_PAGE_REF_RE.search(t) for t in titles) else _ANS_MIN_PAIRS
    if sum(len(p) for _, p in groups) < need:
        return None
    return titles, [([f"({x})" if _ANS_BARE_NO_RE.match(x) else f"[{x}]" for x in lb], p)
                    for lb, p in groups]
