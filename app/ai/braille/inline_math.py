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

from app.ai.braille.constants import WRAP_HYPHEN_CLOSE, WRAP_HYPHEN_OPEN
from app.ai.braille.kor_math_rules import UNI_SUB, UNI_SUP, unicode_scripts_to_latex

# 캡셔닝 LLM이 쓰는 유니코드 수학 표기(QA 10번, 2026-08-08). 아래 _ATOM·_STRONG에
# 넣어야 `Ca²⁺`·`aₙ₊₁`·`f′(x)`·`2ˣ`가 **한 구간**으로 잡힌다. 안 넣으면 구간이 그
# 글자에서 끊겨 뒷조각이 한글 텍스트 경로로 새고, 그 이음매에 빈칸이 하나 더 생긴다
# (두 칸 = 항목 구분 부호라 점역사가 오독) — 또는 앞에 로마자표 ⠴가 붙는다.
# 실측(현실적 표기 14개, 유니코드형 vs LaTeX형 점형 대조): 다름 10 → 6.
# ⚠ 화살표 →는 **일부러 뺐다**. 캡셔닝 프롬프트가 흐름을 →로 적으라고 지시하므로
#   ('Client → 서버: 요청') 수식으로 삼키면 본문 개조식이 깨진다.
# ⚠ ∽도 뺐다 — 점역자 주 마커(⠠⠄)와 자형이 겹쳐 오인 위험이 있다.
# ⚠ △도 뺐다 — 제57항 숨김표다(△△도서관 = ⠸⠬⠬⠇). 수식 삼각형으로 보면 숨김표가
#   깨진다(test_hidden_marks_reg57). ○☆◇◆도 같은 이유로 애초에 넣지 않는다.
_UNI_SCRIPTS = "".join(UNI_SUP) + "".join(UNI_SUB)
# ⚠ °도 뺐다 — dev-2027 실측 80건이 각도가 아니라 **깨진 아래첨자 ₅**다
#   (생물 `d°`=d₅ · `A°`=A₅. 교재 폰트가 첨자를 U+00B0에 매핑했다).
#   수식 신호로 삼으면 그 80건이 도(⠴⠙)로 나간다.
# ⚠ ∴·∵도 뺐다 — 국어 문장 안에서 접속어로 쓰인다("개체 수 증가(∵ 많은 영양염류)").
_UNI_RELATIONS = "∈∉⊂⊃⊆⊇∪∩∠⊥∥≡≈∝′″"

# 수식 구간을 이룰 수 있는 문자 — 한글이 나오면 여기서 끊긴다.
# `|`(절댓값·조건제시 세로바)를 포함한다: 없으면 |α-β| 같은 구간이 막대에서 끊겨
# 막대만 텍스트 경로로 새고, symbol_table의 텍스트 세로선 ⠸⠳(제71항, 2셀)가 나간다.
# 정답은 제21항 절댓값 ⠳ 1셀 — gold 실측도 ⠳⠈⠁⠔⠈⠃⠳(=|α-β|)로 ⠸⠳는 1131p 0회다.
# ★ 감쌈 붙임표 자리표시자(WRAP_HYPHEN_*)는 하이픈의 대역이라 하이픈과 같이 원자로 친다.
#   빼면 "x(x-a)(x-1)²<0"처럼 감쌈이 낀 수식 구간이 표식에서 쪼개져 라우팅이 달라진다.
_ATOM = (r"[A-Za-z0-9αβγδεζηθικλμνξπρστυφχψωΑΒΓΔΘΛΞΠΣΦΨΩ"
         r"+\-=×÷<>≤≥≠±∞√∑∫·^_(){}\[\]/,.'\\| "
         + _UNI_SCRIPTS + _UNI_RELATIONS
         + WRAP_HYPHEN_OPEN + WRAP_HYPHEN_CLOSE + "]")
_SPAN_RE = re.compile(rf"{_ATOM}{{2,}}")
_ATOM_RE = re.compile(_ATOM)   # 낱글자 판정용(_latex_start)
# 아래첨자를 지닌 2자 토큰(O₂·t₂ 등 원소·변수)도 수식으로 잡기 위한 신호.
# 3자 임계는 유지하되 아래첨자만 예외로 2자를 허용한다 — 아래첨자 유니코드는 한글
# 본문에 안 나오고(코퍼스 실측 0건, r15) 깨진 글리프 정화 후에만 생기므로 오탐이 없다.
# 없으면 짧은 O₂·t₂가 라우팅을 못 타 규정형 ⠰⠼(gold 0회)로 나가 되레 어긋난다(r16 생물 p073).
_SUB_CHARS = re.compile(f"[{''.join(UNI_SUB)}]")
# 이온 전하를 지닌 2자 토큰(H⁺·K⁺)도 같은 이유로 예외다. 라우팅을 못 타면 텍스트
# 경로가 로마자 종료표를 끼워 ⠠⠓⠲⠘⠢를 내는데, 과학점자 제2항 붙임은 '이온 표시
# 뒤에는 로마자 종료표 없이 한 칸 띄어 쓴다'이다(H+ = ,h^5).
_ION_CHARS = re.compile("[⁺⁻]")

