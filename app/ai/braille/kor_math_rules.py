"""KOR_MATH 수식 점자 규칙 엔진.

한국 점자 규정 2017 개정 기준 LaTeX → 점자 BRF 변환.

C5-critical: _DIGIT_MAP 오류 시 단위 테스트에서 즉시 차단.
"""

from __future__ import annotations

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
# 수학에서 ( ) 는 ⠷⠾, 텍스트 괄호(⠦⠄ / ⠠⠴)와 다름
_MATH_PAREN_S = "⠷"  # ( (dots 1,2,3,5,6)
_MATH_PAREN_E = "⠾"  # ) (dots 2,3,4,5,6)

# ── 삼각함수 (수학 점자 제47~49항): 접두 6(⠋) + 접미 ─────────────────
_TRIG: dict[str, str] = {
    "arcsin":  "⠁⠗⠉⠋⠎",   # arc6s  (역함수는 arc 접두)
    "arccos":  "⠁⠗⠉⠋⠉",   # arc6c
    "arctan":  "⠁⠗⠉⠋⠞",   # arc6t
    "arccsc":  "⠁⠗⠉⠋⠣",   # arc6<
    "arcsec":  "⠁⠗⠉⠋⠤",   # arc6-
    "arccot":  "⠁⠗⠉⠋⠳",   # arc6\
    "sinh":    "⠋⠎⠓",      # 6sh
    "cosh":    "⠋⠉⠓",      # 6ch
    "tanh":    "⠋⠞⠓",      # 6th
    "csch":    "⠋⠣⠓",      # 6<h
    "sech":    "⠋⠤⠓",      # 6-h
    "coth":    "⠋⠳⠓",      # 6\h
    "sin":     "⠋⠎",       # 6s
    "cos":     "⠋⠉",       # 6c
    "tan":     "⠋⠞",       # 6t
    "csc":     "⠋⠣",       # 6<
    "sec":     "⠋⠤",       # 6-
    "cot":     "⠋⠳",       # 6\
}

# ── 로그 (수학 점자 제46항): _ (⠸, dots 4,5,6) ────────────────────────
# log 기호 = _ = ⠸
# 밑이 숫자: _, + 수표 없이 숫자 (예: log₂ = _,2 = ⠸⠠⠃)
# 밑이 변수: _; + 문자 (예: log_a = _;a = ⠸⠰⠁)
# ln = log_e = _;e = ⠸⠰⠑
_LOG_IND     = "⠸"   # _ (dots 4,5,6) — log 기호
_LOG_NUM_SEP = "⠠"   # , (dot 6) — 밑이 숫자일 때 구분자 (붙임: 수표 없이)
_LN_BRAILLE  = "⠸⠰⠑"  # _;e — 자연로그 ln = log_e (아래첨자 ; = ⠰)

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
_SUP_RE    = re.compile(r"([A-Za-z0-9⠁-⠿])\^\{([^{}]*)\}|([A-Za-z0-9])\^([A-Za-z0-9])")
# 아래첨자: base_{sub} 또는 base_x
_SUB_RE    = re.compile(r"([A-Za-z0-9⠁-⠿])_\{([^{}]*)\}|([A-Za-z0-9])_([A-Za-z0-9])")
# 숫자 (음수 포함, 소수 포함)
_NUM_RE    = re.compile(r"-?\d+(?:[.,]\d+)*")
# \to 또는 \rightarrow
_TO_RE     = re.compile(r"\\(?:to|rightarrow)")
# \lim_{var \to val} 또는 \lim_{var→val}
_LIM_RE    = re.compile(
    r"\\lim_\{([^{}]*?)(?:\\to|→|\\rightarrow)(.*?)\}",
    re.DOTALL,
)
# \log_{base} 또는 \log_{base}(arg)
_LOG_BASE_RE = re.compile(r"\\log_\{([^{}]*)\}")
# \log_base (단일 문자/숫자)
_LOG_BASE1_RE = re.compile(r"\\log_([A-Za-z0-9])")
# \abs{x} 또는 \left| ... \right|
_ABS_RE    = re.compile(r"\\abs\{([^{}]*)\}|\\left\|([^|]*?)\\right\|")
# \sum_{lower}^{upper} 또는 \sum_{lower}
_SUM_RE    = re.compile(r"\\sum_\{([^{}]*)\}(?:\^\{([^{}]*)\})?")


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


