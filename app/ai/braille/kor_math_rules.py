"""KOR_MATH 수식 점자 규칙 엔진.

한국 점자 규정 2017 개정 기준 LaTeX → 점자 BRF 변환.

C5-critical: _DIGIT_MAP 오류 시 단위 테스트에서 즉시 차단.
"""

from __future__ import annotations

import os
import re

from app.ai.braille.symbol_rules import substitute_symbols

# ── C5-critical: 숫자 점자 매핑 ─────────────────────────────────────────
_NUMBER_INDICATOR = "⠼"  # 수표시 (dots 3,4,5,6) — 숫자 앞에 반드시 삽입
_DIGIT_MAP: dict[str, str] = {
    "0": "⠚",  # dots 2,4,5
    "1": "⠁",  # dot 1
    "2": "⠃",  # dots 1,2
    "3": "⠉",  # dots 1,4
    "4": "⠙",  # dots 1,4,5
    "5": "⠑",  # dots 1,5
    "6": "⠋",  # dots 1,2,4
    "7": "⠛",  # dots 1,2,4,5
    "8": "⠓",  # dots 1,2,5
    "9": "⠊",  # dots 2,4
}

# ── 수학 구조 기호 ─────────────────────────────────────────────────────────
# 수학 점자 제7항: 분수는 분모+분수표+분자 순서, 분수표(/)=⠌
_FRACTION_MID    = "⠌"  # / (dots 3,4)
# 수학 점자 제18항: 위첨자 기호 ^ = ⠘ (dots 4,5)
_SUPERSCRIPT_IND = "⠘"
# 수학 점자 제19항/한글 제68항: 아래첨자 기호 ; = ⠰ (dots 5,6). 규정 폰트 ";" 디코드
_SUBSCRIPT_IND   = "⠰"
# 수학 점자 제22항: 근호 > = ⠜ (dots 3,4,5)
_SQRT_IND        = "⠜"
# 수학 점자 제22항 붙임1: 세제곱근 이상 근수 기호 ] = ⠻ (dots 1,2,4,5,6)
_SQRT_N_IND      = "⠻"

# ── 수학 괄호 (수학 점자 제6항 소괄호 8`0) ──────────────────────────────
# 수학 소괄호 = ⠦…⠴ (수학 규정 제6항 1: 소괄호 8`0). 정답 도서도 동일(수학2 p009 실측).
# ⚠ ⠷⠾가 아니다 — 그건 같은 조항 2의 '묶음 괄호'(점자에서만 쓰는 단항 곱·다항 묶음)로,
#   2026-07-17까지 소괄호로 잘못 쓰여 수식 무수정률을 깎았다(숫자 자간과 함께 1.1%의 원인).
_MATH_PAREN_S = "⠦"  # ( 여는 소괄호 (수학 제6항)
_MATH_PAREN_E = "⠴"  # ) 닫는 소괄호

# 점역자 삽입 묶음(제6항 2호 ⠷⠾): 규정 예시는 ⠷⠾(제7항3·18항붙임·22항붙임2)이나
# 정답 도서는 **⠶…⠶**로 적는다 — 우리가 묶음을 넣은 자리에서 gold가 ⠶인 경우 53건
# (정렬 opcode 실측 2026-07-19). ⚠ 같은 날 오전엔 ⠦⠴로 판정했는데, 그때는 후보에서
# ⠶를 빼고 ⠦ 93 : ⠷ 2로만 세는 오류였다(수식 구간 재측정: 근호 뒤 ⠦ 9 : ⠶ 8로 팽팽,
# 삽입 위치 대조에서는 ⠶ 우세). **인쇄 소괄호는 ⠦⠴ 그대로** — 삽입 묶음만 ⠶다.
# → book 모드는 ⠶⠶, regulation 모드는 규정 원형 ⠷⠾.
_BOOK_STYLE_ENV = os.environ.get("BRAILLE_STYLE", "book") != "regulation"
# ∴ 관행: 규정 제65항 2호는 ,*(⠠⠡)이나 정답 도서는 ⠌⠄만 쓴다(gold 86회 vs 규정형 0회,
# 2026-07-19 실측). ∵(⠈⠌)은 gold 용례가 없어 규정형 유지.
_THEREFORE = "⠌⠄" if _BOOK_STYLE_ENV else "⠠⠡"
_WRAP_S = "⠶" if _BOOK_STYLE_ENV else "⠷"
_WRAP_E = "⠶" if _BOOK_STYLE_ENV else "⠾"

# ── 삼각함수 (수학 점자 제47항): 접두 6(⠖) + 접미 ─────────────────
# ⚠ 접두는 ⠖(ASCII "6")다. 규정 제47항 예시가 sin=6S·cos=6c·tan=6t로 명시
#   (규정_텍스트.txt 3855~3868행). 구 코드는 ⠋(ASCII "f")로 오기돼 있었다 —
#   gold·규정·ASCII 매핑 3자 모두 ⠖로 일치 확인(2026-07-18).
_TRIG: dict[str, str] = {
    "arcsin":  "⠁⠗⠉⠖⠎",   # arc6s  (역함수는 arc 접두)
    "arccos":  "⠁⠗⠉⠖⠉",   # arc6c
    "arctan":  "⠁⠗⠉⠖⠞",   # arc6t
    "arccsc":  "⠁⠗⠉⠖⠣",   # arc6<
    "arcsec":  "⠁⠗⠉⠖⠤",   # arc6-
    "arccot":  "⠁⠗⠉⠖⠳",   # arc6\
    "sinh":    "⠖⠎⠓",      # 6sh
    "cosh":    "⠖⠉⠓",      # 6ch
    "tanh":    "⠖⠞⠓",      # 6th
    "csch":    "⠖⠣⠓",      # 6<h
    "sech":    "⠖⠤⠓",      # 6-h
    "coth":    "⠖⠳⠓",      # 6\h
    "sin":     "⠖⠎",       # 6s
    "cos":     "⠖⠉",       # 6c
    "tan":     "⠖⠞",       # 6t
    "csc":     "⠖⠣",       # 6<
    "sec":     "⠖⠤",       # 6-
    "cot":     "⠖⠳",       # 6\
}

# ── 로그 (수학 점자 제46항): _ (⠸, dots 4,5,6) ────────────────────────
# log 기호 = _ = ⠸
# 밑이 숫자: _, + 수표 없이 숫자 (예: log₂ = _,2 = ⠸⠠⠃)
# 밑이 변수: _; + 문자 (예: log_a = _;a = ⠸⠰⠁)
# ln = log_e = _;e = ⠸⠰⠑
_LOG_IND     = "⠸"   # _ (dots 4,5,6) — log 기호
_LOG_NUM_SEP = "⠠"   # , (dot 6) — 밑이 숫자일 때 구분자 (붙임: 수표 없이)
# ln 표기 정정(2026-07-19): 규정 3832행 예시 `LNx33_;Ex`(ln x = log_e x) — 묵자가
# 'ln'이면 **문자 그대로**(⠇⠝), log_e 표기일 때만 _;e. \ln의 무조건 _;e 변환은 과변환
# (gold 13건 실측 — gold도 ln 문자). 로마자 소문자 ln = ⠇⠝.
_LN_BRAILLE  = "⠇⠝"  # ln (문자 그대로, 규정 3832 예시 좌변)

# ── 극한 (수학 점자 제51항): lim;변수 ` → ` 점근값 ` ` 함수 ─────────────
_LIM_BRAILLE  = "⠇⠊⠍"  # lim (l=⠇, i=⠊, m=⠍)
_ARROW_RIGHT  = "⠒⠕"   # → (3o=⠒⠕, 수학 제10항/제38항 반직선)

# ── 절댓값 (수학 점자 제21항): \ \ ─────────────────────────────────────
_ABS_IND = "⠳"  # \ (dots 1,2,5,6) — 절댓값 기호

# ── 정적분 범위 / 합 범위 구분자 ─────────────────────────────────────────
_RANGE_SEP = "⠰"   # ; = ⠰ — 범위 시작 (아래첨자 기호와 동일 셀, 규정 폰트 ";")


