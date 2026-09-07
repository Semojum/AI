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