def _digit_no_indicator(ch: str) -> str:
    """수표 없이 단일 숫자 변환 (log 밑 숫자 등에 사용, 수학 제46항)."""
    return _DIGIT_MAP.get(ch, ch)


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
# 텍스트/서식 래퍼: \text{…}·\boxed{…}·\mathrm{…} 등 → 내용만 남김(수식 속 한글·식별자 보존)
_TEXT_WRAP_RE = re.compile(r"\\(?:text|boxed|mathrm|mathbf|mathit|operatorname)\{([^{}]*)\}")

# MinerU가 자주 내는 명령 별칭 → 유니코드(이후 substitute_symbols가 점자화)
_CMD_ALIAS = {
    r"\infty": "∞", r"\cdot": "·", r"\times": "×", r"\div": "÷",
    r"\leq": "≤", r"\geq": "≥", r"\neq": "≠", r"\pm": "±", r"\mp": "∓",
    r"\in": "∈", r"\subset": "⊂", r"\cup": "∪", r"\cap": "∩",
    r"\angle": "∠", r"\triangle": "△", r"\cdots": "⋯", r"\dots": "⋯", r"\ldots": "⋯",
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
    s = _TEXT_WRAP_RE.sub(r"\1", s)
    s = _LEFTRIGHT_RE.sub("", s)
    # 공백 축약(명령/첨자/중괄호 주변) — 정규식이 토큰을 인식하도록
    s = _CMD_BRACE_SP_RE.sub(r"\1", s)
    s = _SUBSUP_SP_RE.sub(r"\1", s)
    s = _BRACE_IN_SP_RE.sub("{", s)
    s = _BRACE_OUT_SP_RE.sub("}", s)
    for cmd, uni in _CMD_ALIAS.items():
        s = s.replace(cmd, uni)
    s = _MULTISPACE_RE.sub(" ", s)
    return s.strip()


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
    result = _normalize_latex_input(latex)

    # ── 1. 수학 괄호 치환 (substitute_symbols보다 먼저) ─────────────────
    result = result.replace("(", _MATH_PAREN_S).replace(")", _MATH_PAREN_E)

    # ── 2. 분수: \frac{...}{...} → 분모⠌분자 (수학 제7항, 중첩 중괄호 대응) ──
    result = _apply_fracs(result)

    # ── 2b. n제곱근: \sqrt[n]{내용} → n⠻내용 (수학 제22항 붙임1) ──────
    def _sqrt_n_replace(m: re.Match) -> str:
        n_part = convert_latex(m.group(1))
        inner  = convert_latex(m.group(2))
        inner_w = f"{_MATH_PAREN_S}{inner}{_MATH_PAREN_E}" if _needs_wrap(m.group(2)) else inner
        return f"{n_part}{_SQRT_N_IND}{inner_w}"

    result = _SQRT_N_RE.sub(_sqrt_n_replace, result)

    # ── 2c. 제곱근: \sqrt{내용} → ⠜내용 (수학 제22항) ─────────────────
    def _sqrt_replace(m: re.Match) -> str:
        inner = convert_latex(m.group(1))
        inner_w = f"{_MATH_PAREN_S}{inner}{_MATH_PAREN_E}" if _needs_wrap(m.group(1)) else inner
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

    # \log_{base} — 밑이 중괄호 안에
    def _log_base_replace(m: re.Match) -> str:
        base_raw = m.group(1)
        base = convert_latex(base_raw)
        # 밑이 순수 숫자 한 글자인 경우: _,(숫자, 수표 없이)
        if base_raw.strip().isdigit() and len(base_raw.strip()) == 1:
            return f"{_LOG_IND}{_LOG_NUM_SEP}{_digit_no_indicator(base_raw.strip())}"
        # 밑이 소수/분수인 경우 묶음 괄호 (수학 제46항 붙임1)
        if _needs_wrap(base_raw):
            return f"{_LOG_IND}{_SUBSCRIPT_IND}{_MATH_PAREN_S}{base}{_MATH_PAREN_E}"
        return f"{_LOG_IND}{_SUBSCRIPT_IND}{base}"

    result = _LOG_BASE_RE.sub(_log_base_replace, result)

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
        exp  = convert_latex(m.group(2) or m.group(4) or "")
        exp_w = f"{_MATH_PAREN_S}{exp}{_MATH_PAREN_E}" if _needs_wrap(m.group(2) or m.group(4) or "") else exp
        return f"{base}{_SUPERSCRIPT_IND}{exp_w}"

    result = _SUP_RE.sub(_sup_replace, result)

    # ── 9. 아래첨자: base_{sub} → base⠰sub (수학 제19항, ; = ⠰) ────────────
    def _sub_replace(m: re.Match) -> str:
        base = m.group(1) or m.group(3) or ""
        sub  = convert_latex(m.group(2) or m.group(4) or "")
        sub_w = f"{_MATH_PAREN_S}{sub}{_MATH_PAREN_E}" if _needs_wrap(m.group(2) or m.group(4) or "") else sub
        return f"{base}{_SUBSCRIPT_IND}{sub_w}"

    result = _SUB_RE.sub(_sub_replace, result)

    # ── 10. 기타 LaTeX 명령어 직접 매핑 ────────────────────────────────
    _LATEX_SIMPLE: dict[str, str] = {
        "\\infty":    "⠿",    # ∞ (수학 제50항: =)
        "\\pm":       "⠑⠊",   # ± (수학연산)
        "\\times":    "⠡",    # × (수학 제2항, 폰트 "*"=⠡)
        "\\div":      "⠌⠌",   # ÷ (수학 제2항, 폰트 "//"=⠌⠌)
        "\\cdot":     "⠐",    # · (수학 제2항 붙임, 폰트 '"'=⠐)
        "\\leq":      "⠦⠦",   # ≤ (수학 제4항 8호, 폰트 "66"=⠦⠦)
        "\\geq":      "⠲⠲",   # ≥ (수학 제4항 6호, 폰트 "44"=⠲⠲)
        "\\neq":      "⠨⠒⠒",  # ≠ (수학 제4항 1호, 폰트 ".33"=⠨⠒⠒)
        "\\approx":   "⠈⠊⠈⠊", # ≈ (수학기하)
        "\\equiv":    "⠛⠛",   # ≡ (합동, 기하 제43항)
        "\\sim":      "⠠⠄",   # ∽ (닮음 관련)
        "\\in":       "⠋",    # ∈ (수학 제60항 1호 가)
        "\\notin":    "⠨⠋",   # ∉
        "\\subset":   "⠋⠁",   # ⊂ (수학 제60항 3호)
        "\\supset":   "⠶⠙",   # ⊃
        "\\cup":      "⠬",    # ∪ (수학 제60항 5호 가)
        "\\cap":      "⠩",    # ∩ (수학 제60항 5호 나)
        "\\emptyset": "⠨⠋",   # ∅ (수학 제60항 4호)
        "\\varnothing": "⠨⠋", # ∅
        "\\forall":   "⠠⠄",   # ∀  (TODO: 제61항 9호: .'로 적는다)
        "\\exists":   "⠠⠑",   # ∃
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
        "\\eta":      "⠨⠓",   # η
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
        "\\chi":      "⠨⠉",   # χ
        "\\psi":      "⠨⠽",   # ψ
        "\\omega":    "⠨⠺",   # ω
        "\\cdots":    "⠄⠄⠄",  # ⋯
        "\\ldots":    "⠄⠄⠄",  # ...
        "\\vdots":    "⠠⠠⠠",  # ⋮
        "\\ddots":    "⠨⠨⠨",  # ⋱
        "\\therefore":"⠠⠡",   # ∴ (수학 제65항 2호: ,*)
        "\\because":  "⠈⠌",   # ∵ (수학 제65항 3호: @/)
        "\\rightarrow": "⠒⠕", # → (3o)
        "\\leftarrow":  "⠪⠒", # ← (폰트 "[3"=⠪⠒)
        "\\leftrightarrow": "⠪⠒⠕",  # ↔ (폰트 "[3o")
        "\\Rightarrow":  "⠒⠒⠕",     # ⇒ (명제 제61항, "33o")
        "\\Leftarrow":   "⠐⠉⠉",     # ⇐ (미확인 — 규정 원문 재확인 필요)
        "\\Leftrightarrow": "⠪⠒⠒⠕", # ⇔ (명제 제61항, "[33o")
        # 대문자 그리스 문자
        "\\Alpha":   "⠠⠨⠁", "\\Beta":    "⠠⠨⠃",
        "\\Gamma":   "⠠⠨⠛", "\\Delta":   "⠠⠨⠙",
        "\\Epsilon": "⠠⠨⠑", "\\Zeta":    "⠠⠨⠵",
        "\\Eta":     "⠠⠨⠓", "\\Theta":   "⠠⠨⠹",
        "\\Iota":    "⠠⠨⠊", "\\Kappa":   "⠠⠨⠅",
        "\\Lambda":  "⠠⠨⠇", "\\Mu":      "⠠⠨⠍",
        "\\Nu":      "⠠⠨⠝", "\\Xi":      "⠠⠨⠭",
        "\\Pi":      "⠠⠨⠏", "\\Rho":     "⠠⠨⠗",
        "\\Sigma":   "⠠⠨⠎", "\\Tau":     "⠠⠨⠞",
        "\\Upsilon": "⠠⠨⠥", "\\Phi":     "⠠⠨⠋",
        "\\Chi":     "⠠⠨⠉", "\\Psi":     "⠠⠨⠽",
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

    # ── 11. 숫자 → 수표시 + 점자 ──────────────────────────────────────
    def _num_replace(m: re.Match) -> str:
        return digits_to_braille(m.group())

    result = _NUM_RE.sub(_num_replace, result)

    # ── 11b. 사칙연산 기호 변환 (수학 제2항) — 숫자 변환 후 처리 ──────────
    result = result.replace("+", "⠢")                        # 덧셈표 (수학 제2항, 폰트 "5"=⠢)
    result = re.sub(r"(?<=\s)-(?=\s)", "⠔", result)          # 뺄셈표 (수학 제2항, 폰트 "9"=⠔)
    result = result.replace("=", "⠒⠒")                       # 등호 (수학 제3항, 폰트 "33"=⠒⠒)

    # ── 11c. 문맥 overload 분기: 수식 내 기호는 수학 의미로(텍스트 substitute_symbols와 분리) ──
    # ∼: 수식 논리부정·관계 = ⠈⠔ (명제 제61항, 폰트 "@9"). 텍스트 물결표는 symbol_table 담당.
    # →: 화살표·조건문 = ⠒⠕ (제38·61항, 폰트 "3o").
    result = result.replace("∼", "⠈⠔").replace("→", "⠒⠕")

    # ── 12. 남은 유니코드 수학 기호 → substitute_symbols ────────────────
    result = substitute_symbols(result)

    # ── 13. 잔여 LaTeX 명령어·중괄호 제거 ──────────────────────────────
    result = re.sub(r"\\[a-zA-Z]+\*?", "", result)
    result = re.sub(r"[{}]", "", result)

    # ── 14. 남은 로마자 → 수식 점자 (로마자표 없이, 수학 점자 제12항) ──────
    # 대문자: 대문자표(⠠) + 점자 셀
    result = re.sub(r"[A-Z]", lambda m: "⠠" + _letter_braille(m.group()), result)
    result = re.sub(r"[a-z]", lambda m: _letter_braille(m.group()), result)

    # ── 15. 수식 내 ASCII 공백 → 점자공백(⠀) ─────────────────────────────
    result = result.replace(" ", "⠀")

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
    """분모/분자가 다항식(+,-가 포함된 경우) 이면 묶음 괄호 필요."""
    expr = expr.strip()
    # 단순 숫자·문자 → 괄호 불필요
    if not expr:
        return False
    if re.match(r"^-?[A-Za-z0-9]+$", expr):
        return False
    # + 또는 - (부호 위치 제외) 포함 시 괄호 필요
    # 괄호 안쪽 내용은 제외
    depth = 0
    for ch in expr:
        if ch in ("(", "{", "["):
            depth += 1
        elif ch in (")", "}", "]"):
            depth -= 1
        elif ch in ("+", "-") and depth == 0:
            return True
    return False


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
                den_wrapped = f"{_MATH_PAREN_S}{den}{_MATH_PAREN_E}" if _needs_wrap(den_raw) else den
                num_wrapped = f"{_MATH_PAREN_S}{num}{_MATH_PAREN_E}" if _needs_wrap(num_raw) else num
                result.append(f"{den_wrapped}{_FRACTION_MID}{num_wrapped}")
                i = after_den
                continue
        result.append(latex[i])
        i += 1
    return "".join(result)