# ── 정규식 ────────────────────────────────────────────────────────────────
# 분수: \frac{분자}{분모}  (단순 비중첩)
_FRAC_RE   = re.compile(r"\\frac\{([^{}]*)\}\{([^{}]*)\}")
# n제곱근: \sqrt[n]{내용}
_SQRT_N_RE = re.compile(r"\\sqrt\[([^\]]*)\]\{([^{}]*)\}")
# 제곱근: \sqrt{내용}
_SQRT_RE   = re.compile(r"\\sqrt\{([^{}]*)\}")
# 위첨자: base^{exp} 또는 base^x (단일 문자/숫자)
# 둘째 대안 base에 점자 셀 포함(2026-07-19): \sin^2x는 삼각 치환 후 base가 ⠎라
# ASCII만 매칭하던 구판에서 '^'가 기호 캐럿(⠈⠑)으로 오치환됐다(규정 3880행 `6s^#bx` 위반).
_SUP_RE    = re.compile(r"([A-Za-z0-9⠁-⠿])\^\{([^{}]*)\}|([A-Za-z0-9⠁-⠿])\^([A-Za-z0-9])")
# 아래첨자: base_{sub} 또는 base_x
_SUB_RE    = re.compile(r"([A-Za-z0-9⠁-⠿])_\{([^{}]*)\}|([A-Za-z0-9])_([A-Za-z0-9])")
# 숫자 (음수 포함, 소수 포함). 쉼표는 **3자리 자릿점만** 수 내부로 본다(제41항 "자릿점").
# {2,4,6} 같은 나열 쉼표를 자릿점 ⠂로 삼키던 버그 정정(2026-07-19, 규정 집합 예시
# ,a337#b"#d"#f7 — 나열 쉼표는 문장부호 ⠐·다음 수에 수표 재삽입).
_NUM_RE    = re.compile(r"-?\d+(?:,\d{3})*(?:\.\d+)?")
# \to 또는 \rightarrow
_TO_RE     = re.compile(r"\\(?:to|rightarrow)")
# \lim_{var \to val} 또는 \lim_{var→val}
_LIM_RE    = re.compile(
    r"\\lim_\{([^{}]*?)(?:\\to|→|\\rightarrow)(.*?)\}",
    re.DOTALL,
)
# \log_{base} 또는 \log_{base}(arg) — 괄호 진수는 제46항 [붙임2]·[다만] 분기용으로 캡처.
# 이 단계 시점엔 소괄호가 이미 ⠦…⠴로 바뀌어 있다(변환 1단계) — 점자 괄호로 매칭.
_LOG_BASE_RE = re.compile(r"\\log_\{([^{}]*)\}")
_LOG_BASE_FULL_RE = re.compile(r"\\log_\{([^{}]*)\}(?:\s*⠦([^⠦⠴]*)⠴)?")
# \log_base (단일 문자/숫자)
_LOG_BASE1_RE = re.compile(r"\\log_([A-Za-z0-9])")
# \abs{x} 또는 \left| ... \right|
_ABS_RE    = re.compile(r"\\abs\{([^{}]*)\}|\\left\|([^|]*?)\\right\|")
# \sum_{lower}^{upper} 또는 \sum_{lower}
_SUM_RE    = re.compile(r"\\sum_\{([^{}]*)\}(?:\^\{([^{}]*)\})?")

# ── 문자 위 기호(제23·35~38·64·65항): prefix형(선분·호·벡터)과 postfix형(바·햇·점) ──
# \vec·\overrightarrow = 반직선/벡터 3O(⠒⠕, 제38항), \overleftrightarrow = 직선 [3O(제37항),
# \overparen·\overarc·\wideparen = 호 @[(⠈⠪, 제36항) — 모두 본문 앞에 적는다.
_ACC_PREFIX_RE = re.compile(
    r"\\(vec|overrightarrow|overleftrightarrow|overparen|overarc|wideparen)"
    r"\s*\{([^{}]*)\}|\\vec\s*([A-Za-z])")
_ACC_PREFIX_MARK = {"vec": "⠒⠕", "overrightarrow": "⠒⠕",
                    "overleftrightarrow": "⠪⠒⠕",
                    "overparen": "⠈⠪", "overarc": "⠈⠪", "wideparen": "⠈⠪"}
# postfix형: 가로바 @c(⠈⠉, 제23항 켤레·평균 — 단 내용이 연속 대문자면 선분 제35항 → prefix),
# 햇 @@5(⠈⠈⠢, 제64항), 점 @4(⠈⠲)·겹점 @44·물결 @@9(제65항 5호)
_ACC_POSTFIX_RE = re.compile(
    r"\\(bar|overline|hat|widehat|dot|ddot|tilde|widetilde)\s*\{([^{}]*)\}"
    r"|\\(bar|hat|dot|ddot|tilde)\s*([A-Za-z])")
_ACC_POSTFIX_MARK = {"bar": "⠈⠉", "overline": "⠈⠉", "hat": "⠈⠈⠢", "widehat": "⠈⠈⠢",
                     "dot": "⠈⠲", "ddot": "⠈⠲⠲", "tilde": "⠈⠈⠔", "widetilde": "⠈⠈⠔"}
_CAPS_RUN_RE = re.compile(r"^[A-Z](?:['′⠤]?[A-Z])+['′⠤]?$")

# ── 순열·조합(제62항): nPr = ,P(N R) — P·C·H·중복순열 ,.P. 묶음은 _WRAP(관행/규정 분기) ──
# 선행 문자 가드: P₁P₂(점 이름 아래첨자 곱)를 순열로 오인하지 않게, 왼쪽 첨자는
# 식 머리(공백·연산자 뒤)나 {} 뒤에서만 인정한다.
_PERM_RE = re.compile(
    r"(?<![A-Za-z0-9⠁-⠿}])(?:\{\})?_(\{[^{}]*\}|[A-Za-z0-9])\s*"
    r"(?:([PCH])|\\Pi(?![a-zA-Z])|(Π))\s*"
    r"_(\{(?:[^{}]|\{[^{}]*\})*\}|[A-Za-z0-9])")
# ── 왼쪽 첨자(제18·19항 2호): {}^{t}A → ^(t)A — 첨자는 항상 묶음 괄호 ──
_LEFT_SUP_RE = re.compile(r"\{\}\^(\{[^{}]*\}|[A-Za-z0-9])\s*([A-Za-z])")
_LEFT_SUB_RE = re.compile(r"\{\}_(\{[^{}]*\}|[A-Za-z0-9])\s*([A-Za-z])")
# ── 정적분(제57항): ∫;아래끝`위끝`본식 — 위끝은 위첨자 ⠘가 아니라 칸 구분 ──
# 한계는 \frac{π}{2} 같은 1중첩 중괄호 허용
_BRACE1 = r"\{(?:[^{}]|\{[^{}]*\})*\}"
_INT_RANGE_RE = re.compile(
    rf"([∫∬∮])_({_BRACE1}|[A-Za-z0-9])(?:\^({_BRACE1}|[A-Za-z0-9]))?")
_INT_BASE = {"∫": "⠮", "∬": "⠮⠮", "∮": "⠾"}
# 대괄호 정적분 값 [F(x)]_a^b (제57항): 닫는 대괄호(⠠⠾) 뒤 범위도 같은 형식
_BRACKET_RANGE_RE = re.compile(
    rf"(⠠⠾)_({_BRACE1}|[A-Za-z0-9])(?:\^({_BRACE1}|[A-Za-z0-9]))?")
# 구조 공백 sentinel: 제51·57항 범위 구분 칸이 연산 붙임(11e)에 지워지지 않게 보호
_SP = "\x1f"


def _unbrace(s: str) -> str:
    """바깥 중괄호 한 겹만 제거({\\frac{a}{b}} → \\frac{a}{b}). strip('{}')은 파손."""
    s = s.strip()
    return s[1:-1] if s.startswith("{") and s.endswith("}") else s
# ── 삼각함수 인수 묶음(제47항 [붙임]): 각이 곱·다항·분수면 묶는다(6s(#cx)) ──
_TRIG_ARG_RE = re.compile(
    r"(\\(?:arc)?(?:sin|cos|tan|sec|csc|cot)h?)"
    r"(\^(?:\{[^{}]*\}|[0-9A-Za-z]))?\s*"
    r"(\d+[A-Za-z][A-Za-z0-9]*|\d+\\[a-zA-Z]+|[A-Za-z]{2,}[A-Za-z0-9]*"
    r"|\\frac\{[^{}]*\}\{[^{}]*\})")


def digits_to_braille(num_str: str) -> str:
    """숫자 문자열 → 수표시 + 점자 (C5-critical)."""
    result = [_NUMBER_INDICATOR]
    for ch in num_str:
        if ch in _DIGIT_MAP:
            result.append(_DIGIT_MAP[ch])
        elif ch == ".":
            result.append("⠲")   # 소수점 (제43항/수학 제8항: dots 2,5,6)
        elif ch == ",":
            result.append("⠂")   # 자릿점 (제41항: dot 2)
        elif ch == "-":
            result.append("⠤")   # 음수 부호 (수학 제17항 - = ⠤)
        else:
            result.append(ch)
    return "".join(result)


# 내린 숫자(한 단 내려 적기): 수학 제46항 로그 밑 "수표 없이 내려 적는다".
# 규정 BRF 실측 `_,5#b`(log₅2)의 밑 5=⠢ 확인(2026-07-19) — 일반 숫자 셀이 아니라 하단 셀.
_DROPPED_DIGIT: dict[str, str] = {
    "1": "⠂", "2": "⠆", "3": "⠒", "4": "⠲", "5": "⠢",
    "6": "⠖", "7": "⠶", "8": "⠦", "9": "⠔", "0": "⠴",
}


def _digit_no_indicator(ch: str) -> str:
    """수표 없이 **내린** 단일 숫자 (log 밑 전용, 수학 제46항).

    ⚠ 구현이 일반 숫자 셀(⠃)을 내던 버그 정정 — 규정 '내려 적는다'는 하단 셀(2=⠆)."""
    return _DROPPED_DIGIT.get(ch, ch)