# 강한 수식 신호 — 이게 없으면 수식으로 보지 않는다.
_STRONG = re.compile(
    r"[αβγδεζηθικλμνξπρστυφχψωΑΒΓΔΘΛΞΠΣΦΨΩ]"          # 그리스 문자
    f"|[{_UNI_SCRIPTS}]"                                 # 위·아래 첨자
    r"|(?<![A-Za-z])(?:sin|cos|tan|sec|csc|cot|log|ln|lim)(?![A-Za-z])"
    r"|\\[a-zA-Z]{2,}"                                   # LaTeX 명령
    f"|[√∑∫∞≤≥≠±×÷{_UNI_RELATIONS}]"
    # 등식(양쪽에 피연산자) — 오른쪽 피연산자 집합에 감쌈 자리표시자도 넣는다(하이픈 대역)
    r"|[A-Za-z0-9)\]]\s*=\s*[-A-Za-z0-9(\\" + WRAP_HYPHEN_OPEN + WRAP_HYPHEN_CLOSE + r"]"
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
    s = unicode_scripts_to_latex(s).replace("′", "'").replace("″", "''")
    s = _COEF_FRAC_RE.sub(r"\\frac{\1}{\2}", s)
    return s


# 구간 앞에 붙은 문항·선택지 번호는 수식이 아니다 — 떼어내고 원문에 남긴다.
# 홑따옴표 없는 `.`·`,`도 뗀다: 자모 문항표 "ㄱ. |f(x)|"의 마침표는 표지의 일부라
# 수식에 딸려 들어가면 자모 표지 규칙(ㄱ.→⠿⠁)의 뒤보기가 깨져 `.`가 그대로 남는다.
_ENUM_HEAD_RE = re.compile(r"^(\(\s*\d+\s*\)|\d+\s*[.)]|[①-⑳]|[.,])\s*")


# ★ `\text{한글}` 이 든 LaTeX 은 **통째로 한 구간**이다(2026-09-03).
#   _ATOM 에 한글이 없어서 `\text{득표율}` 이 `\text{` 와 `득표율}` 로 갈렸고,
#   그 결과 수식이 조각나 `\%` · 닫는 중괄호가 그대로 점역되고 `\times` 가 한글 약자
#   '연'으로 나갔다(실측: `득표율} (\%  concc  득표수  유효 투표수  연100`).
#   LaTeX 명령이 든 식은 여기서 먼저 통째로 잡아 쪼개지지 않게 한다.
# ★ 2026-09-07 — 명령 **이름표는 못 쓴다**(원장 R-71). 종전에는 열다섯 개만 적어 뒀는데
#   코퍼스 1,361쪽의 LaTeX 명령 32,224회를 세니 그 밖의 이름이 절반이다
#   (\to 1,460 · \overline 1,234 · \cdots 1,033 · \left/\right 각 1,032 · \pi 867 …).
#   이름표에 없는 명령이 식 **앞머리**에 있으면 구간이 그 뒤에서 시작해, 앞머리가
#   로마자로 점역돼 나간다 — `\overline{\mathrm{PI}}=…` 가 `⠸⠡⠴⠕⠧⠻⠇⠔⠑⠦⠂`(="\overline{"
#   열 셀)로 샜다. 신호는 `_STRONG` 이 이미 쓰는 것으로 통일한다(`\[a-zA-Z]{2,}`).
_LATEX_CMD_RE = re.compile(r"\\[a-zA-Z]{2,}")
_HANGUL = re.compile(r"[가-힣ㄱ-ㅎㅏ-ㅣ]")


def _latex_end(s: str, i: int) -> int:
    r"""LaTeX 식이 끝나는 자리. **중괄호 깊이 0에서** 한글·줄바꿈·두 칸을 만나면 끊는다.

    ★ 깊이를 세는 이유 — `\text{득표율}` 처럼 **중괄호 안 한글은 식의 일부**라 끊으면
      안 된다(2026-09-03 주석 참조). 반대로 깊이 0의 한글은 본문이다: 이름표를 넓히면서
      줄 끝까지 삼키게 두면 `\overline{AB}의 길이는` 의 조사 '의' 까지 수식이 먹어
      `̅ABW 길이는` 이 된다(실측). 종전 정규식은 열다섯 개 이름에서만 이 손해를 냈다.
    """
    depth = 0
    while i < len(s):
        ch = s[i]
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth = max(0, depth - 1)
        elif ch == "\n":
            break
        elif depth == 0:
            if _HANGUL.match(ch) or s.startswith("  ", i):
                break
        i += 1
    return i


def _latex_start(s: str, i: int) -> int:
    r"""식의 **앞머리**. 명령 앞에 붙은 수식 원자까지 거슬러 올라간다.

    ★ 명령 자리에서 곧장 열면 식이 두 동강 난다 — `{}_{n}C_{0},\ … ,\ \cdots` 는
      강한 신호가 `\cdots` 하나뿐이라, 거기서부터만 감싸면 앞의 조합 기호가 토큰
      규칙의 강한 신호를 잃어 원문 그대로 나간다(확률과 통계 p0020 실측).
      뒤(`_latex_end`)와 같은 잣대로 앞도 잡는다: 깊이 0의 한글·두 칸에서 멈춘다.
    """
    depth = 0
    while i > 0:
        ch = s[i - 1]
        if ch == "}":
            depth += 1
        elif ch == "{":
            depth = max(0, depth - 1)
        elif depth == 0:
            if ch == "\n" or _HANGUL.match(ch) or not _ATOM_RE.match(ch):
                break
            if s.startswith("  ", i - 2):
                break
        i -= 1
    return i


def _wrap_latex_spans(seg: str) -> str:
    """LaTeX 명령이 든 구간을 통째로 감싼다. 못 잡으면 아래 토큰 규칙이 이어받는다."""
    out: list[str] = []
    i = 0
    for m in _LATEX_CMD_RE.finditer(seg):
        if m.start() < i:                      # 앞 구간이 이미 먹은 자리
            continue
        start = max(i, _latex_start(seg, m.start()))
        end = _latex_end(seg, m.start())
        core = seg[start:end].strip()
        out.append(seg[i:start])
        if not core or "<!수식>" in core:
            out.append(seg[start:end])
        else:
            out.append(f"<!수식>{normalize(core)}<!/수식>")
        i = end
    out.append(seg[i:])
    return "".join(out)


def _wrap_segment(seg: str) -> str:
    # LaTeX 명령이 보이면 그쪽을 먼저 통째로 잡는다 — 한글에서 안 끊긴다.
    if "\\" in seg or "\\text" in seg:
        wrapped = _wrap_latex_spans(seg)
        if "<!수식>" in wrapped:
            # ★ 감싸고 **남은 자리도 토큰 규칙에 넘긴다**(2026-09-07, 원장 R-71).
            #   종전에는 여기서 곧장 돌려줘, 명령보다 **앞에 놓인 식**이 토큰 규칙을
            #   못 타고 통째로 원문으로 샜다 — `{}_{n}C_{0}, … , \cdots` 에서
            #   `\cdots` 부터만 감싸이고 앞의 조합 기호가 `{}_{n}나_{0}` 로 나갔다
            #   (확률과 통계 p0020 실측). 이름표가 좁던 때에는 `_wrap_latex_spans`
            #   자체가 아무것도 못 잡아 전부 토큰 규칙으로 갔기에 안 보이던 자리다.
            out: list[str] = []
            last = 0
            for m in _TAGGED_RE.finditer(wrapped):
                out.append(_wrap_tokens(wrapped[last:m.start()]))
                out.append(m.group())
                last = m.end()
            out.append(_wrap_tokens(wrapped[last:]))
            return "".join(out)
    return _wrap_tokens(seg)


def _wrap_tokens(seg: str) -> str:
    """구분자 없는 수식 토큰을 감싼다(강한 신호가 있을 때만)."""

    def repl(m: re.Match) -> str:
        span = m.group()
        core = span.strip()
        head = ""
        em = _ENUM_HEAD_RE.match(core)
        if em:
            head, core = em.group(), core[em.end():]
        if not _has_strong(core):
            return span
        # 2자 토큰은 아래첨자·이온 전하를 지닌 것만 허용(O₂·t₂·H⁺). 그 밖은 3자 임계 유지.
        if len(core) < 3 and not (_SUB_CHARS.search(core) or _ION_CHARS.search(core)):
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
