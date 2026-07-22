"""평문 인라인 수식 탐지 — 구분자 없이 본문에 섞인 수식을 찾아 수식 태그로 감싼다.

**문제**: 수학 교재 본문은 수식을 `$…$` 없이 그대로 쓴다.

    (1) cos 2α=1-2 sin² α에서 sin² α=\\frac{1-\\cos 2\\alpha}{2}이므로

translator의 `_INLINE_MATH_RE`는 `$…$`·`\\(…\\)` 같은 **구분자가 있을 때만** 수식으로
라우팅하므로, 위 문장은 통째로 한글 텍스트로 점역돼 `cos`가 로마자로, `²`가 장식으로
나간다. 정답은 삼각함수 접두(제47항 ⠖⠉)와 위첨자(제18항)로 적는다.
수학2 텍스트 요소 1,932개 중 313개(16%)가 이 경우였다(2026-07-19 실측). 다른 과목은
0~2%라 수학 특유의 문제다.

**왜 별도 모듈인가**: 이건 '번역'이 아니라 '탐지' 책임이다. 어디까지가 수식인지 정하는
일과 그 수식을 점자로 바꾸는 일(kor_math_rules)은 분리돼야 바뀔 때 서로 안 흔든다.
translator는 이 모듈이 태그를 붙인 결과를 받아 기존 수식 경로로 흘려보낸다.

**오탐 방지**(가장 중요): 한글 본문을 수식으로 잘못 잡으면 문장이 통째로 깨진다. 그래서
  · 한글·문장부호를 만나면 즉시 구간을 끊는다.
  · 구간 안에 **강한 수식 신호**(그리스 문자·위첨자·함수 이름·연산자 낀 등식)가 하나라도
    없으면 버린다. 단순 영단어나 숫자 나열은 수식이 아니다.
  · 이미 `<!수식>`으로 감싸인 구간은 건드리지 않는다.
"""
from __future__ import annotations

import re

# 수식 구간을 이룰 수 있는 문자 — 한글이 나오면 여기서 끊긴다.
# `|`(절댓값·조건제시 세로바)를 포함한다: 없으면 |α-β| 같은 구간이 막대에서 끊겨
# 막대만 텍스트 경로로 새고, symbol_table의 텍스트 세로선 ⠸⠳(제71항, 2셀)가 나간다.
# 정답은 제21항 절댓값 ⠳ 1셀 — gold 실측도 ⠳⠈⠁⠔⠈⠃⠳(=|α-β|)로 ⠸⠳는 1131p 0회다.
_ATOM = r"[A-Za-z0-9αβγδεζηθικλμνξπρστυφχψωΑΒΓΔΘΛΞΠΣΦΨΩ" \
        r"⁰¹²³⁴⁵⁶⁷⁸⁹₀₁₂₃₄₅₆₇₈₉+\-=×÷<>≤≥≠±∞√∑∫·^_(){}\[\]/,.'\\| ]"
_SPAN_RE = re.compile(rf"{_ATOM}{{3,}}")

# 강한 수식 신호 — 이게 없으면 수식으로 보지 않는다.
_STRONG = re.compile(
    r"[αβγδεζηθικλμνξπρστυφχψωΑΒΓΔΘΛΞΠΣΦΨΩ]"          # 그리스 문자
    r"|[⁰¹²³⁴⁵⁶⁷⁸⁹₀₁₂₃₄₅₆₇₈₉]"                        # 위·아래 첨자
    r"|(?<![A-Za-z])(?:sin|cos|tan|sec|csc|cot|log|ln|lim)(?![A-Za-z])"
    r"|\\[a-zA-Z]{2,}"                                   # LaTeX 명령
    r"|[√∑∫∞≤≥≠±×÷]"
    r"|[A-Za-z0-9)\]]\s*=\s*[-A-Za-z0-9(\\]"            # 등식(양쪽에 피연산자)
)

# 절댓값 쌍(제21항) — |x|·|f(x)|·|α-β|. 이것만으로도 수식 신호로 친다.
# 오탐 방지 두 겹: (1) 막대 안쪽 가장자리에 공백이 없어야 하고 (2) 안에 문자가 있어야 한다.
# 표 draft의 마크다운 칸 구분자 `| 89.2 |`는 둘 다 어겨서 걸리지 않는다(숫자만·양끝 공백).
_ABS_PAIR_RE = re.compile(
    r"\|[^|가-힣\s](?:[^|가-힣]*[^|가-힣\s])?\|"
)
_LETTER_RE = re.compile(r"[A-Za-zαβγδεζηθικλμνξπρστυφχψωΑΒΓΔΘΛΞΠΣΦΨΩ]")