# MinerU/마크다운 입력 정규화용 패턴 ─────────────────────────────────────
_CODE_FENCE_RE = re.compile(r"```[a-zA-Z]*\n?|```")        # ```latex … ``` 펜스
_MATH_DELIM_RE = re.compile(r"\${1,2}")                    # $$ … $$ / $ … $
_CMD_BRACE_SP_RE = re.compile(r"(\\[a-zA-Z]+)\s+(?=[{[(])")  # \frac { → \frac{
# 첨자 _ ^ 양쪽 공백 제거: a _ {i} → a_{i}, } ^{∞} → }^{∞} (첨자가 본체에 붙도록)
_SUBSUP_SP_RE = re.compile(r"\s*([_^])\s*")
_MULTISPACE_RE = re.compile(r" {2,}")                       # 다중 공백 → 단일
_BRACE_IN_SP_RE = re.compile(r"\{\s+")                      # { x → {x
_BRACE_OUT_SP_RE = re.compile(r"\s+\}")                     # x } → x}
# \left( \right) 류 — 구분자만 남기고 \left·\right 제거(단, \left| … \right| 절댓값은 보존)
_LEFTRIGHT_RE = re.compile(r"\\(?:left|right)\s*(?=[()\[\].])")
# 간격 명령(\quad \, \; \! \:) → 공백
_SPACING_CMD_RE = re.compile(r"\\(?:quad|qquad|[,;:!])")
# 서식 래퍼: \boxed{…}·\mathrm{…} 등 → 내용만 남김(수식 식별자 보존). \text는 별도(P2 한글 점역).
_TEXT_WRAP_RE = re.compile(
    r"\\(?:boxed|fbox|mbox|mathrm|mathbf|mathit|mathbb|mathcal|mathsf|operatorname)\s*\{([^{}]*)\}"
)
# \text·\textbf 등 자연어 래퍼 → 내용을 한글 점자 훅으로 변환(P2). 미등록 시 내용 보존.
_TEXT_CMD_RE = re.compile(r"\\text(?:rm|bf|it|sf|tt|normal|md)?\s*\{([^{}]*)\}")
# 식 번호 \tag{N} → (N), 배열 환경 \begin{array}{l}…\end{array} → 제거(행 \\는 공백)
_TAG_CMD_RE = re.compile(r"\\tag\s*\*?\s*\{([^{}]*)\}")
_ENV_RE = re.compile(r"\\(?:begin|end)\s*\{[^{}]*\}(?:\s*\[[^\]]*\])?(?:\s*\{[^{}]*\})?")
# 연립식 괄호(수학 규정 제6항): 여는 ⠶⠄(7')·닫는 ⠠⠶(,7). \left\{ 동반 array 또는 cases.
_SYS_OPEN, _SYS_CLOSE = "⠶⠄", "⠠⠶"
# 관행 스위치 — translator._BOOK_STYLE과 같은 판정을 env에서 직접 읽는다(순환 import 회피).
_IS_BOOK_STYLE = os.environ.get("BRAILLE_STYLE", "book") != "regulation"
_SYS_ENV_RE = re.compile(
    r"\\left\s*\\?\{\s*\\begin\{array\}(?:\{[^{}]*\})?(.*?)\\end\{array\}(?:\s*\\right\s*\.?)?"
    r"|\\begin\{cases\}(.*?)\\end\{cases\}", re.DOTALL)

# \text{한글} 점역용 훅(translator가 런타임 주입 — 순환 import 회피).
_text_hook = None


def register_text_hook(fn) -> None:
    r"""\text{…} 내부 자연어(한글·영문)를 점자로 바꾸는 함수를 주입한다(translator가 호출).

    convert_latex는 수식 변환기라 한글을 점역할 수 없으므로, 한글 점역은 translator가
    맡는다. import 순환을 피하려 모듈 로드 시 런타임으로 주입한다.
    """
    global _text_hook
    _text_hook = fn


# 맨 한글 구간: MinerU는 수식 속 한글을 \text{} 없이 그대로 낸다("(시간) = \frac{(거리)}…").
# 안 잡으면 날문자가 점자 문자열에 섞여 나간다(2026-07-17 dev 수식 실패 92건 중 45건의 원인).
# 다단어("시간당 일의 양")를 한 sentinel로 묶어야 훅이 한글 어절 공백을 옳게 점역한다.
_BARE_KOR_RE = re.compile(r"[가-힣ㄱ-ㅎㅏ-ㅣ]+(?: [가-힣ㄱ-ㅎㅏ-ㅣ]+)*")


def _protect_text(latex: str) -> tuple[str, list[str]]:
    r"""수식 속 자연어(\text{한글}·맨 한글)를 점자로 변환해 PUA sentinel로 치환.

    반환: (sentinel 치환된 latex, 점자 저장 리스트). convert_latex 끝에서 복원한다.
    중첩(\boxed{\text{…}})·다중 \text를 위해 안정될 때까지 반복한다.
    sentinel은 _hangul_or_sentinel이 '한글'로 판정해 제46항 띄어쓰기에 참여하고,
    괄호로 묶인 경우엔 인접 문자가 괄호라 수학편 [붙임]대로 연산·등호가 붙는다.
    """
    store: list[str] = []

    def _stash(content: str) -> str:
        brailled = content
        if _text_hook is not None:
            try:
                brailled = _text_hook(content)
            except Exception:  # noqa: BLE001 — 훅 실패 시 원문 보존(빈 결과 금지)
                brailled = content
        store.append(brailled)
        return chr(0xE000 + len(store) - 1)   # BMP PUA sentinel(이후 단계에 불활성)

    prev = None
    while prev != latex:
        prev = latex
        latex = _TEXT_CMD_RE.sub(lambda m: _stash(m.group(1)), latex)
    latex = _BARE_KOR_RE.sub(lambda m: _stash(m.group(0)), latex)
    return latex, store


def _restore_text(result: str, store: list[str]) -> str:
    for i, val in enumerate(store):
        result = result.replace(chr(0xE000 + i), val)
    return result

# MinerU가 자주 내는 명령 별칭 → 유니코드(이후 substitute_symbols 또는 수식 문맥 분기가 점자화)
# ⚠ 치환은 긴 이름 우선(아래 sorted) — 구현 초기 dict 순회가 \in을 \int보다 먼저 치환해
#   적분 \int가 ∈t로 깨지던 버그(2026-07-19 발견·정정).
_CMD_ALIAS = {
    r"\infty": "∞", r"\cdot": "·", r"\times": "×", r"\div": "÷",
    r"\leq": "≤", r"\geq": "≥", r"\neq": "≠", r"\pm": "±", r"\mp": "∓",
    r"\le": "≤", r"\ge": "≥", r"\ne": "≠",
    r"\in": "∈", r"\ni": "∋", r"\notin": "∉",
    r"\subseteq": "⊂", r"\supseteq": "⊃",   # ⊆⊇는 규정 미구분 — ⊂⊃(제60항 3호)로
    r"\subset": "⊂", r"\supset": "⊃", r"\cup": "∪", r"\cap": "∩",
    r"\angle": "∠", r"\triangle": "△", r"\square": "□",
    r"\cdots": "⋯", r"\dots": "⋯", r"\ldots": "⋯",
    r"\bullet": "·", r"\perp": "⊥", r"\parallel": "∥", r"\sslash": "∥",
    r"\circ": "∘",                            # 합성 ∘ (제15항 5호 _0) — 각도 ^∘는 별도 선처리
    r"\fallingdotseq": "≒", r"\doteq": "≒",
    r"\neg": "¬", r"\lnot": "¬",
    r"\vee": "∨", r"\lor": "∨", r"\wedge": "∧", r"\land": "∧",
    r"\nmid": "∤", r"\mid": "|",
    r"\propto": "∝",
    r"\oplus": "⊕", r"\ominus": "⊖", r"\otimes": "⊗", r"\odot": "∙",
    r"\ast": "∗", r"\star": "∗",
}


def _normalize_latex_input(latex: str) -> str:
    """MinerU/마크다운식 LaTeX를 convert_latex가 다룰 수 있게 정규화.

    코드펜스·`$$` 구분자 제거, `\\frac {1}{a _ {i}}`류 공백 축약, `\\left( … \\right)`의
    \\left/\\right 제거(절댓값 `\\left| … \\right|`은 보존), 간격 명령·줄바꿈 정리.
    """
    s = _CODE_FENCE_RE.sub("", latex)
    s = _MATH_DELIM_RE.sub(" ", s)
    s = s.replace("\r", " ").replace("\n", " ")
    s = _SPACING_CMD_RE.sub(" ", s)
    # 각도 ^{\circ}·^\circ → °(제50항 예시 0d=⠴⠙, 단위) — \circ(합성 ∘) 별칭보다 먼저.
    s = re.sub(r"\^\s*(?:\{\s*\\circ\s*\}|\\circ)", "°", s)
    # 적분 명령 보호: \iint·\int을 유니코드로 먼저 — \in 별칭이 \int를 ∈t로 깨는 것 방지.
    s = re.sub(r"\\iint(?![a-zA-Z])", "∬", s)
    s = re.sub(r"\\int(?![a-zA-Z])", "∫", s)
    # 함수 위 문자 화살표(제45항 [붙임]): \xrightarrow{f} → f 3o (문자를 화살표 앞에)
    s = re.sub(r"\\xrightarrow\s*(?:\[[^\]]*\])?\s*\{([^{}]*)\}", r" \1⠒⠕ ", s)
    # 행렬(제26항): 8 0 묶고 행 사이 개행 기호 >(⠜) 앞뒤 한 칸. 행렬식(vmatrix)은 \ \.
    def _mat_repl(m: re.Match) -> str:
        kind, body = m.group(1), m.group(2)
        rows = [" ".join(r.replace("&", " ").split())
                for r in body.split("\\\\") if r.strip()]
        inner = " ⠜ ".join(rows)
        if kind == "v":
            return f"⠳{inner}⠳"
        if kind == "b":
            return f"⠷⠄{inner}⠠⠾"
        return f"⠦{inner}⠴"

    s = re.sub(r"\\begin\{([pbv])matrix\}(.*?)\\end\{\1matrix\}",
               _mat_repl, s, flags=re.DOTALL)
    # 연립식(수학 규정 제6항): \left\{ \begin{array}… → 여는 ⠶⠄ … 닫는 ⠠⠶.
    # 정답 실측(수학2 p070): f⠦x⠴=⠶⠄√⠦x−1⠴ ⠦x≥1⠴ … ⠠⠶ — 행은 공백으로 잇는다.
    # ⚠ 평탄화(_ENV_RE)보다 먼저 잡아야 한다. \begin{cases}도 같은 구조다.
    def _sys_repl(m: re.Match) -> str:
        body = (m.group(1) or m.group(2) or "").replace("\\\\", " ").replace("&", " ")
        body = " ".join(body.split())
        # 관행(book): 연립식 각 행의 조건 괄호는 붙임표 ⠤…⠤ (정답 p070 실측 '-x≥1-').
        # 일반 수식 괄호는 관행에서도 ⠦⠴ 그대로(p009 '40⠦x+30⠴')라 연립식 body만 바꾼다.
        if _IS_BOOK_STYLE:
            body = body.replace("(", "⠤").replace(")", "⠤")
        return f" {_SYS_OPEN}{body}{_SYS_CLOSE} "

    s = _SYS_ENV_RE.sub(_sys_repl, s)
    # 배열 환경 평탄화: \begin{array}{l}…\end{array} 제거, 행 구분 \\·열 구분 & → 공백
    s = _ENV_RE.sub(" ", s)
    s = s.replace("\\\\", " ").replace("&", " ")
    # 식 번호 \tag{N} → (N)
    s = _TAG_CMD_RE.sub(r"(\1)", s)
    # 서식 래퍼(\boxed{…} 등) → 내용만. 중첩 대응으로 안정될 때까지 반복.
    prev = None
    while prev != s:
        prev = s
        s = _TEXT_WRAP_RE.sub(r"\1", s)
    s = _LEFTRIGHT_RE.sub("", s)
    # 공백 축약(명령/첨자/중괄호 주변) — 정규식이 토큰을 인식하도록
    s = _CMD_BRACE_SP_RE.sub(r"\1", s)
    s = _SUBSUP_SP_RE.sub(r"\1", s)
    s = _BRACE_IN_SP_RE.sub("{", s)
    s = _BRACE_OUT_SP_RE.sub("}", s)
    # 긴 명령 우선 치환(접두 충돌 방지: \notin>\ni, \subseteq>\subset 등)
    for cmd, uni in sorted(_CMD_ALIAS.items(), key=lambda kv: -len(kv[0])):
        s = s.replace(cmd, uni)
    s = _MULTISPACE_RE.sub(" ", s)
    s = s.strip()
    # 식 끝에 매달린 합성 ∘: 이항 연산자인데 우변이 없으면 문법적 불능 — MinerU가
    # 인접 장식 원을 \circ로 오인해 붙이는 노이즈(수학2 p034 실측). 좁게 제거.
    s = re.sub(r"\s*∘\s*$", "", s)
    return s


# 연산·비교 기호 앞뒤 붙임(수학 제45항) 대상. 11e 시점 표기 기준:
#   +→⠢·(공백낀)-→⠔·=→⠒⠒ 는 이미 점자, ×÷<>≤≥≠±∓ 는 아직 유니코드/ASCII.
# 화살표(⠒⠕)는 제51항(양쪽 한 칸)이라 제외 — ⠒⠒ 토큰만 정확히 매칭.
# ⠔·⠢는 관계·연산 접두 뒤(⠈⠔ 관계물결·⠸⠔ ⊖·⠸⠢ ⊕ — 제29·34항 한 칸, 제15항 한 칸)면
# 뺄셈·덧셈이 아니므로 제외(lookbehind).
_TIGHT_OPS_RE = re.compile(
    r"(\S)[ ⠀]*((?<![⠈⠸])⠒⠒|(?<![⠈⠸])⠢|(?<![⠈⠸])⠔|×|÷|<|>|≤|≥|≠|±|∓)[ ⠀]*(?=(\S))")


def _hangul_or_sentinel(ch: str) -> bool:
    """한글 음절/자모 또는 \\text 보호 sentinel(PUA) — 제46항 '한글 사이' 판정."""
    return ("가" <= ch <= "힣") or ("ㄱ" <= ch <= "ㅣ") or (0xE000 <= ord(ch) <= 0xF8FF)


def _tighten_operator_spacing(result: str) -> str:
    """수학 제45항: 연산·비교 기호는 앞뒤를 붙여 쓴다(5+7=12 → #e5#g33#ab).

    제46항: 기호가 한글 사이에 나올 때에는 앞뒤 한 칸 유지(나루 + 배 = 나룻배).
    LaTeX 입력의 관습적 공백("x + 1")을 규정에 맞게 정리해 셀 과생성도 막는다.
    """
    def _repl(m: re.Match) -> str:
        left, op, right = m.group(1), m.group(2), m.group(3)
        if _hangul_or_sentinel(left) or _hangul_or_sentinel(right):
            return m.group(0)
        return f"{left}{op}"

    return _TIGHT_OPS_RE.sub(_repl, result)