def _has_strong(core: str) -> bool:
    """구간이 수식인지 — 강한 신호가 하나라도 있으면 참."""
    if _STRONG.search(core):
        return True
    return any(_LETTER_RE.search(m.group()) for m in _ABS_PAIR_RE.finditer(core))
_FUNCS = ("arcsin", "arccos", "arctan", "sinh", "cosh", "tanh",
          "sin", "cos", "tan", "sec", "csc", "cot", "log", "ln", "lim")
_SUP = {"⁰": "0", "¹": "1", "²": "2", "³": "3", "⁴": "4",
        "⁵": "5", "⁶": "6", "⁷": "7", "⁸": "8", "⁹": "9"}
_SUB = {"₀": "0", "₁": "1", "₂": "2", "₃": "3", "₄": "4",
        "₅": "5", "₆": "6", "₇": "7", "₈": "8", "₉": "9"}
_TAGGED_RE = re.compile(r"<!수식>.*?<!/수식>", re.DOTALL)

# 계수분수(1/2x 등)는 인쇄 원문이 세로분수라 gold도 분수형(제7항 1호)으로 적는다.
# 날짜·비율·연도범위(3/4분기·1/4)와·2005/2006)는 뒤에 변수·여는 괄호가 없어 빗금 유지.
_COEF_FRAC_RE = re.compile(r"(?<![\d.)])(\d+)/(\d+)(?=[A-Za-z(])")


def normalize(span: str) -> str:
    r"""평문 수식 표기를 kor_math_rules가 아는 LaTeX으로 맞춘다.

    함수 이름은 명령으로(cos → \cos), 유니코드 첨자는 ^{}·_{}로 바꾼다. 그리스 문자는
    유니코드 그대로 둔다 — convert_latex이 substitute_symbols로 처리한다.
    """
    s = span
    for f in _FUNCS:                      # 긴 이름부터(arcsin이 sin보다 먼저)
        s = re.sub(rf"(?<![A-Za-z\\]){f}(?![A-Za-z])", rf"\\{f}", s)
    s = re.sub(f"[{''.join(_SUP)}]+", lambda m: "^{" + "".join(_SUP[c] for c in m.group()) + "}", s)
    s = re.sub(f"[{''.join(_SUB)}]+", lambda m: "_{" + "".join(_SUB[c] for c in m.group()) + "}", s)
    s = _COEF_FRAC_RE.sub(r"\\frac{\1}{\2}", s)
    return s


# 구간 앞에 붙은 문항·선택지 번호는 수식이 아니다 — 떼어내고 원문에 남긴다.
# 홑따옴표 없는 `.`·`,`도 뗀다: 자모 문항표 "ㄱ. |f(x)|"의 마침표는 표지의 일부라
# 수식에 딸려 들어가면 자모 표지 규칙(ㄱ.→⠿⠁)의 뒤보기가 깨져 `.`가 그대로 남는다.
_ENUM_HEAD_RE = re.compile(r"^(\(\s*\d+\s*\)|\d+\s*[.)]|[①-⑳]|[.,])\s*")


def _wrap_segment(seg: str) -> str:
    def repl(m: re.Match) -> str:
        span = m.group()
        core = span.strip()
        head = ""
        em = _ENUM_HEAD_RE.match(core)
        if em:
            head, core = em.group(), core[em.end():]
        if len(core) < 3 or not _has_strong(core):
            return span
        lead = span[:len(span) - len(span.lstrip())]
        trail = span[len(span.rstrip()):]
        return f"{lead}{head}<!수식>{normalize(core)}<!/수식>{trail}"

    return _SPAN_RE.sub(repl, seg)


def wrap(text: str) -> str:
    """본문 문자열 → 평문 수식 구간을 `<!수식>…<!/수식>`로 감싼 문자열.

    이미 태그가 붙은 구간은 그대로 통과시킨다(이중 감쌈 방지).
    """
    if not text or "<!수식>" not in text and not _SPAN_RE.search(text):
        return text
    out: list[str] = []
    last = 0
    for m in _TAGGED_RE.finditer(text):
        out.append(_wrap_segment(text[last:m.start()]))
        out.append(m.group())
        last = m.end()
    out.append(_wrap_segment(text[last:]))
    return "".join(out)