def convert_latex(latex: str) -> str:
    """LaTeX 수식 문자열 → 점자 BRF.

    처리 순서:
      0. MinerU/마크다운 입력 정규화 (코드펜스·$$·공백·\\left\\right)
      1. 수학 괄호 변환 (텍스트 괄호와 충돌 방지)
      2. 구조 기호: 분수, 근호
      3. 함수: lim, log, ln, 삼각함수
      4. 위/아래 첨자
      5. 숫자 변환
      6. 나머지 유니코드 기호 → substitute_symbols
      7. 잔여 LaTeX 명령어·중괄호 제거
    """
    latex, _text_store = _protect_text(latex)   # P2: \text{한글} → 한글 점자 sentinel
    result = _normalize_latex_input(latex)

    # ── 0b. n제곱근: \sqrt[n]{내용} — 대괄호 치환(1단계)보다 먼저 잡아야 한다.
    # 구현이 1단계 뒤에 있어 [n]이 대괄호 점형 ⠷⠄…⠠⠾로 선점되던 버그(2026-07-19 정정).
    def _sqrt_n_replace(m: re.Match) -> str:
        n_part = convert_latex(m.group(1))
        inner  = convert_latex(m.group(2))
        inner_w = f"{_WRAP_S}{inner}{_WRAP_E}" if _needs_wrap(m.group(2)) else inner
        return f"{n_part}{_SQRT_N_IND}{inner_w}"

    result = _SQRT_N_RE.sub(_sqrt_n_replace, result)

    # ── 1. 수학 괄호 치환 (substitute_symbols보다 먼저) ─────────────────
    # 중괄호 \{ \} = ⠶…⠶ (수학 제6항 1: 중괄호 '7 7', 집합 예시 ,a337#b…7 실측).
    #   구현엔 이스케이프 미처리로 백슬래시(⠸⠡)가 새어나가던 버그(2026-07-19 정정).
    result = result.replace("\\{", "⠶").replace("\\}", "⠶")
    # 대괄호 [ ] = ⠷⠄…⠠⠾ (수학 제6항 1: 대괄호 (' ,) — y=[x] 예시 y33('x,) 실측).
    #   한글 문장부호 대괄호(⠦⠆…⠰⠴)와 다르다 — 수식 내에서는 수학 대괄호.
    result = result.replace("[", "⠷⠄").replace("]", "⠠⠾")
    result = result.replace("(", _MATH_PAREN_S).replace(")", _MATH_PAREN_E)
    # 괄호 인접 공백 제거: 정답·규정 모두 f⠦x⠴·⠦x−1⠴f⠦x⠴처럼 붙인다(수학2 p070 셀 대조,
    # MinerU는 "f (x)"로 띄워 낸다). 한글(sentinel) 인접은 제46항 몫이라 라틴·숫자·괄호만.
    result = re.sub(rf"(?<=[A-Za-z0-9{_MATH_PAREN_E}]) +(?={_MATH_PAREN_S})", "", result)
    result = re.sub(rf"(?<={_MATH_PAREN_E}) +(?=[A-Za-z0-9{_MATH_PAREN_S}])", "", result)
    # 숫자·문자 곱도 붙인다: "1 6 x"→16x (정답 수학2 p009 '…16옥=옥…' — 곱 생략 인접 표기).
    result = re.sub(r"(?<=\d) +(?=[A-Za-z])", "", result)

    # ── 1b. 문자 위 기호 (제23·35~38·64·65항) ─────────────────────────────
    # prefix형(벡터·선분 계열)은 기호를 앞에, postfix형(바·햇·점)은 뒤에 적는다.
    # 가로바는 내용이 연속 대문자(선분 AB, 제35항)면 prefix, 아니면 켤레·평균(제23항) postfix.
    def _acc_prefix(m: re.Match) -> str:
        name = m.group(1) or "vec"
        content = m.group(2) if m.group(2) is not None else m.group(3)
        return f"{_ACC_PREFIX_MARK[name]}{convert_latex(content)}"

    result = _ACC_PREFIX_RE.sub(_acc_prefix, result)

    def _acc_postfix(m: re.Match) -> str:
        name = m.group(1) or m.group(3)
        content = m.group(2) if m.group(2) is not None else m.group(4)
        mark = _ACC_POSTFIX_MARK[name]
        if mark == "⠈⠉" and _CAPS_RUN_RE.match(content.strip()):
            return f"⠈⠉{convert_latex(content)}"   # 선분 @c,,AB (제35항)
        return f"{convert_latex(content)}{mark}"

    result = _ACC_POSTFIX_RE.sub(_acc_postfix, result)

    # ── 1c. 순열·조합 (제62항): nPr → ,P(n r) — P/C/H, 중복순열 \Pi는 ,.P ──
    def _perm_replace(m: re.Match) -> str:
        low = convert_latex(_unbrace(m.group(1)))
        letter = m.group(2)
        up = convert_latex(_unbrace(m.group(4)))
        head = "⠠⠨⠏" if letter is None else "⠠" + _letter_braille(letter.lower())
        return f"{head}{_WRAP_S}{low}{_SP}{up}{_WRAP_E}"

    result = _PERM_RE.sub(_perm_replace, result)

    # ── 1d. 왼쪽 첨자 (제18·19항 2호): {}^{t}A → ⠘(t)A — 첨자는 항상 묶음 ──
    result = _LEFT_SUP_RE.sub(
        lambda m: f"⠘{_WRAP_S}{convert_latex(_unbrace(m.group(1)))}{_WRAP_E}{m.group(2)}",
        result)
    result = _LEFT_SUB_RE.sub(
        lambda m: f"⠰{_WRAP_S}{convert_latex(_unbrace(m.group(1)))}{_WRAP_E}{m.group(2)}",
        result)

    # ── 1e. 정적분 범위 (제57·58항): ∫_a^b → ⠮⠰a⠀b⠀ (위끝은 ⠘ 위첨자가 아님) ──
    def _int_replace(m: re.Match) -> str:
        base = _INT_BASE[m.group(1)]
        low = convert_latex(_unbrace(m.group(2)))
        up = convert_latex(_unbrace(m.group(3))) if m.group(3) else ""
        return f"{base}⠰{low}{_SP}{up}{_SP}" if up else f"{base}⠰{low}{_SP}"

    result = _INT_RANGE_RE.sub(_int_replace, result)
    result = result.replace("∫", "⠮").replace("∬", "⠮⠮")
    # 정적분 값 대괄호 [F(x)]_a^b (제57항): 닫는 대괄호 뒤 범위도 칸 구분
    result = _BRACKET_RANGE_RE.sub(
        lambda m: f"⠠⠾⠰{convert_latex(_unbrace(m.group(2)))}"
                  + (f"{_SP}{convert_latex(_unbrace(m.group(3)))}" if m.group(3) else ""),
        result)

    # ── 1f. 삼각함수 인수 묶음 (제47항 [붙임]): sin 3x → 6s(3x) — 곱·분수 인수만 ──
    result = _TRIG_ARG_RE.sub(
        lambda m: f"{m.group(1)}{m.group(2) or ''}{_WRAP_S}{m.group(3)}{_WRAP_E}", result)

    # ── 2. 분수: \frac{...}{...} → 분모⠌분자 (수학 제7항, 중첩 중괄호 대응) ──
    result = _apply_fracs(result)

    # ── 2c. 제곱근: \sqrt{내용} → ⠜내용 (수학 제22항; n제곱근은 0b에서 선처리) ──
    def _sqrt_replace(m: re.Match) -> str:
        inner = convert_latex(m.group(1))
        inner_w = f"{_WRAP_S}{inner}{_WRAP_E}" if _needs_wrap(m.group(1)) else inner
        return f"{_SQRT_IND}{inner_w}"

    result = _SQRT_RE.sub(_sqrt_replace, result)

    # ── 3. 극한: \lim_{x \to val} → lim;x ` → ` val ` 함수 ──────────
    def _lim_replace(m: re.Match) -> str:
        var = convert_latex(m.group(1).strip())
        val = convert_latex(m.group(2).strip())
        return f"{_LIM_BRAILLE}{_SUBSCRIPT_IND}{var} {_ARROW_RIGHT} {val} "

    result = _LIM_RE.sub(_lim_replace, result)
    # 단독 \to / \rightarrow → 화살표
    result = _TO_RE.sub(_ARROW_RIGHT, result)

    # ── 4. 로그 ─────────────────────────────────────────────────────────
    # \ln → log_e
    result = result.replace("\\ln", _LN_BRAILLE)

    # \log_{base} — 밑이 중괄호 안에. 진수(⠦…⠴)는 재귀 없이 제자리 재방출 —
    # 내용은 이후 단계(숫자·기호 변환)가 이어서 처리한다.
    def _log_base_replace(m: re.Match) -> str:
        base_raw = m.group(1).strip()
        trailing = m.group(2)
        tail = f"⠦{trailing}⠴" if trailing is not None else ""
        base = convert_latex(base_raw)
        # 밑이 숫자(다자리 포함): _, + 수표 없이 내린 숫자들 (제46항 1호)
        if base_raw.isdigit():
            dropped = "".join(_digit_no_indicator(ch) for ch in base_raw)
            head = f"{_LOG_IND}{_LOG_NUM_SEP}{dropped}"
            # [붙임 2] 밑이 숫자이고 진수가 괄호식이면 묶음으로 다시 묶는다(_,2(8x5#a0)).
            # 관행 모드는 묶음=소괄호꼴이라 겹괄호가 되므로 규정 모드만 겉묶음을 더한다.
            if tail and not _IS_BOOK_STYLE:
                return f"{head}{_WRAP_S}{tail}{_WRAP_E}"
            return f"{head}{tail}"
        # 밑이 소수/분수인 경우 묶음 괄호 (수학 제46항 붙임1)
        if _needs_wrap(base_raw) or re.fullmatch(r"\d+\.\d+", base_raw):
            return f"{_LOG_IND}{_SUBSCRIPT_IND}{_WRAP_S}{base}{_WRAP_E}{tail}"
        # [다만] 밑이 문자면 괄호 진수는 그대로 잇는다
        return f"{_LOG_IND}{_SUBSCRIPT_IND}{base}{tail}"

    result = _LOG_BASE_FULL_RE.sub(_log_base_replace, result)

    # \log_x (단일 문자/숫자)
    def _log_base1_replace(m: re.Match) -> str:
        b = m.group(1)
        if b.isdigit():
            return f"{_LOG_IND}{_LOG_NUM_SEP}{_digit_no_indicator(b)}"
        return f"{_LOG_IND}{_SUBSCRIPT_IND}{_letter_braille(b)}"

    result = _LOG_BASE1_RE.sub(_log_base1_replace, result)
    # 밑 없는 log
    result = result.replace("\\log", _LOG_IND)

    # ── 5. 삼각함수 (수학 점자 제47~49항) ──────────────────────────────
    # 긴 이름(arcsin 등)을 먼저 처리해 substr 충돌 방지
    for name, braille in _TRIG.items():
        result = result.replace(f"\\{name}", braille)

    # ── 5b. 함수 기호 뒤 단일 인수 붙임 — 규정 예시가 전부 붙임(6shx·6sx^#c·
    # arc6s,A·LNx·#b6cx·!f8x0). LaTeX 관습 공백("\sin x")을 제거한다.
    # 대상: 삼각(⠖?·⠖?⠓)·ln(⠇⠝)·맨 log(⠸)·적분(⠮) 뒤 한 칸.
    result = re.sub(r"(⠖[⠎⠉⠞⠣⠤⠳]⠓?|⠇⠝|⠮⠮?|⠸)[ ]+(?=\S)", r"\1", result)

    # ── 6. 절댓값 (수학 제21항): \ \ ────────────────────────────────────
    def _abs_replace(m: re.Match) -> str:
        inner = convert_latex((m.group(1) or m.group(2) or ""))
        return f"{_ABS_IND}{inner}{_ABS_IND}"

    result = _ABS_RE.sub(_abs_replace, result)
    # 단순 |...| 패턴 (LaTeX에서 수직바로 쓴 절댓값)
    result = re.sub(r"\|([^|]+)\|", lambda m: f"{_ABS_IND}{convert_latex(m.group(1))}{_ABS_IND}", result)
    result = result.replace("\\|", _ABS_IND)

    # ── 7. 합 기호: \sum_{lower}^{upper} (수학 제25항) ──────────────────
    # ∑ 기호는 symbol_table에서 처리, 여기서는 범위 구조만 처리
    def _sum_replace(m: re.Match) -> str:
        lower = convert_latex(m.group(1))
        upper = convert_latex(m.group(2)) if m.group(2) else ""
        # ,.S;lower upper 본식 형태: 여기서는 범위 표시만
        base = "⠠⠨⠎"   # ,.S (총합 기호, 수학 제25항)
        if upper:
            return f"{base}{_SUBSCRIPT_IND}{lower} {upper} "
        return f"{base}{_SUBSCRIPT_IND}{lower} "

    result = _SUM_RE.sub(_sum_replace, result)
    result = result.replace("\\sum", "⠠⠨⠎")

    # ── 8. 위첨자: base^{exp} → base⠘exp (수학 제18항) ──────────────
    def _sup_replace(m: re.Match) -> str:
        base = m.group(1) or m.group(3) or ""
        raw_exp = (m.group(2) or m.group(4) or "").strip()
        # 관행(book): 제곱(^2)은 ⠣ 한 셀 약기 — 정답 코퍼스에서 규정형 ⠘⠼⠃은 0회,
        # ⠣형만 관측(수학2 p009 'x<9#b'·p039 'x<5y<' 실측). 규정 모드는 제18항 그대로.
        # 관행 지수 약기: ²=⠣(gold 107회)·³=⠩(9건 중 7건, 2026-07-19 실측).
        # ⁴ 이상은 gold도 규정형 ⠘⠼N을 쓰므로 약기하지 않는다.
        if _IS_BOOK_STYLE and raw_exp in ("2", "3"):
            return base + ("⠣" if raw_exp == "2" else "⠩")
        exp  = convert_latex(raw_exp)
        exp_w = f"{_WRAP_S}{exp}{_WRAP_E}" if _needs_wrap(raw_exp) else exp
        return f"{base}{_SUPERSCRIPT_IND}{exp_w}"

    result = _SUP_RE.sub(_sup_replace, result)

    # ── 9. 아래첨자: base_{sub} → base⠰sub (수학 제19항, ; = ⠰) ────────────
    def _sub_replace(m: re.Match) -> str:
        base = m.group(1) or m.group(3) or ""
        sub  = convert_latex(m.group(2) or m.group(4) or "")
        sub_w = f"{_WRAP_S}{sub}{_WRAP_E}" if _needs_wrap(m.group(2) or m.group(4) or "") else sub
        return f"{base}{_SUBSCRIPT_IND}{sub_w}"

    result = _SUB_RE.sub(_sub_replace, result)

    # ── 10. 기타 LaTeX 명령어 직접 매핑 ────────────────────────────────
    _LATEX_SIMPLE: dict[str, str] = {
        "\\infty":    "⠿",    # ∞ (수학 제50항: =)
        "\\pm":       "⠢⠔",   # ± (제51항 예시 59=⠢⠔; 별칭 경유 시 symbol_table과 동일)
        "\\times":    "⠡",    # × (수학 제2항, 폰트 "*"=⠡)
        "\\div":      "⠌⠌",   # ÷ (수학 제2항, 폰트 "//"=⠌⠌)
        "\\cdot":     "⠐",    # · (수학 제2항 붙임, 폰트 '"'=⠐)
        "\\leq":      "⠖⠖",   # ≤ (수학 제4항 8호, 폰트 66=⠖⠖ — ⠦는 8 오독이었음)
        "\\geq":      "⠲⠲",   # ≥ (수학 제4항 6호, 폰트 "44"=⠲⠲)
        "\\neq":      "⠨⠒⠒",  # ≠ (수학 제4항 1호, 폰트 ".33"=⠨⠒⠒)
        "\\approx":   "⠈⠔⠈⠔", # ≈ 이중물결 (제29항 @9@9, 앞뒤 한 칸)
        "\\equiv":    "⠶⠶",   # ≡ 합동 (기하 제43항 77=⠶⠶ — ⠛은 폰트 g 오독)
        "\\sim":      "⠈⠔",   # ∼ 관계·분포 (제34항 @9). 닮음 ∽(⠠⠄)는 유니코드 경유
        "\\in":       "⠖",    # ∈ (제60항 1호 가, 폰트 6=⠖)
        "\\notin":    "⠨⠖",   # ∉ (제60항 1호 다 .6)
        "\\subset":   "⠖⠂",   # ⊂ (제60항 3호 61)
        "\\supset":   "⠐⠲",   # ⊃ (제60항 3호 나 "4)
        "\\cup":      "⠬",    # ∪ (수학 제60항 5호 가)
        "\\cap":      "⠩",    # ∩ (수학 제60항 5호 나)
        "\\emptyset": "⠨⠋",   # ∅ (수학 제60항 4호)
        "\\varnothing": "⠨⠋", # ∅
        "\\forall":   "⠨⠄",   # ∀ (제61항 9호 가 .')
        "\\exists":   "⠨⠢",   # ∃ (제61항 9호 나 .5)
        "\\partial":  "⠫",    # ∂ (편도함수, 제54항)
        "\\nabla":    "⠸⠩",   # ∇ (델연산자, 제55항)
        "\\int":      "⠮",    # ∫ (부정적분, 제56항: ! = ⠮)
        "\\alpha":    "⠨⠁",   # α
        "\\beta":     "⠨⠃",   # β
        "\\gamma":    "⠨⠛",   # γ
        "\\delta":    "⠨⠙",   # δ
        "\\epsilon":  "⠨⠑",   # ε
        "\\varepsilon":"⠨⠑",  # ε (변형)
        "\\zeta":     "⠨⠵",   # ζ
        "\\eta":      "⠨⠱",   # η (수학 제13항 표 .:)
        "\\theta":    "⠨⠹",   # θ
        "\\iota":     "⠨⠊",   # ι
        "\\kappa":    "⠨⠅",   # κ
        "\\lambda":   "⠨⠇",   # λ
        "\\mu":       "⠨⠍",   # μ
        "\\nu":       "⠨⠝",   # ν
        "\\xi":       "⠨⠭",   # ξ
        "\\pi":       "⠨⠏",   # π
        "\\rho":      "⠨⠗",   # ρ
        "\\sigma":    "⠨⠎",   # σ
        "\\tau":      "⠨⠞",   # τ
        "\\upsilon":  "⠨⠥",   # υ
        "\\phi":      "⠨⠋",   # φ
        "\\varphi":   "⠨⠋",   # φ (변형)
        "\\chi":      "⠨⠯",   # χ (수학 제13항 표 .&)
        "\\psi":      "⠨⠽",   # ψ
        "\\omega":    "⠨⠺",   # ω
        "\\cdots":    "⠠⠠⠠",  # ⋯ 수식 줄임표 (제12항 [붙임1] ,,,)
        "\\ldots":    "⠠⠠⠠",  # … (제12항 [붙임1])
        "\\vdots":    "⠠⠠⠠",  # ⋮
        "\\ddots":    "⠨⠨⠨",  # ⋱
        "\\therefore":_THEREFORE,  # ∴ (제65항 2호 ,* / 도서 관행 ⠌⠄)
        "\\because":  "⠈⠌",   # ∵ (수학 제65항 3호: @/)
        "\\rightarrow": "⠒⠕", # → (3o)
        "\\uparrow":   "⠰⠒⠕",  # ↑ (제10항 ;3o)
        "\\downarrow": "⠘⠒⠕",  # ↓ (제10항 ^3o)
        "\\nearrow":   "⠔⠕",   # ↗ (제10항 9o)
        "\\searrow":   "⠢⠕",   # ↘ (제10항 5o)
        "\\leftarrow":  "⠪⠒", # ← (폰트 "[3"=⠪⠒)
        "\\leftrightarrow": "⠪⠒⠕",  # ↔ (폰트 "[3o")
        "\\Rightarrow":  "⠒⠒⠕",     # ⇒ (명제 제61항, "33o")
        "\\Leftarrow":   "⠐⠉⠉",     # ⇐ (미확인 — 규정 원문 재확인 필요)
        "\\Leftrightarrow": "⠪⠒⠒⠕", # ⇔ (명제 제61항, "[33o")
        # 대문자 그리스 문자
        "\\Alpha":   "⠠⠨⠁", "\\Beta":    "⠠⠨⠃",
        "\\Gamma":   "⠠⠨⠛", "\\Delta":   "⠠⠨⠙",
        "\\Epsilon": "⠠⠨⠑", "\\Zeta":    "⠠⠨⠵",
        "\\Eta":     "⠠⠨⠱", "\\Theta":   "⠠⠨⠹",
        "\\Iota":    "⠠⠨⠊", "\\Kappa":   "⠠⠨⠅",
        "\\Lambda":  "⠠⠨⠇", "\\Mu":      "⠠⠨⠍",
        "\\Nu":      "⠠⠨⠝", "\\Xi":      "⠠⠨⠭",
        "\\Pi":      "⠠⠨⠏", "\\Rho":     "⠠⠨⠗",
        "\\Sigma":   "⠠⠨⠎", "\\Tau":     "⠠⠨⠞",
        "\\Upsilon": "⠠⠨⠥", "\\Phi":     "⠠⠨⠋",
        "\\Chi":     "⠠⠨⠯", "\\Psi":     "⠠⠨⠽",
        "\\Omega":   "⠠⠨⠺",
        # 선적분 (수학 제59항: )으로 적는다)
        "\\oint":    "⠾",
        # 절댓값 (수학 제21항: \ \)
        "\\lvert":   "⠳", "\\rvert":   "⠳",
        "\\lVert":   "⠳⠳", "\\rVert":  "⠳⠳",
        # 노름 (수학 제28항: \\ \\)
        "\\|":       "⠳⠳",
        # 프라임 (수학 제17항: -으로 적는다)
        "\\prime":   "⠤",
        # 퍼센트·비 등
        "\\%":       "⠴⠏",   # % 단위 (단위표 0=⠴)
    }
    # 긴 명령어를 먼저 치환하여 prefix 충돌 방지 (예: \\int vs \\in)
    for latex_cmd, braille_val in sorted(_LATEX_SIMPLE.items(), key=lambda x: -len(x[0])):
        result = result.replace(latex_cmd, braille_val)

    # ── 10x. 뺄셈표: 남은 하이픈은 수식 문맥에선 뺄셈·음수 (수학 제2항 9=⠔) ──
    # 숫자 변환 전에 처리 — _NUM_RE의 선행 '-?'가 이항 뺄셈("9-3")을 숫자 내
    # 붙임표(⠤, 계좌번호용)로 삼키는 것을 막는다(제45항 예시 #i9#c33#f).
    # 프라임(′→⠤, 제17항)은 _LATEX_SIMPLE에서 이미 치환됨. \text 한글은 sentinel로 보호됨.
    result = result.replace("-", "⠔")

    # ── 11. 숫자 → 수표시 + 점자 ──────────────────────────────────────
    def _num_replace(m: re.Match) -> str:
        return digits_to_braille(m.group())

    result = _NUM_RE.sub(_num_replace, result)

    # ── 11a. 숫자 뒤 로마자 a~j: 붙여 쓰되 "(⠐)을 적는다 (제12항 [다만]·[붙임]) ──
    # 숫자 셀과 a~j 문자 셀이 동형이라 3a가 31로 읽히는 것을 막는 규정. gold 실측
    # #B"A(2a) 59회 일치. 대상은 a~j 소문자만(대문자는 ⠠가 이미 구분).
    result = re.sub(r"(⠼[⠁⠃⠉⠙⠑⠋⠛⠓⠊⠚⠲⠂]*[⠁⠃⠉⠙⠑⠋⠛⠓⠊⠚])([a-j])",
                    r"\1⠐\2", result)

    # ── 11b. 사칙연산 기호 변환 (수학 제2항) — 숫자 변환 후 처리 ──────────
    result = result.replace("+", "⠢")                        # 덧셈표 (수학 제2항, 폰트 "5"=⠢)
    result = result.replace("=", "⠒⠒")                       # 등호 (수학 제3항, 폰트 "33"=⠒⠒)

    # ── 11c. 문맥 overload 분기: 수식 내 기호는 수학 의미로(텍스트 substitute_symbols와 분리) ──
    # ∼: 수식 논리부정·관계 = ⠈⠔ (명제 제61항, 폰트 "@9"). 텍스트 물결표는 symbol_table 담당.
    # →: 화살표·조건문 = ⠒⠕ (제38·61항, 폰트 "3o").
    result = result.replace("∼", "⠈⠔").replace("→", "⠒⠕")
    result = result.replace("∴", _THEREFORE)
    # 숫자 사이 쉼표(제41항): ⠂로 적고 **뒤 숫자에 수표를 다시 적지 않는다**(제43항).
    # 구현이 제12항 [붙임1]의 *로마자* 나열 쉼표(⠐)를 숫자에까지 적용하던 규정 위반 정정
    # (2026-07-19, gold 실측도 숫자⠂숫자 249 : 숫자⠐숫자 117로 규정 편).
    result = re.sub(f"(?<=[{''.join(_DIGIT_MAP.values())}]),⠼(?=[{''.join(_DIGIT_MAP.values())}])",
                    "⠂", result)
    # 나머지 나열 쉼표(로마자·식 사이) = 문장부호 쉼표 ⠐
    # (규정 집합 예시 ,a337#b"#d"#f7 의 " = ⠐, 2026-07-19)
    result = result.replace(",", "⠐")
    # 계승(제62항 1호): 수식의 ! = ⠖ (gold 실측 #D6=4! 일치). 텍스트 느낌표와 분리.
    result = result.replace("!", "⠖")
    # 점곱셈(제2항 [붙임]): 수식의 ·(비롯 ⋅ U+22C5) = ⠐ 한 칸 — 한글 가운뎃점 ⠐⠆와 분리.
    result = result.replace("·", "⠐").replace("⋅", "⠐")
    # 프라임(제17항): 수식의 ′ = ⠤, ″ = ⠤⠤ — 텍스트 각도 분·초 표기(⠴⠤)와 분리.
    # LaTeX 아포스트로피 프라임(f'(x)·y'')도 동일 — 구현은 ⠄(따옴표)로 새던 버그 정정.
    result = result.replace("″", "⠤⠤").replace("′", "⠤").replace("'", "⠤")
    # 합성(제15항 5호): ∘ = ⠸⠴. 도형(제40항): △·증분 ∆ = ⠸⠬, □ = ⠸⠶
    # — 지침의 텍스트 세모·네모 문자(⠸⠬⠇류)와 분리.
    result = result.replace("∘", "⠸⠴")
    result = result.replace("△", "⠸⠬").replace("∆", "⠸⠬")
    result = result.replace("□", "⠸⠶").replace("◻", "⠸⠶")
    # 나누어떨어짐(제27항): ∤ = ⠨⠳, 남은 수직바(조건제시·조건부확률·나눔)는 ⠳
    result = result.replace("∤", "⠨⠳")
    result = result.replace("|", _ABS_IND)

    # ── 11e. 연산·비교 기호 앞뒤 붙임 (수학 제45항: 5+7=12 → #e5#g33#ab) ──
    # LaTeX 입력의 공백("x + 1")이 그대로 점자에 남아 규정 위반 + 셀 과생성.
    # 단, 제46항: 한글(\text 보호 sentinel 포함)이 어느 한쪽에라도 오면 한 칸 유지.
    # 화살표(⠒⠕)는 제51항이 양쪽 띄움을 요구하므로 대상에서 제외.
    result = _tighten_operator_spacing(result)

    # ── 11d. 미처리 \cmd 제거(P3) — substitute_symbols가 백슬래시를 ⠸⠡로 음역하기 전에 정리.
    # 구조·텍스트 매크로는 위에서 내용으로 풀렸고, 여기 남은 건 미지원 명령 → 제거(음역 방지).
    result = re.sub(r"\\[a-zA-Z]+\*?", "", result)

    # ── 12. 남은 유니코드 수학 기호 → substitute_symbols ────────────────
    result = substitute_symbols(result)

    # ── 13. 잔여 LaTeX 명령어·중괄호 제거 ──────────────────────────────
    result = re.sub(r"\\[a-zA-Z]+\*?", "", result)
    result = re.sub(r"[{}]", "", result)

    # ── 14. 남은 로마자 → 수식 점자 (로마자표 없이, 수학 점자 제12항) ──────
    # 연속 대문자(프라임 ⠤ 개재 허용)는 대문자 단어표 ⠠⠠ 하나로(제35항 [붙임]
    # @c,,A-B-, gold ,, 572회 실측). 단독 대문자는 대문자표 ⠠.
    result = re.sub(
        r"[A-Z](?:⠤?[A-Z])+⠤?",
        lambda m: "⠠⠠" + "".join(_letter_braille(c) if c.isalpha() else c
                                  for c in m.group()),
        result)
    result = re.sub(r"[A-Z]", lambda m: "⠠" + _letter_braille(m.group()), result)
    result = re.sub(r"[a-z]", lambda m: _letter_braille(m.group()), result)

    # ── 15. 수식 내 ASCII 공백 → 점자공백(⠀), 구조 공백 sentinel 복원 ──────
    # 구조 공백(제51·57항)과 입력 공백이 겹치면 한 칸으로(⠿  f(x) 이중 칸 방지)
    result = re.sub(r" *\x1f *", _SP, result)
    result = re.sub(r" {2,}", " ", result)
    result = result.replace(" ", "⠀")
    result = result.replace(_SP, "⠀")

    # ── 16. P2: 보호한 \text{한글} 점자 복원 ─────────────────────────────
    result = _restore_text(result, _text_store)
    return result


# ── 수식 구조 → rule_id (rule_trail emit용, Phase B) ────────────────────────
# 항→장→KBR-수학-{장}.{항}. 규정 원문 + 장 경계로 검증(환각 0). 모두 regulations.json 실재.
_STRUCT_RULES: list[tuple[str, str]] = [
    # (rule_id, 설명)  — 탐지 순서가 trail 순서
    ("KBR-수학-1.7", "분수"),      # 제7항
    ("KBR-수학-2.18", "위첨자"),   # 제18항
    ("KBR-수학-2.19", "아래첨자"), # 제19항
    ("KBR-수학-2.21", "절댓값"),   # 제21항
    ("KBR-수학-2.22", "근호"),     # 제22항
    ("KBR-수학-2.25", "총합"),     # 제25항
    ("KBR-수학-5.46", "로그"),     # 제46항
    ("KBR-수학-5.47", "삼각함수"), # 제47항
    ("KBR-수학-5.48", "역삼각함수"),  # 제48항
    ("KBR-수학-5.49", "쌍곡선함수"),  # 제49항
    ("KBR-수학-6.51", "극한"),     # 제51항
    ("KBR-수학-6.54", "편도함수"), # 제54항
    ("KBR-수학-6.55", "델연산자"), # 제55항
    ("KBR-수학-6.56", "적분"),     # 제56항
    ("KBR-수학-6.59", "선적분"),   # 제59항
]

# 단순 LaTeX 기호 명령 → rule_id (구조 외, 검증된 항만). \cmd 토큰 단위 매칭(substring 무관).
_LATEX_SYMBOL_RULES: dict[str, str] = {
    # 집합 (수학 제60항)
    **{c: "KBR-수학-7.60" for c in (
        "in", "notin", "ni", "subset", "supset", "subseteq", "supseteq",
        "cup", "cap", "emptyset", "varnothing", "vdash")},
    # 부등호 (수학 제4항)
    **{c: "KBR-수학-1.4" for c in ("leq", "le", "geq", "ge", "neq", "ne")},
    # 논리·명제 (수학 제61항)
    **{c: "KBR-수학-7.61" for c in (
        "forall", "exists", "neg", "lnot", "land", "wedge", "lor", "vee")},
    # 근사·합동·닮음 (수학 제29·32·43·42항)
    "approx": "KBR-수학-3.29", "cong": "KBR-수학-3.32",
    "equiv": "KBR-수학-4.43", "sim": "KBR-수학-4.42",
    # 연산 (수학 제2항 ×÷±, 제15항 ⊕⊗∙)
    "pm": "KBR-수학-1.2", "times": "KBR-수학-1.2", "div": "KBR-수학-1.2",
    "cdot": "KBR-수학-2.15", "oplus": "KBR-수학-2.15",
    "ominus": "KBR-수학-2.15", "otimes": "KBR-수학-2.15",
    # 기타 (수학 제65항 ∴∵ℵ, 제50항 ∞)
    "therefore": "KBR-수학-9.65", "because": "KBR-수학-9.65",
    "aleph": "KBR-수학-9.65", "infty": "KBR-수학-6.50",
    # 그리스 문자 (한글 제4장 제10절 제30항)
    **{g: "KBR-4.10.30" for g in (
        "alpha", "beta", "gamma", "delta", "epsilon", "varepsilon", "zeta",
        "eta", "theta", "iota", "kappa", "lambda", "mu", "nu", "xi", "pi",
        "rho", "sigma", "tau", "upsilon", "phi", "varphi", "chi", "psi", "omega",
        "Alpha", "Beta", "Gamma", "Delta", "Epsilon", "Zeta", "Eta", "Theta",
        "Iota", "Kappa", "Lambda", "Mu", "Nu", "Xi", "Pi", "Rho", "Sigma",
        "Tau", "Upsilon", "Phi", "Chi", "Psi", "Omega")},
}

_RE_TRIG_ARC = re.compile(r"\\arc(?:sin|cos|tan|csc|sec|cot)")
_RE_TRIG_HYP = re.compile(r"\\(?:sin|cos|tan|csc|sec|cot)h")
_RE_TRIG_BASE = re.compile(r"\\(?:sin|cos|tan|csc|sec|cot)(?![a-z])")
_RE_ABS_BAR = re.compile(r"\|[^|]+\|")


def latex_rule_ids(latex: str) -> list[str]:
    """LaTeX 수식에 쓰인 수학 '구조'(분수·근·첨자·로그·극한·합·절댓값·적분·삼각) → rule_id 목록.

    source-based(LaTeX 명령 탐지) — 환각 0: 항을 규정 원문에서 검증한 rule_id만 사용.
    단순 기호 명령(\\in, \\leq, 그리스 등)은 여기서 다루지 않음(symbol_table 매핑 영역).
    반환은 탐지 순서·중복제거. 좌표는 formula_braille에서 수식 전체로 부여(구조 좌표는 추후).
    """
    out: list[str] = []

    def add(rule_id: str) -> None:
        if rule_id not in out:
            out.append(rule_id)

    s = latex
    if "\\frac" in s:
        add("KBR-수학-1.7")
    if "\\sqrt" in s:
        add("KBR-수학-2.22")
    if "\\sum" in s:
        add("KBR-수학-2.25")
    if "\\lim" in s:
        add("KBR-수학-6.51")
    if "\\log" in s or "\\ln" in s:
        add("KBR-수학-5.46")
    if _RE_TRIG_ARC.search(s):
        add("KBR-수학-5.48")
    if _RE_TRIG_HYP.search(s):
        add("KBR-수학-5.49")
    if _RE_TRIG_BASE.search(s):
        add("KBR-수학-5.47")
    if "\\partial" in s:
        add("KBR-수학-6.54")
    if "\\nabla" in s:
        add("KBR-수학-6.55")
    if "\\oint" in s:
        add("KBR-수학-6.59")
    if "\\int" in s:
        add("KBR-수학-6.56")
    if (_ABS_RE.search(s) or "\\lvert" in s or "\\lVert" in s
            or "\\|" in s or _RE_ABS_BAR.search(s)):
        add("KBR-수학-2.21")
    # 첨자: 함수/구조 명령(자체 _·^ 보유)을 제거한 잔여에서만 ^·_ 판정 → \log_ \lim_ \sum_ 오계수 방지
    residual = _LIM_RE.sub(" ", s)
    residual = _LOG_BASE_RE.sub(" ", residual)
    residual = _LOG_BASE1_RE.sub(" ", residual)
    residual = _SUM_RE.sub(" ", residual)
    for cmd in ("\\log", "\\ln", "\\sum", "\\sqrt", "\\lim"):
        residual = residual.replace(cmd, " ")
    if _SUP_RE.search(residual):
        add("KBR-수학-2.18")
    if _SUB_RE.search(residual):
        add("KBR-수학-2.19")
    # 단순 기호 명령(\in, \leq, 그리스 등) — \cmd 토큰 단위로 추출(substring 충돌 없음)
    for cmd in set(re.findall(r"\\([A-Za-z]+)", s)):
        rid = _LATEX_SYMBOL_RULES.get(cmd)
        if rid:
            add(rid)
    # 탐지 순서를 _STRUCT_RULES 기준으로 정렬(구조 먼저, 기호 명령은 뒤)
    order = {r: i for i, (r, _) in enumerate(_STRUCT_RULES)}
    out.sort(key=lambda r: order.get(r, 99))
    return out


def _needs_wrap(expr: str) -> bool:
    """점역자 삽입 묶음 괄호 필요 판정 (수학 제7항 3호·제18항 붙임·제22항 붙임2).

    묶는다: 다항식(이항 +/−), 분수(/·\\frac), 곱(인수 2개 이상 — xy·2a·2(m+n)).
    안 묶는다: 단일 수(소수·자릿점 포함, 제18항 x^#j4c)·단일 문자·문자^단일첨자
    (제22항 #c]x^#c)·미분소 dx·d²y(제53항 dx/dy 실측)·앞뒤 부호뿐인 수(이온 2−)·
    이미 완전히 괄호로 묶인 식(제53항 y^(4) — 이중 괄호 방지)·단일 명령(\\pi 등).
    """
    expr = expr.strip()
    if not expr:
        return False
    # 이미 완전 괄호 → 추가 묶음 불필요
    if expr.startswith("(") and expr.endswith(")"):
        depth = 0
        for i, ch in enumerate(expr):
            if ch == "(":
                depth += 1
            elif ch == ")":
                depth -= 1
                if depth == 0 and i < len(expr) - 1:
                    break
        else:
            return False
    # 단일 원자: 수(소수·자릿점·앞뒤 부호 허용)·문자(첨자 허용)·미분소·단일 명령·sentinel
    if re.fullmatch(r"[+-]?\d+(?:[.,]\d+)*[+-]?", expr):
        return False
    if re.fullmatch(r"[A-Za-z](?:\^(?:\{[^{}]*\}|[A-Za-z0-9]))?", expr):
        return False
    if re.fullmatch(r"[+-]?d(?:\^(?:\{[^{}]*\}|[A-Za-z0-9]))?[A-Za-z]", expr):
        return False   # 미분소 dx·d²y (제53항 — 곱으로 세지 않음)
    if re.fullmatch(r"\\[a-zA-Z]+|[-]", expr):
        return False
    # 분수 → 묶음 (제7항 3호·제46항 붙임)
    if "\\frac" in expr or "/" in expr:
        return True
    # 이항 +/− (괄호 밖, 양쪽에 피연산자) → 다항식
    depth = 0
    for i, ch in enumerate(expr):
        if ch in ("(", "{", "["):
            depth += 1
        elif ch in (")", "}", "]"):
            depth -= 1
        elif ch in ("+", "-") and depth == 0 and 0 < i < len(expr) - 1:
            return True
    # 곱 판정: 첨자 그룹 제거 후 인수(문자·수·명령·괄호군) 2개 이상 (제22항 >(xy))
    flat = re.sub(r"[\^_](?:\{[^{}]*\}|[A-Za-z0-9])", "", expr)
    factors = re.findall(r"\\[a-zA-Z]+|\d+(?:[.,]\d+)*|[A-Za-z]|\([^()]*\)", flat)
    return len(factors) >= 2


def _letter_braille(ch: str) -> str:
    """단일 영문자 → 알파벳 점자 셀 (수표 없이, 수식 내 로마자 직접 사용)."""
    _MAP = {
        "a": "⠁", "b": "⠃", "c": "⠉", "d": "⠙", "e": "⠑",
        "f": "⠋", "g": "⠛", "h": "⠓", "i": "⠊", "j": "⠚",
        "k": "⠅", "l": "⠇", "m": "⠍", "n": "⠝", "o": "⠕",
        "p": "⠏", "q": "⠟", "r": "⠗", "s": "⠎", "t": "⠞",
        "u": "⠥", "v": "⠧", "w": "⠺", "x": "⠭", "y": "⠽", "z": "⠵",
    }
    return _MAP.get(ch.lower(), ch)


def _extract_brace_content(s: str, start: int) -> tuple[str, int]:
    """s[start] == '{' 위치에서 대응하는 '}' 까지의 내용과 다음 인덱스를 반환."""
    depth = 0
    for i in range(start, len(s)):
        if s[i] == "{":
            depth += 1
        elif s[i] == "}":
            depth -= 1
            if depth == 0:
                return s[start + 1:i], i + 1
    return s[start + 1:], len(s)


def _apply_fracs(latex: str) -> str:
    """\\frac{...}{...} 변환 — 중괄호 중첩 대응 (\\sqrt{...} 안의 \\frac 포함)."""
    result = []
    i = 0
    while i < len(latex):
        if latex[i:i+5] == "\\frac" and i + 5 < len(latex) and latex[i + 5] == "{":
            num_raw, after_num = _extract_brace_content(latex, i + 5)
            if after_num < len(latex) and latex[after_num] == "{":
                den_raw, after_den = _extract_brace_content(latex, after_num)
                num = convert_latex(num_raw)
                den = convert_latex(den_raw)
                den_wrapped = f"{_WRAP_S}{den}{_WRAP_E}" if _needs_wrap(den_raw) else den
                num_wrapped = f"{_WRAP_S}{num}{_WRAP_E}" if _needs_wrap(num_raw) else num
                result.append(f"{den_wrapped}{_FRACTION_MID}{num_wrapped}")
                i = after_den
                continue
        result.append(latex[i])
        i += 1
    return "".join(result)
