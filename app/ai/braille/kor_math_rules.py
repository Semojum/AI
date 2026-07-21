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
# 정답 도서는 소괄호꼴 ⠦⠴로 적는다 — 재점역 A/B로 확정(수식 164개, ⠦⠴ hit 51 vs
# ⠶⠶ 45 · 유사 58.3 vs 52.0, temp/wrap_variant_ab.py).
# ⚠ 방법론 교훈(2026-07-19): 한때 ⠶로 바꿨다가 되돌렸다. 근거였던 opcode 치환표
# (우리 ⠦ → gold ⠶ 53건)는 **불일치만 세고 일치는 안 보여준다** — ⠦를 내고 gold도
# ⠦인 다수가 표에 안 잡혀 소수 반례가 다수처럼 보였다. 매핑 판정은 치환 빈도가 아니라
# 재점역 A/B로 해야 한다. **인쇄 소괄호도 ⠦⠴** — 도서는 둘을 같은 점형으로 쓴다.
# → book 모드는 ⠦⠴, regulation 모드는 규정 원형 ⠷⠾.
_BOOK_STYLE_ENV = os.environ.get("BRAILLE_STYLE", "book") != "regulation"
# ∴ 관행: 규정 제65항 2호는 ,*(⠠⠡)이나 정답 도서는 ⠌⠄만 쓴다(gold 86회 vs 규정형 0회,
# 2026-07-19 실측). ∵(⠈⠌)은 gold 용례가 없어 규정형 유지.
_THEREFORE = "⠌⠄" if _BOOK_STYLE_ENV else "⠠⠡"
_WRAP_S = "⠦" if _BOOK_STYLE_ENV else "⠷"
_WRAP_E = "⠴" if _BOOK_STYLE_ENV else "⠾"

# 병치 닫음표 생략(T2, 2026-07-20 실측): 묶음이 끝나자마자 빈칸 없이 다른 함수 호출
# 묶음이 시작되면 정답 도서는 **앞 묶음의 닫음표 ⠴를 적지 않는다**.
#   f(x)f(-x) → gold ⠋⠦⠭⠋⠦⠔⠭⠴ (우리 ⠋⠦⠭⠴⠋⠦⠔⠭⠴ — 앞 ')' 없음)
# gold 수학2 127p 전수: 붙여쓴 병치 생략 50 vs 유지 2, 빈칸 낀 산문 문맥은 유지 27로
# 깔끔히 갈린다(output_수학2_page056.brl 4·5·18·35·37행) → **빈칸이 없을 때만** 발동.
# ⚠ 리터럴 중첩 f(g(x))는 대상 아님 — 닫음이 연달아(⠴⠴) 오지 뒤에 함수가 붙지 않으므로
#   패턴이 애초에 걸리지 않는다. gold도 ⠋⠦⠛⠦⠭⠴⠴로 둘 다 유지(p056 58·59행, F1과 정합).
# 규정 제6항에 생략 근거가 없다(예시도 f8x0로 닫는다) → 도서 관행이므로 book 모드 한정.
# ⚠ 적용 위치는 괄호 치환 직후(1단계)여야 한다 — 뒤로 갈수록 ⠴가 로그 내림 밑의 숫자 0
#   (제46항 _DROPPED_DIGIT)·%(⠴⠏)·∘(⠸⠴)와 같은 점형이라 닫음표와 구분되지 않는다.
#   1단계에서는 ⠴가 소괄호뿐이고 뒤따르는 함수명도 아직 ASCII라 오인이 원천 차단된다.
_JUXT_CLOSE_RE = re.compile(rf"{_MATH_PAREN_E}(?=[a-z]{_MATH_PAREN_S})")

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

# ── 정규식 ────────────────────────────────────────────────────────────────
# n제곱근: \sqrt[n]{내용}
_SQRT_N_RE = re.compile(r"\\sqrt\[([^\]]*)\]\{([^{}]*)\}")
# 제곱근: \sqrt{내용}
_SQRT_RE   = re.compile(r"\\sqrt\{([^{}]*)\}")
# 위첨자: base^{exp} 또는 base^x (단일 문자/숫자)
# 둘째 대안 base에 점자 셀 포함(2026-07-19): \sin^2x는 삼각 치환 후 base가 ⠎라
# ASCII만 매칭하던 구판에서 '^'가 기호 캐럿(⠈⠑)으로 오치환됐다(규정 3880행 `6s^#bx` 위반).
# base에 닫는 묶음 `}`·`)`·`]`을 넣는다(2026-07-21): 아래첨자가 먼저 오는 이온
# HCO_{3}^{-}·[Fe(CN)6]^{4-}는 ^ 앞이 닫는 괄호라 구판이 못 잡고 ^가 symbol_table의
# 캐럿(⠈⠑)으로 샜다. 지수에 부호를 허용하는 것도 같은 이유 — 화학 제2항은 이온을
# "위첨자 기호 ^ 뒤에 + 는 5(⠢), - 는 9(⠔)"로 적는다(규정 예시 H+ = ,h^5).
_SUP_RE    = re.compile(r"([A-Za-z0-9⠁-⠿})\]])\^\{([^{}]*)\}"
                        r"|([A-Za-z0-9⠁-⠿})\]])\^([+\-−][A-Za-z0-9]*|[A-Za-z0-9])")
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
# ── MinerU 수식 OCR의 '글자 띄어쓰기' 정규화 ────────────────────────────────
# \operatorname* { l i m } → \lim  ·  { l i m } → {lim}  ·  { = } → =
_OPERATORNAME_RE = re.compile(r"\\operatorname\s*\*?\s*\{([^{}]*)\}")
_SPACED_LETTERS_RE = re.compile(r"\{\s*([a-zA-Z](?:\s+[a-zA-Z])+)\s*\}")
_BRACED_OP_RE = re.compile(r"\{\s*([-+=<>*/])\s*\}")

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
# LaTeX 널 구분자 `\left.` / `\right.` — 점(.)은 "구분자 없음"을 뜻하는 **문법**이지 문자가
# 아니다. _LEFTRIGHT_RE는 명령만 지우고 점을 남겨, 최종 점자에 ASCII '.'이 그대로 실렸다
# (연립식 `\left\{…\right.` 형태, 코퍼스 잔류 '.' 55건 중 최다). 명령과 점을 함께 지운다.
# ⚠ _LEFTRIGHT_RE보다 **먼저** 돌아야 한다 — 뒤에 두면 점만 남아 매칭이 안 된다.
_W2C_NULL_DELIM_RE = re.compile(r"\\(?:left|right)\s*\.")
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
# 대문자 그리스 접두(F3, 2026-07-20 실측): 규정 제30항·수학 제25항은 ,.(⠠⠨)이나
# 도서 관행은 대문자표 ⠠를 생략 — gold 수학2에서 ⠨⠎ 426·⠨⠙ 142회 vs ⠠⠨ 계열 3회
# (Σ=.S·Δx=.DX, output_수학2_page091.brl 원문 실측). regulation 모드는 규정형 유지.
_CAP_GREEK = "⠨" if _IS_BOOK_STYLE else "⠠⠨"
# 소문자 그리스 접두(2026-07-21 실측): 규정 제30항·수학 제13항은 `.x`(⠨)이나 도서는
# `@x`(⠈)를 쓴다 — gold 판정가능 265건 중 ⠈ 263 vs ⠨ 2(val)·24 vs 0(dev), 전부 수학2.
# output_수학2_page028.brl 원시 BRF에서 θ=`@?`와 ≠=`.3`이 같은 줄에 공존 → 도서가 두
# 접두를 의도적으로 구분해 쓴다는 증거(대문자 그리스는 ⠨ 유지 = _CAP_GREEK).
# ⚠ 모수가 작다: val 663회·dev 179회(gold 152.7만/29.0만 셀)라 CER 상한 기여는
# +0.04~0.06%p뿐이다. 규정 정합이 아니라 관행 정합 목적의 변경이다.
_LC_GREEK = "⠈" if _IS_BOOK_STYLE else "⠨"
_SUM_BASE = _CAP_GREEK + "⠎"   # 총합 Σ (수학 제25항 ,.S / 도서 관행 .S)
# ≠(F4, 2026-07-20 실측): 규정 수학 제4항 1호는 .33(⠨⠒⠒)이나 도서 관행은 .3(⠨⠒)
# — gold 수학2에서 .3 91회 vs .33 0회(x≠1=`X.3#A`·f(x)≠0=`F8X0.3#J` 원문 실측).
_NEQ = "⠨⠒" if _IS_BOOK_STYLE else "⠨⠒⠒"
_SYS_ENV_RE = re.compile(
    r"\\left\s*\\?\{\s*\\begin\{array\}(?:\{[^{}]*\})?(.*?)\\end\{array\}(?:\s*\\right\s*\.?)?"
    r"|\\begin\{cases\}(.*?)\\end\{cases\}", re.DOTALL)

# \text{한글} 점역용 훅(translator가 런타임 주입 — 순환 import 회피).
_text_hook = None

# 잔류 정화용 **평문** 훅(translator._braillify 주입). _text_hook(=translate_tagged_text)은
# 수식 라우팅(inline_math.wrap)을 다시 타므로 잔류 한 조각을 넘기면 convert_latex로
# 되돌아와 무한 재귀가 된다. 이 훅은 braillify만 부르는 비재귀 경로다.
_w2c_plain_hook = None


def w2c_register_plain_hook(fn) -> None:
    """비재귀 평문 점역 훅 주입(잔류 정화 전용). translator가 로드 시 호출."""
    global _w2c_plain_hook
    _w2c_plain_hook = fn


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
# 보기 항목 머리의 낱자 + 마침표("ㄱ. f(x)=x[x]"). _BARE_KOR_RE는 낱자만 떼어가고 점을
# 남겨 최종 점자에 ASCII '.'이 실렸다. 텍스트 경로는 translator._JAMO_MARK_RE가 이미
# 같은 형태를 처리하므로 **점까지 묶어** 훅에 넘겨 같은 결과를 얻는다.
# 정답 실측: 수학2 p063·p064·p070 gold가 "ㄱ."을 ⠿⠁ + 빈칸으로 적고 마침표 셀을 안 쓴다
# (같은 페이지 선택지 줄의 쉼표는 ⠐로 또렷이 구분됨 — '⠼⠲ ⠿⠁⠐ ⠿⠒' = "④ ㄱ, ㄴ").
_W2C_JAMO_ITEM_RE = re.compile(r"(?<![가-힣A-Za-z0-9])([ㄱ-ㅎ])\s*\.(?=\s|$)")


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
    latex = _W2C_JAMO_ITEM_RE.sub(lambda m: _stash(m.group(0)), latex)  # "ㄱ." 통째로
    latex = _BARE_KOR_RE.sub(lambda m: _stash(m.group(0)), latex)
    return latex, store


def _restore_text(result: str, store: list[str]) -> str:
    # ★ 내림차순 — 중첩 \text(`\text{|\(\text{旦}\text{로}\)}`)는 안쪽이 먼저 stash돼
    #   **바깥 저장값이 안쪽 sentinel을 품는다**. 오름차순으로 되돌리면 안쪽 인덱스를
    #   이미 지나친 뒤에 그 sentinel이 삽입돼 U+E001 등이 최종 점자에 그대로 실렸다
    #   (수학2 p053 실측). 내림차순이면 품은 sentinel이 삽입된 뒤 차례가 온다.
    for i in range(len(store) - 1, -1, -1):
        result = result.replace(chr(0xE000 + i), store[i])
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

# ── MinerU 백슬래시 유실 복원 (2026-07-21 실측) ──────────────────────────
# MinerU 수식 OCR이 명령의 `\`를 잃고 이름만 남기는 사례가 있다.
#   `$ textcircled{7}$` · `$ frac{1}{2600}$` · `$ cdots$` · `$2n rightarrow 2n$`
# `\`가 없으니 아래 어느 정규식에도 안 걸리고 **명령 이름이 로마자 점자로 그대로
# 박혀 나간다** — ` textcircled{7}` → ⠞⠑⠭⠞⠉⠊⠗⠉⠇⠑⠙⠦⠂⠼⠛⠐⠴("textcircled(7)").
# 셀 유실보다 나쁘다(원문에 없는 잡음을 만들어냄). 전 코퍼스 실측 87회/14p.
#
# 오탐 방지 3중:
#   (1) 중괄호를 끄는 이름(`frac{`)은 영어 단어가 될 수 없다 → 무조건 복원.
#   (2) 맨 이름은 **영어 동음이의어를 뺀** 목록만(to·in·left·right·text·end·begin·
#       log·min·max·bar·hat·dot 제외). 외국어 지문의 통화 표기 `$50 … spending to $`가
#       `\to`로 깨지는 것을 막는다(실측 val 외국어 p175).
#   (3) 그래도 남는 homograph(times·square·star·circ·sim)를 위해 **산문 가드** —
#       명령이 아닌 영단어가 3개 이상이면 수식이 아니라 산문으로 보고 통째로 건너뛴다.
_LOSTBS_BRACED = ("textcircled|operatorname|widetilde|underline|overline|widehat|"
                  "mathrm|mathbf|mathit|mathbb|mathcal|mathsf|textbf|textit|"
                  "boxed|dfrac|tfrac|frac|sqrt|vec|hat|bar|tilde")
_LOSTBS_BARE = ("longrightarrow|Longrightarrow|rightarrow|leftarrow|Rightarrow|Leftarrow|"
                "varepsilon|epsilon|triangle|parallel|infty|partial|approx|equiv|propto|"
                "varphi|lambda|sigma|omega|Gamma|Delta|Theta|Lambda|Sigma|Omega|"
                "alpha|beta|gamma|delta|zeta|theta|iota|kappa|"
                "qquad|quad|cdots|ldots|cdot|times|circ|square|bullet|star|perp|angle|"
                "hline|fallingdotseq|doteq|neq|leq|geq|div|pm|mp|sim|"
                "xi|pi|rho|tau|phi|chi|psi|eta|mu|nu")
_LOSTBS_BRACED_RE = re.compile(r"(?<![\\A-Za-z])(" + _LOSTBS_BRACED + r")(?=\s*\{)")
_LOSTBS_BARE_RE = re.compile(r"(?<![\\A-Za-z])(" + _LOSTBS_BARE + r")(?![A-Za-z])")
_LOSTBS_ALL = set((_LOSTBS_BRACED + "|" + _LOSTBS_BARE).split("|"))
_PROSE_WORD_RE = re.compile(r"(?<![\\A-Za-z])[A-Za-z]{3,}(?![A-Za-z])")


def _restore_lost_backslash(s: str) -> str:
    """MinerU가 잃은 LaTeX 백슬래시를 되살린다(위 주석의 3중 가드)."""
    if len([w for w in _PROSE_WORD_RE.findall(s) if w not in _LOSTBS_ALL]) >= 3:
        return s                      # 산문 — 손대지 않는다
    s = _LOSTBS_BRACED_RE.sub(lambda m: "\\" + m.group(1), s)
    return _LOSTBS_BARE_RE.sub(lambda m: "\\" + m.group(1), s)


# ── 원문자 \textcircled{…} (한국점자규정 제64항) ────────────────────────
# 규정 원문: "동그라미 숫자는 수표 뒤에 숫자의 점형을 한 단 내려 적고, 그 밖의
#            동그라미 문자는 7 7으로, 네모 문자는 _8 0l으로 묶어 나타낸다."
# 규정 예시 디코드: ① = #1(⠼⠂) · ㉠ = 7=a7(⠶⠿⠁⠶) · ⓐ = 70a7(⠶⠴⠁⠶).
# 기존 translator의 유니코드 경로(①→⠼⠂, ⓐ→⠶⠴⠁⠶)와 같은 점형을 낸다 — 원문자가
# 유니코드로 왔든 \textcircled로 왔든 출력이 갈리지 않게.
_CIRCLED_OPEN, _CIRCLED_CLOSE = "⠶", "⠶"
_ROMAN_CELL = dict(zip("abcdefghijklmnopqrstuvwxyz",
                       "⠁⠃⠉⠙⠑⠋⠛⠓⠊⠚⠅⠇⠍⠝⠕⠏⠟⠗⠎⠞⠥⠧⠺⠭⠽⠵"))
_TEXTCIRCLED_RE = re.compile(r"\\textcircled\s*\*?\s*\{([^{}]*)\}")

# ── 원문자 자모 ㉠~㉣의 OCR 오독 복원 (2026-07-21 원본 PDF 전수 대조) ──────
# MinerU가 원 안의 **한글 자모**를 자형이 닮은 로마자·숫자·기호로 읽는다. 전 코퍼스
# \textcircled 출현 7페이지를 원본 PDF 크롭으로 육안 확인한 결과:
#   사회문화 p052  7·L·E·B = ㉠㉡㉢㉣      언어 p231  T·L·E = ㉠㉡㉢
#   언어 p171     7·L    = ㉠㉡            수학2 p058 \neg  = ㉠
# 자형 대응: ㄱ→7·T·¬ · ㄴ→L · ㄷ→E · ㄹ→B.
#
# ★ 반례도 같은 방법으로 확인했다 — 아래 둘은 **고치면 안 된다**:
#   생물 p089  \textcircled{a} = 진짜 ⓐ (원문에 동그라미 소문자 a가 실재)
#   수학2 p040 \textcircled{\circ} = 원문자가 아니라 "이"의 오독(ㅇ+ㅣ)
# 그래서 **대문자 로마자·기호만** 자모로 돌리고 소문자(ⓐ~ⓩ)와 숫자는 손대지 않는다.
# 근거: 코퍼스 유니코드 원문자 로마자는 소문자 274회(ⓐ98·ⓑ66·ⓒ48·ⓓ33·ⓔ29) 대
#       대문자 3회뿐이고, 그 3회(Ⓥ·Ⓓ·Ⓐ)마저 p052 크롭에서 ㉡·㉢의 오독으로 확인됐다.
#       "7"은 유니코드 ⑦이 125회로 ⑥ 43회보다 3배 많은 역전이 나는데, ①…⑦ 순번이라면
#       불가능한 분포다 — 초과분이 곧 ㉠ 오독이다(translator._CIRCLED_JAMO_MISREAD와 동일 판단).
# 숫자는 매핑하지 않는다: 수학2 p020의 \textcircled{2}는 실제로 ㉣이지만(크롭 확인),
#   ②는 선택지로 흔해서 일반 매핑하면 진짜 ②를 조용히 망친다. 잔여 오류로 남긴다.
#
# 점형은 유니코드 경로와 1:1로 맞춘다(translator 실측: ㉠⠿⠁ ㉡⠿⠒ ㉢⠿⠔ ㉣⠿⠂ — 제8항 온표+자모).
_TC_JAMO_CELLS = {
    "7": "⠿⠁", "T": "⠿⠁", "\\neg": "⠿⠁",   # ㉠
    "L": "⠿⠒",                              # ㉡
    "E": "⠿⠔",                              # ㉢
    "B": "⠿⠂",                              # ㉣
}


def _textcircled_repl(m: re.Match) -> str:
    """\\textcircled{X} → 제64항 원문자 점형. 못 다루는 인자는 원문 보존."""
    arg = m.group(1).strip()
    if arg in _TC_JAMO_CELLS:                          # ㉠~㉣ 자형 오독 복원
        return _TC_JAMO_CELLS[arg]
    if arg.isdigit():                                  # ① ⑩ ㉘ — 수표 + 내린 숫자
        return "⠼" + "".join(_DROPPED_DIGIT[c] for c in arg)
    if len(arg) == 1 and arg.lower() in _ROMAN_CELL:   # ⓐ Ⓐ — 7 로마자표 x 7
        cap = "⠠" if arg.isupper() else ""
        return _CIRCLED_OPEN + "⠴" + cap + _ROMAN_CELL[arg.lower()] + _CIRCLED_CLOSE
    return arg                                         # 그 밖 — 인자만 남긴다


def _normalize_latex_input(latex: str) -> str:
    """MinerU/마크다운식 LaTeX를 convert_latex가 다룰 수 있게 정규화.

    코드펜스·`$$` 구분자 제거, `\\frac {1}{a _ {i}}`류 공백 축약, `\\left( … \\right)`의
    \\left/\\right 제거(절댓값 `\\left| … \\right|`은 보존), 간격 명령·줄바꿈 정리.
    """
    s = _CODE_FENCE_RE.sub("", latex)
    s = _MATH_DELIM_RE.sub(" ", s)
    # ★ 다른 어떤 규칙보다 먼저 — 백슬래시가 없으면 아래 정규식이 하나도 안 걸린다.
    s = _restore_lost_backslash(s)
    # 원문자(제64항). \text{…} 래퍼보다 먼저 잡아야 \textcircled가 \text로 오인되지 않는다.
    s = _TEXTCIRCLED_RE.sub(_textcircled_repl, s)
    # MinerU 수식 OCR은 토큰을 글자 단위로 띄어 낸다 — `\operatorname* { l i m }`,
    # `{ = }`, `f ^ { \prime } ( a )`. 이 형태를 못 풀면 \lim이 낱글자 l·i·m으로
    # 흩어져 수식이 통째로 깨진다(수학2 실측 2026-07-19: operatorname 88건·
    # 띄어쓴 글자 116건·{ = } 92건, 해당 페이지 정렬률 2~7%).
    s = _OPERATORNAME_RE.sub(lambda m: "\\" + re.sub(r"\s+", "", m.group(1)), s)
    s = _SPACED_LETTERS_RE.sub(lambda m: "{" + re.sub(r"\s+", "", m.group(1)) + "}", s)
    s = _BRACED_OP_RE.sub(lambda m: m.group(1), s)
    # 괄호 안쪽과 쉼표 앞의 공백도 MinerU가 넣은 것이다: `( x )` → `(x)`, `α , β` → `α, β`.
    # 이 단계는 원문 LaTeX의 군더더기 공백만 지운다 — 제51·57항의 구조 칸은 뒤 단계에서
    # 따로 넣으므로 영향받지 않는다.
    s = re.sub(r"(?<=[(\[])\s+|\s+(?=[)\]])", "", s)
    s = re.sub(r"\s+(?=[,;])", "", s)
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
    s = _W2C_NULL_DELIM_RE.sub("", s)   # \left. \right. — 널 구분자는 점까지 제거
    s = _LEFTRIGHT_RE.sub("", s)
    # 공백 축약(명령/첨자/중괄호 주변) — 정규식이 토큰을 인식하도록
    s = _CMD_BRACE_SP_RE.sub(r"\1", s)
    s = _SUBSUP_SP_RE.sub(r"\1", s)
    s = _BRACE_IN_SP_RE.sub("{", s)
    s = _BRACE_OUT_SP_RE.sub("}", s)
    # 명령 경계까지 봐야 한다 — 단순 replace면 `\le`가 **`\left`의 앞부분을 먹어**
    # `≤ft`가 된다(2026-07-19 실측 `⠖⠖⠋⠞`, \le 별칭 추가 때 생긴 회귀).
    # 뒤에 영문자가 오면 다른 명령이므로 치환하지 않는다.
    for cmd, uni in sorted(_CMD_ALIAS.items(), key=lambda kv: -len(kv[0])):
        s = re.sub(re.escape(cmd) + r"(?![a-zA-Z])", uni, s)
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


# ── 비점자 잔류 정화 (2026-07-21, w2c) ──────────────────────────────────────
# convert_latex는 처리 못 한 문자를 **원문 그대로 통과**시킨다. 그 결과 최종 점자에
# ASCII가 섞여 나갔다(전 코퍼스 실측 55줄: '.' 47 · '_' 6 · PUA 2 · '?' 1).
# 점역사에게는 즉시 이물질로 보이고, BRF로는 점형이 아닌 바이트가 된다.
# 여기서 마지막으로 훑어 braillify가 아는 문자는 점자로 바꾸고, 모르는 것(미복원 PUA·
# 제어문자)은 버린다. 정상 경로가 이미 처리한 것은 점자 셀이라 이 그물에 걸리지 않는다.
# ⚠ 근본 원인은 개별 단계에서 고치는 게 우선이고(위 _W2C_NULL_DELIM_RE·_W2C_JAMO_ITEM_RE),
#   이건 놓친 것을 붙잡는 안전망이다 — 여기서만 막으면 점형이 어긋난 채 통과할 수 있다.
# ★ _protect_text의 PUA sentinel(U+E000~)은 **반드시 제외**한다. convert_latex는 분수
#   분자·근호 안에서 자기 자신을 재귀 호출하는데, 그 하위 호출의 _text_store는 비어 있어
#   바깥 호출의 sentinel이 복원되지 않은 채 지나간다(설계상 정상 — 바깥이 복원한다).
#   제외하지 않으면 하위 호출의 이 그물이 sentinel을 먹어 한글이 통째로 깨진다
#   (실측: `\frac{(거리)}{(속력)}` → ⠠⠭⠐⠱⠁·⠈⠎⠐⠕ 가 ⠰⠤·⠤⠄ 로, 수학2 p001).
_W2C_RESIDUE_RUN_RE = re.compile(r"[^⠀-⣿\s-]+")


def _w2c_sweep_residue(result: str) -> str:
    """최종 점자열에 남은 비점자 문자를 점자로 치환하거나 제거한다."""
    if _w2c_plain_hook is None:
        return result

    def _rep(m: re.Match) -> str:
        try:
            out = _w2c_plain_hook(m.group())
        except Exception:  # noqa: BLE001 — 정화 실패는 제거로 수렴(빈 결과는 상위가 막음)
            return ""
        return "".join(ch for ch in out if "⠀" <= ch <= "⣿")

    return _W2C_RESIDUE_RUN_RE.sub(_rep, result)


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


# ══════════════════════════════════════════════════════════════════════════
# convert_latex 단계 함수
# ══════════════════════════════════════════════════════════════════════════
# **순서가 곧 의미인 파이프라인**이다. 각 함수는 str→str이고 상태를 갖지 않는다.
# 독스트링의 [입력]/[출력]은 그 단계가 전제하는 표현 형태와 보장하는 표현 형태다.
# 새 규칙을 어디에 넣을지는 convert_latex 독스트링의 단계표로 판정한다.
#
# 함수명 접두 = 원래 단계 번호(주석에 쓰이던 0b·1a·11e 등). 번호는 **실행 순서와
# 다를 수 있다** — 11e가 11d보다 먼저 돈다. 파이프라인 나열 순서가 진실이다.


def _stage0b_nth_root(result: str) -> str:
    r"""0b. n제곱근 \sqrt[n]{내용} → n⠻내용 (수학 제22항 [붙임1]).

    [입력] 정규화된 LaTeX. **대괄호 [ ]가 아직 ASCII이고 소괄호도 ASCII다.**
    [출력] \sqrt[n]{…} 소멸. 근수 n·내용은 재귀 변환되어 완성 점자.

    ⚠ 1단계(대괄호 치환)보다 반드시 먼저다 — 뒤로 가면 [n]이 대괄호 점형 ⠷⠄…⠠⠾로
      선점된다(2026-07-19 정정). 또한 _needs_wrap이 ASCII 괄호를 보고 판정할 수 있는
      **유일한 단계**다(1단계 이후 호출자들은 점형 괄호를 넘기게 된다).
    """
    def _sqrt_n_replace(m: re.Match) -> str:
        n_part = convert_latex(m.group(1))
        inner  = convert_latex(m.group(2))
        inner_w = _wrap_ins(inner) if _needs_wrap(m.group(2)) else inner
        return f"{n_part}{_SQRT_N_IND}{inner_w}"

    return _SQRT_N_RE.sub(_sqrt_n_replace, result)


def _stage1_math_brackets(result: str) -> str:
    """1. 수학 괄호 → 점형 · 괄호 인접 공백 정리 · 1a. 병치 닫음표 생략(T2 관행).

    [입력] 괄호가 ASCII ( ) [ ] \\{ \\}. 함수명·변수도 ASCII. substitute_symbols 이전.
    [출력] 괄호가 전부 점형(소괄호 ⠦⠴ · 대괄호 ⠷⠄…⠠⠾ · 중괄호 ⠶). 괄호 인접 군더더기
      공백 제거. book 모드면 병치 닫음표(⠴) 생략까지 끝난 상태.

    ⚠ **문맥 소실 지점 1 — 괄호의 정체성이 여기서 사라진다.** 이 단계 이후 ⠦·⠴는
      다의(多義)다: 점역자 묶음표(_WRAP_S/E)·로그 내림밑 8(⠦)/0(⠴)·%(⠴⠏)·∘(⠸⠴)가
      뒤 단계에서 같은 셀을 만든다. 그래서 '괄호를 보는' 규칙은 전부 이 단계 안에서
      끝내야 한다. T2(병치 닫음표 생략)를 최종 셀열 단계에 넣었더니 log₁₀의 밑 0(⠴)을
      닫음표로 오인해 log₁로 깨진 것이 이 소실의 실제 사고 사례다(2026-07-20).
      여기서는 ⠴가 소괄호뿐이고 뒤따르는 함수명도 아직 ASCII라 오인이 원천 차단된다.
    """
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
    # 1a. 병치 닫음표 생략(T2 관행) — 위 공백 정리로 병치가 확정된 뒤에 적용한다.
    # 대문자 함수명(F(x)G(x))은 제외: 닫음을 지우면 앞 인수와 붙어 연속 대문자가 되어
    # 14단계의 대문자 단어표 ⠠⠠가 잘못 붙는다(P(A)P(B) → "AP"). gold 실측 모수도 소문자다.
    if _BOOK_STYLE_ENV:
        result = _JUXT_CLOSE_RE.sub("", result)
    return result


def _stage1b_accents(result: str) -> str:
    """1b. 문자 위 기호 (제23·35~38·64·65항).

    [입력] \\vec·\\bar·\\hat 등이 아직 LaTeX 명령. 내용의 대소문자가 살아 있다.
    [출력] 해당 명령 소멸, 내용은 재귀 변환된 완성 점자에 기호가 앞/뒤로 붙은 형태.

    prefix형(벡터·선분 계열)은 기호를 앞에, postfix형(바·햇·점)은 뒤에 적는다.
    가로바는 내용이 연속 대문자(선분 AB, 제35항)면 prefix, 아니면 켤레·평균(제23항) postfix
    — **14단계가 로마자를 점형으로 바꾸기 전이라 대문자 판정이 가능한 구간**이다.
    """
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

    return _ACC_POSTFIX_RE.sub(_acc_postfix, result)


def _stage1c_permutation(result: str) -> str:
    """1c. 순열·조합 (제62항): nPr → ,P(n r) — P/C/H, 중복순열 \\Pi는 ,.P.

    [입력] 아래첨자 _ 가 아직 ASCII(8·9단계 이전). 좌우 첨자 구조가 원형대로 남아 있다.
    [출력] 순열·조합 묶음이 완성 점자. 첨자 언더스코어 소비됨.

    ⚠ 8·9단계(위/아래첨자)보다 먼저여야 한다 — 뒤로 가면 _{n}이 일반 아래첨자로
      선점돼 순열 패턴이 성립하지 않는다.
    """
    def _perm_replace(m: re.Match) -> str:
        low = convert_latex(_unbrace(m.group(1)))
        letter = m.group(2)
        up = convert_latex(_unbrace(m.group(4)))
        head = "⠠⠨⠏" if letter is None else "⠠" + _letter_braille(letter.lower())
        return f"{head}{_WRAP_S}{low}{_SP}{up}{_WRAP_E}"

    return _PERM_RE.sub(_perm_replace, result)


def _stage1d_left_scripts(result: str) -> str:
    """1d. 왼쪽 첨자 (제18·19항 2호): {}^{t}A → ⠘(t)A — 첨자는 항상 묶음.

    [입력] 빈 중괄호 {} 마커와 ^·_ 가 ASCII로 살아 있음.
    [출력] 왼쪽 첨자가 묶음 점자로 확정. 남은 ^·_ 는 일반 첨자(8·9단계) 몫.
    """
    result = _LEFT_SUP_RE.sub(
        lambda m: f"⠘{_WRAP_S}{convert_latex(_unbrace(m.group(1)))}{_WRAP_E}{m.group(2)}",
        result)
    return _LEFT_SUB_RE.sub(
        lambda m: f"⠰{_WRAP_S}{convert_latex(_unbrace(m.group(1)))}{_WRAP_E}{m.group(2)}",
        result)


def _stage1e_integral_range(result: str) -> str:
    """1e. 정적분 범위 (제57·58항): ∫_a^b → ⠮⠰a⠀b⠀ (위끝은 ⠘ 위첨자가 아님).

    [입력] ∫∬∮ 유니코드(정규화가 \\int을 이미 유니코드로 바꿔 둠) + ASCII _ ^.
    [출력] 적분 기호·범위가 완성 점자. 범위 구분 칸은 sentinel _SP로 넣어 11e의
      연산 붙임에 지워지지 않게 보호한다.

    ⚠ 8단계(위첨자)보다 먼저다 — 적분 위끝은 위첨자표 ⠘가 아니라 칸 구분이라
      일반 위첨자로 선점되면 규정 위반이 된다.
    """
    def _int_replace(m: re.Match) -> str:
        base = _INT_BASE[m.group(1)]
        low = convert_latex(_unbrace(m.group(2)))
        up = convert_latex(_unbrace(m.group(3))) if m.group(3) else ""
        return f"{base}⠰{low}{_SP}{up}{_SP}" if up else f"{base}⠰{low}{_SP}"

    result = _INT_RANGE_RE.sub(_int_replace, result)
    result = result.replace("∫", "⠮").replace("∬", "⠮⠮")
    # 정적분 값 대괄호 [F(x)]_a^b (제57항): 닫는 대괄호 뒤 범위도 칸 구분
    return _BRACKET_RANGE_RE.sub(
        lambda m: f"⠠⠾⠰{convert_latex(_unbrace(m.group(2)))}"
                  + (f"{_SP}{convert_latex(_unbrace(m.group(3)))}" if m.group(3) else ""),
        result)


def _stage1f_trig_arg_group(result: str) -> str:
    """1f. 삼각함수 인수 묶음 (제47항 [붙임]): sin 3x → 6s(3x) — 곱·분수 인수만.

    [입력] 삼각함수가 아직 \\sin 등 LaTeX 명령(5단계 치환 이전)이고 인수가 원문 그대로.
    [출력] 인수에 묶음표(_WRAP_S/E)가 씌워진 상태. 명령 자체는 아직 LaTeX.

    ⚠ 5단계(삼각 치환)보다 먼저다 — 명령이 점형이 되면 인수 경계를 이 정규식으로
      다시 잡을 수 없다.

    ★ book 모드에서는 **적용하지 않는다**(2026-07-21). 규정 제47항 [붙임]은 "각이 곱,
      다항식 등으로 표시되어 있을 경우에는 묶음 괄호로 묶는다"(sin 3x → 6s(#cx))이지만
      정답 도서는 묶지 않는다 — val+dev gold 전수 실측 삼각함수 **1095회 중 묶음 60 :
      비묶음 1035(94.5%)**. 그 60건도 `sin(α+β)`처럼 **묵자에 이미 괄호가 있는** 경우라
      이 단계가 아니라 1단계(소괄호 치환)가 만든다 — 즉 여기를 꺼도 그 60건은 그대로
      유지된다(`_TRIG_ARG_RE`는 `\\sin (…)` 형태를 매칭하지 않음, 실측 확인).
      ⚠ 이 규칙이 안 걸리던 게 아니다: MinerU는 `\\sin 2 x`처럼 띄어 내보내는데
      0a단계가 공백을 지운 뒤 매칭되므로, **원문 LaTeX로 정규식을 재보면 발동 건수가
      크게 과소 집계된다**(직전 라운드가 "429개 중 7개"로 오판한 원인). 실제 발동은
      429요소 중 25요소.
      `regulation` 모드는 규정 그대로 묶는다 — _NEQ·_CAP_GREEK와 동일한 관행 게이팅.
    """
    if _IS_BOOK_STYLE:
        return result
    return _TRIG_ARG_RE.sub(
        lambda m: f"{m.group(1)}{m.group(2) or ''}{_WRAP_S}{m.group(3)}{_WRAP_E}", result)


def _stage2c_sqrt(result: str) -> str:
    r"""2c. 제곱근 \sqrt{내용} → ⠜내용 (수학 제22항; n제곱근은 0b에서 선처리).

    [입력] \sqrt{…}가 남아 있음. 분수(2단계)는 이미 풀려 있어 근호 안 분수도 완성 점자.
    [출력] 근호가 완성 점자. 내용은 재귀 변환 + 필요 시 묶음.
    """
    def _sqrt_replace(m: re.Match) -> str:
        inner = convert_latex(m.group(1))
        inner_w = _wrap_ins(inner) if _needs_wrap(m.group(1)) else inner
        return f"{_SQRT_IND}{inner_w}"

    return _SQRT_RE.sub(_sqrt_replace, result)


def _stage3_limit(result: str) -> str:
    """3. 극한 \\lim_{x \\to val} → lim;x ` val ` 함수 (제51항) + 단독 화살표.

    [입력] \\lim_{…\\to…} 구조가 원형. 화살표가 아직 \\to/\\rightarrow 또는 →.
    [출력] 극한 머리가 완성 점자. 구분 칸은 **일반 공백**(sentinel 아님)이라
      11e 연산 붙임의 영향권에 들어간다 — 화살표 ⠒⠕를 11e 대상에서 뺀 이유다.
    """
    def _lim_replace(m: re.Match) -> str:
        var = convert_latex(m.group(1).strip())
        val = convert_latex(m.group(2).strip())
        # 도서 관행(2026-07-19 실측): gold의 lim 420건 **전부** 화살표 없이
        # `lim⠰변수 점근값 본식`으로 적는다(0%). 규정 제51항은 화살표를 명시하므로
        # regulation 모드는 규정형을 유지하고 book 모드만 생략한다.
        if _IS_BOOK_STYLE:
            return f"{_LIM_BRAILLE}{_SUBSCRIPT_IND}{var} {val} "
        return f"{_LIM_BRAILLE}{_SUBSCRIPT_IND}{var} {_ARROW_RIGHT} {val} "

    result = _LIM_RE.sub(_lim_replace, result)
    # 단독 \to / \rightarrow → 화살표
    return _TO_RE.sub(_ARROW_RIGHT, result)


def _stage4_log(result: str) -> str:
    """4. 로그 (제46항): \\ln · \\log_{밑} · \\log_밑 · 맨 \\log.

    [입력] \\log 명령이 남아 있고 **진수 괄호는 이미 점형 ⠦…⠴**(1단계 통과분).
      밑은 아직 ASCII 숫자/문자라 isdigit() 판정이 가능하다.
    [출력] 로그가 완성 점자. **내림 숫자 밑이 여기서 생긴다(_DROPPED_DIGIT)** —
      8=⠦·0=⠴라 이 시점 이후 ⠦⠴를 괄호로 보는 규칙은 만들면 안 된다(문맥 소실 1 참조).

    진수(⠦…⠴)는 재귀 없이 제자리 재방출 — 내용은 이후 단계(숫자·기호 변환)가 이어서 처리한다.
    """
    # \ln → log_e
    result = result.replace("\\ln", _LN_BRAILLE)

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
            return f"{_LOG_IND}{_SUBSCRIPT_IND}{_wrap_ins(base)}{tail}"
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
    return result.replace("\\log", _LOG_IND)


def _stage5_trig(result: str) -> str:
    """5. 삼각함수 (제47~49항) + 5b. 함수 기호 뒤 단일 인수 붙임.

    [입력] \\sin·\\cosh·\\arcsin 등이 LaTeX 명령. 인수 묶음(1f)은 이미 씌워짐.
    [출력] 삼각함수가 완성 점자. 함수 기호와 인수 사이의 LaTeX 관습 공백 제거.

    긴 이름(arcsin 등)을 먼저 처리해 substr 충돌을 막는다(_TRIG 삽입 순서가 곧 우선순위).
    """
    for name, braille in _TRIG.items():
        result = result.replace(f"\\{name}", braille)

    # 5b. 규정 예시가 전부 붙임(6shx·6sx^#c·arc6s,A·LNx·#b6cx·!f8x0).
    # LaTeX 관습 공백("\sin x")을 제거한다.
    # 대상: 삼각(⠖?·⠖?⠓)·ln(⠇⠝)·맨 log(⠸)·적분(⠮) 뒤 한 칸.
    return re.sub(r"(⠖[⠎⠉⠞⠣⠤⠳]⠓?|⠇⠝|⠮⠮?|⠸)[ ]+(?=\S)", r"\1", result)


def _stage6_abs(result: str) -> str:
    """6. 절댓값 (수학 제21항): \\abs{} · \\left|…\\right| · |…| → ⠳…⠳.

    [입력] 수직바가 아직 ASCII `|`. 절댓값 쌍이 짝을 이루고 있음.
    [출력] 짝지어진 절댓값이 ⠳로 확정. **짝이 안 맞아 남은 `|`는 여기서 처리되지 않고**
      11c의 마지막 줄(조건제시·조건부확률·나눔 바)이 일괄로 ⠳로 바꾼다.
    """
    def _abs_replace(m: re.Match) -> str:
        inner = convert_latex((m.group(1) or m.group(2) or ""))
        return f"{_ABS_IND}{inner}{_ABS_IND}"

    result = _ABS_RE.sub(_abs_replace, result)
    # 단순 |...| 패턴 (LaTeX에서 수직바로 쓴 절댓값)
    result = re.sub(r"\|([^|]+)\|", lambda m: f"{_ABS_IND}{convert_latex(m.group(1))}{_ABS_IND}", result)
    return result.replace("\\|", _ABS_IND)


def _stage7_sum(result: str) -> str:
    """7. 합 기호 \\sum_{lower}^{upper} (수학 제25항) — 범위 구조.

    [입력] \\sum_{…}^{…} 구조가 원형(8단계 위첨자 이전).
    [출력] 총합 기호 + 범위가 완성 점자. ∑ 유니코드 자체는 symbol_table(12단계) 몫.

    ⚠ 8단계보다 먼저다 — 합의 위끝은 위첨자표가 아니라 칸 구분이다(적분 1e와 같은 이유).
    """
    def _sum_replace(m: re.Match) -> str:
        lower = convert_latex(m.group(1))
        upper = convert_latex(m.group(2)) if m.group(2) else ""
        # ,.S;lower upper 본식 형태: 여기서는 범위 표시만
        # 규정 제25항은 ,.S(⠠⠨⠎)이나 도서 관행은 대문자표 ⠠를 생략한 .S(⠨⠎)
        # — gold 수학2 ⠨⠎ 426회 vs ⠠⠨ 계열 3회(F3, 2026-07-20 실측).
        base = _SUM_BASE   # 총합 기호 (수학 제25항 / 도서 관행)
        if upper:
            return f"{base}{_SUBSCRIPT_IND}{lower} {upper} "
        return f"{base}{_SUBSCRIPT_IND}{lower} "

    result = _SUM_RE.sub(_sum_replace, result)
    return result.replace("\\sum", _SUM_BASE)


def _stage8_superscript(result: str) -> str:
    """8. 위첨자 base^{exp} → base⠘exp (수학 제18항).

    [입력] ^ 가 ASCII. 지수가 아직 원문("2"·"\\prime")이라 **문자열로 판정**할 수 있다.
    [출력] 위첨자가 완성 점자(관행 약기 ⠣·⠩ 포함). ^ 소멸.

    ⚠ 여기서 raw_exp를 원문 문자열로 보는 게 핵심이다 — 11단계(숫자→수표)를 지나면
      "2"가 ⠼⠃가 되어 관행 약기 판정이 불가능해진다.
    """
    def _sup_replace(m: re.Match) -> str:
        base = m.group(1) or m.group(3) or ""
        raw_exp = (m.group(2) or m.group(4) or "").strip()
        # 관행(book): 제곱(^2)은 ⠣ 한 셀 약기 — 정답 코퍼스에서 규정형 ⠘⠼⠃은 0회,
        # ⠣형만 관측(수학2 p009 'x<9#b'·p039 'x<5y<' 실측). 규정 모드는 제18항 그대로.
        # 프라임(제17항): f^{\prime}(x)는 위첨자표 없이 본문자 뒤에 바로 ⠤를 적는다
        # (규정 예시 `f-8x0`). 구현이 ⠘⠤로 내보내 39건이 어긋났다(2026-07-19).
        if raw_exp in ("\\prime", "'", "′"):
            return f"{base}⠤"
        if raw_exp in ("\\prime\\prime", "''", "″"):
            return f"{base}⠤⠤"
        # 관행 지수 약기: ²=⠣(gold 107회)·³=⠩(9건 중 7건, 2026-07-19 실측).
        # ⁴ 이상은 gold도 규정형 ⠘⠼N을 쓰므로 약기하지 않는다.
        if _IS_BOOK_STYLE and raw_exp in ("2", "3"):
            return base + ("⠣" if raw_exp == "2" else "⠩")
        exp  = convert_latex(raw_exp)
        exp_w = _wrap_ins(exp) if _needs_wrap(raw_exp) else exp
        return f"{base}{_SUPERSCRIPT_IND}{exp_w}"

    return _SUP_RE.sub(_sup_replace, result)


def _stage9_subscript(result: str) -> str:
    """9. 아래첨자 base_{sub} → base⠰sub (수학 제19항, ; = ⠰).

    [입력] 남은 _ 가 ASCII(순열 1c·왼쪽첨자 1d·로그 4·적분 1e가 이미 자기 몫을 소비).
    [출력] 아래첨자가 완성 점자. _ 소멸.
    """
    def _sub_replace(m: re.Match) -> str:
        base = m.group(1) or m.group(3) or ""
        sub  = convert_latex(m.group(2) or m.group(4) or "")
        sub_w = _wrap_ins(sub) if _needs_wrap(m.group(2) or m.group(4) or "") else sub
        return f"{base}{_SUBSCRIPT_IND}{sub_w}"

    return _SUB_RE.sub(_sub_replace, result)


# ── 10단계 치환표 (구현상 convert_latex 안의 지역 리터럴이었다 — 호출마다,
#    재귀까지 매번 새로 만들던 것을 모듈 상수로 올렸다. 값은 전부 모듈 상수라 동작 동일) ──
_LATEX_SIMPLE: dict[str, str] = {
    "\\infty":    "⠿",    # ∞ (수학 제50항: =)
    "\\pm":       "⠢⠔",   # ± (제51항 예시 59=⠢⠔; 별칭 경유 시 symbol_table과 동일)
    "\\times":    "⠡",    # × (수학 제2항, 폰트 "*"=⠡)
    "\\div":      "⠌⠌",   # ÷ (수학 제2항, 폰트 "//"=⠌⠌)
    "\\cdot":     "⠐",    # · (수학 제2항 붙임, 폰트 '"'=⠐)
    "\\leq":      "⠖⠖",   # ≤ (수학 제4항 8호, 폰트 66=⠖⠖ — ⠦는 8 오독이었음)
    "\\geq":      "⠲⠲",   # ≥ (수학 제4항 6호, 폰트 "44"=⠲⠲)
    "\\neq":      _NEQ,   # ≠ (수학 제4항 1호 .33 / 도서 관행 .3 — F4 실측 주석 참조)
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
    "\\alpha":    _LC_GREEK + "⠁",   # α
    "\\beta":     _LC_GREEK + "⠃",   # β
    "\\gamma":    _LC_GREEK + "⠛",   # γ
    "\\delta":    _LC_GREEK + "⠙",   # δ
    "\\epsilon":  _LC_GREEK + "⠑",   # ε
    "\\varepsilon":_LC_GREEK + "⠑",  # ε (변형)
    "\\zeta":     _LC_GREEK + "⠵",   # ζ
    "\\eta":      _LC_GREEK + "⠱",   # η (수학 제13항 표 .:)
    "\\theta":    _LC_GREEK + "⠹",   # θ
    "\\iota":     _LC_GREEK + "⠊",   # ι
    "\\kappa":    _LC_GREEK + "⠅",   # κ
    "\\lambda":   _LC_GREEK + "⠇",   # λ
    "\\mu":       _LC_GREEK + "⠍",   # μ
    "\\nu":       _LC_GREEK + "⠝",   # ν
    "\\xi":       _LC_GREEK + "⠭",   # ξ
    "\\pi":       _LC_GREEK + "⠏",   # π
    "\\rho":      _LC_GREEK + "⠗",   # ρ
    "\\sigma":    _LC_GREEK + "⠎",   # σ
    "\\tau":      _LC_GREEK + "⠞",   # τ
    "\\upsilon":  _LC_GREEK + "⠥",   # υ
    "\\phi":      _LC_GREEK + "⠋",   # φ
    "\\varphi":   _LC_GREEK + "⠋",   # φ (변형)
    "\\chi":      _LC_GREEK + "⠯",   # χ (수학 제13항 표 .&)
    "\\psi":      _LC_GREEK + "⠽",   # ψ
    "\\omega":    _LC_GREEK + "⠺",   # ω
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
    # 대문자 그리스 문자 — 접두는 _CAP_GREEK(규정 ,. / 도서 관행 . — F3 실측 주석 참조)
    "\\Alpha":   _CAP_GREEK + "⠁", "\\Beta":    _CAP_GREEK + "⠃",
    "\\Gamma":   _CAP_GREEK + "⠛", "\\Delta":   _CAP_GREEK + "⠙",
    "\\Epsilon": _CAP_GREEK + "⠑", "\\Zeta":    _CAP_GREEK + "⠵",
    "\\Eta":     _CAP_GREEK + "⠱", "\\Theta":   _CAP_GREEK + "⠹",
    "\\Iota":    _CAP_GREEK + "⠊", "\\Kappa":   _CAP_GREEK + "⠅",
    "\\Lambda":  _CAP_GREEK + "⠇", "\\Mu":      _CAP_GREEK + "⠍",
    "\\Nu":      _CAP_GREEK + "⠝", "\\Xi":      _CAP_GREEK + "⠭",
    "\\Pi":      _CAP_GREEK + "⠏", "\\Rho":     _CAP_GREEK + "⠗",
    "\\Sigma":   _CAP_GREEK + "⠎", "\\Tau":     _CAP_GREEK + "⠞",
    "\\Upsilon": _CAP_GREEK + "⠥", "\\Phi":     _CAP_GREEK + "⠋",
    "\\Chi":     _CAP_GREEK + "⠯", "\\Psi":     _CAP_GREEK + "⠽",
    "\\Omega":   _CAP_GREEK + "⠺",
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
# 긴 명령어를 먼저 치환하여 prefix 충돌 방지 (예: \\int vs \\in).
# sort는 안정 정렬이라 같은 길이면 위 리터럴의 기재 순서가 그대로 유지된다.
_LATEX_SIMPLE_ORDERED: list[tuple[str, str]] = sorted(
    _LATEX_SIMPLE.items(), key=lambda x: -len(x[0]))


def _stage10_latex_symbols(result: str) -> str:
    """10. 기타 LaTeX 명령어 직접 매핑 (_LATEX_SIMPLE).

    [입력] 구조 매크로가 모두 풀린 뒤 남은 단순 기호 명령들.
    [출력] 지원 명령이 전부 점형. 미지원 \\cmd는 남아 11d/13이 정리한다.
    """
    for latex_cmd, braille_val in _LATEX_SIMPLE_ORDERED:
        result = result.replace(latex_cmd, braille_val)
    return result


def _stage10x_minus(result: str) -> str:
    """10x. 뺄셈표: 남은 하이픈은 수식 문맥에선 뺄셈·음수 (수학 제2항 9=⠔).

    [입력] `-` 가 ASCII. 프라임(′→⠤, 제17항)은 10단계에서 이미 치환됐고
      \\text 한글은 sentinel로 보호돼 있다.
    [출력] 하이픈 소멸, 전부 ⠔.

    ⚠ 11단계(숫자)보다 **먼저**여야 한다 — _NUM_RE의 선행 '-?'가 이항 뺄셈("9-3")을
      숫자 내 붙임표(⠤, 계좌번호용)로 삼키는 것을 막는다(제45항 예시 #i9#c33#f).
    """
    return result.replace("-", "⠔")


def _stage11_numbers(result: str) -> str:
    """11. 숫자 → 수표시 + 점자 (C5-critical) + 11a. 숫자 뒤 로마자 a~j 구분.

    [입력] 아라비아 숫자가 ASCII로 남아 있음. 로마자도 ASCII(14단계 이전).
    [출력] 모든 숫자가 ⠼ + 숫자 셀. **C5 불변량: 점형 숫자는 반드시 수표로 시작한다.**

    ⚠ **문맥 소실 지점 3 — 숫자와 로마자 a~j의 셀이 같아진다.** 그래서 11a가
      숫자 뒤 a~j에 구분점 ⠐를 넣는다(제12항 [다만]·[붙임], gold #B"A 59회 일치).
      이 단계 이후로는 '이 셀이 숫자인가 글자인가'를 셀만 보고 판정할 수 없다.
    """
    def _num_replace(m: re.Match) -> str:
        return digits_to_braille(m.group())

    result = _NUM_RE.sub(_num_replace, result)

    # 11a. 숫자 셀과 a~j 문자 셀이 동형이라 3a가 31로 읽히는 것을 막는 규정.
    # 대상은 a~j 소문자만(대문자는 ⠠가 이미 구분).
    return re.sub(r"(⠼[⠁⠃⠉⠙⠑⠋⠛⠓⠊⠚⠲⠂]*[⠁⠃⠉⠙⠑⠋⠛⠓⠊⠚])([a-j])",
                  r"\1⠐\2", result)


def _stage11b_arithmetic(result: str) -> str:
    """11b. 사칙연산 기호 변환 (수학 제2항) — 숫자 변환 후 처리.

    [입력] + 와 = 가 ASCII.
    [출력] + → ⠢, = → ⠒⠒. 11e(연산 붙임)가 이 점형 토큰을 보고 동작하므로
      11e보다 반드시 먼저다.
    """
    result = result.replace("+", "⠢")                        # 덧셈표 (수학 제2항, 폰트 "5"=⠢)
    return result.replace("=", "⠒⠒")                         # 등호 (수학 제3항, 폰트 "33"=⠒⠒)


def _stage11c_math_context_symbols(result: str) -> str:
    """11c. 문맥 overload 분기 — 수식 내 기호는 수학 의미로 확정한다.

    [입력] ∼·→·≠·∴·쉼표·!··(가운뎃점)·′·∘·△·□·| 가 아직 원문자.
    [출력] 전부 수학 점형. **12단계 substitute_symbols(텍스트 의미)보다 먼저 확정해야**
      텍스트 물결표·느낌표·가운뎃점 등으로 오역되지 않는다 — 이 단계의 존재 이유다.
    """
    # ∼: 수식 논리부정·관계 = ⠈⠔ (명제 제61항, 폰트 "@9"). 텍스트 물결표는 symbol_table 담당.
    # →: 화살표·조건문 = ⠒⠕ (제38·61항, 폰트 "3o").
    result = result.replace("∼", "⠈⠔").replace("→", "⠒⠕")
    # ≠: 수식 문맥은 도서 관행 .3(_NEQ 주석 참조) — symbol_table(규정형 .33)보다 먼저 치환.
    result = result.replace("≠", _NEQ)
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
    return result.replace("|", _ABS_IND)


def _stage11d_strip_unknown_commands(result: str) -> str:
    """11d. 미처리 \\cmd 제거(P3).

    [입력] 지원 명령은 전부 소비됐고 남은 \\cmd는 미지원 명령뿐.
    [출력] 백슬래시 명령 소멸. 12단계 substitute_symbols가 백슬래시를 ⠸⠡로
      음역하기 전에 정리해야 하므로 이 위치다.
    """
    return re.sub(r"\\[a-zA-Z]+\*?", "", result)


def _stage13_cleanup(result: str) -> str:
    """13. 잔여 LaTeX 명령어·중괄호 제거.

    [입력] substitute_symbols(12)를 지난 뒤. 그 과정에서 새로 드러난 잔여물이 있을 수 있다.
    [출력] \\cmd·{ } 완전 소멸. 이후 단계는 순수 점형 + 로마자 + 공백만 본다.
    """
    result = re.sub(r"\\[a-zA-Z]+\*?", "", result)
    return re.sub(r"[{}]", "", result)


def _stage14_letters(result: str) -> str:
    """14. 남은 로마자 → 수식 점자 (로마자표 없이, 수학 점자 제12항).

    [입력] 로마자가 ASCII로 살아 있는 **마지막 단계**. 대소문자 구분이 가능하다.
    [출력] 로마자 소멸, 전부 점형.

    ⚠ **문맥 소실 지점 4 — 이 단계 이후 대문자 판정이 불가능하다.** 연속 대문자
      (프라임 ⠤ 개재 허용)는 대문자 단어표 ⠠⠠ 하나로 묶는다(제35항 [붙임] @c,,A-B-,
      gold ,, 572회 실측). 단독 대문자는 대문자표 ⠠.
      1a(병치 닫음표 생략)가 대문자 함수명을 제외하는 이유가 여기 있다 — 닫음을 지우면
      앞 인수와 붙어 연속 대문자로 오인돼 이 단계가 ⠠⠠를 잘못 붙인다.
    """
    result = re.sub(
        r"[A-Z](?:⠤?[A-Z])+⠤?",
        lambda m: "⠠⠠" + "".join(_letter_braille(c) if c.isalpha() else c
                                  for c in m.group()),
        result)
    result = re.sub(r"[A-Z]", lambda m: "⠠" + _letter_braille(m.group()), result)
    return re.sub(r"[a-z]", lambda m: _letter_braille(m.group()), result)


def _stage15_spaces(result: str) -> str:
    """15. 수식 내 ASCII 공백 → 점자공백(⠀), 구조 공백 sentinel 복원.

    [입력] 구조 공백이 sentinel _SP(\\x1f)로, 입력 공백이 ASCII ' '로 구분돼 있다.
    [출력] 둘 다 ⠀(U+2800). 구조 공백(제51·57항)과 입력 공백이 겹치면 한 칸으로
      합친다(⠿  f(x) 이중 칸 방지).

    ⚠ **문맥 소실 지점 5 — 이 단계 이후 구조 칸과 입력 칸을 구별할 수 없다.**
      칸을 근거로 판단하는 규칙(11e 연산 붙임 등)은 전부 이 앞에 있어야 한다.
    """
    result = re.sub(r" *\x1f *", _SP, result)
    result = re.sub(r" {2,}", " ", result)
    result = result.replace(" ", "⠀")
    return result.replace(_SP, "⠀")


def convert_latex(latex: str) -> str:
    r"""LaTeX 수식 문자열 → 점자 BRF.

    **순서가 곧 의미인 단일 파이프라인**이다. 각 단계는 str→str 함수이고, 공유 상태는
    `result` 문자열 하나뿐이다(예외: 0단계가 떼어낸 `_text_store`를 16단계가 되돌린다).

    새 규칙을 **어디에 넣을지**는 아래 표의 '이 단계 이후 잃는 것'으로 판정한다.
    규칙이 보아야 할 정보가 이미 사라진 위치에 넣으면 조용히 오작동한다.

    ┌────┬───────────────────────┬──────────────────────┬────────────────────────────┐
    │단계│ 함수                   │ 입력 표현             │ 이 단계 이후 잃는 것        │
    ├────┼───────────────────────┼──────────────────────┼────────────────────────────┤
    │ 0  │_protect_text          │원문(한글 포함)        │**한글**→PUA sentinel       │
    │ 0a │_normalize_latex_input │MinerU식 LaTeX        │행렬·연립식은 여기서 이미 점형│
    │ 0b │_stage0b_nth_root      │ASCII [ ] 살아있음     │\sqrt[n] 형태               │
    │ 1  │_stage1_math_brackets  │ASCII 괄호·함수명      │★**괄호의 정체성**(아래 참조)│
    │ 1b │_stage1b_accents       │대소문자 살아있음      │\vec·\bar 명령              │
    │ 1c │_stage1c_permutation   │ASCII _ 살아있음       │순열 첨자쌍                 │
    │ 1d │_stage1d_left_scripts  │{} 마커 살아있음       │왼쪽 첨자                   │
    │ 1e │_stage1e_integral_range│∫ + ASCII _ ^         │적분 범위(위첨자로 오인 방지)│
    │ 1f │_stage1f_trig_arg_group│\sin 등 명령 형태      │삼각 인수 경계              │
    │ 2  │_apply_fracs           │\frac 구조            │분수 구조                   │
    │ 2c │_stage2c_sqrt          │\sqrt 구조            │근호 구조                   │
    │ 3  │_stage3_limit          │\lim·\to              │극한 구조                   │
    │ 4  │_stage4_log            │ASCII 밑 숫자          │로그 구조(내림밑 8=⠦·0=⠴ 생성)│
    │ 5  │_stage5_trig           │\sin 등 명령           │삼각 명령                   │
    │ 6  │_stage6_abs            │ASCII |               │짝지은 절댓값               │
    │ 7  │_stage7_sum            │\sum 구조             │합 범위(위첨자로 오인 방지)  │
    │ 8  │_stage8_superscript    │**지수가 원문 문자열** │^2 관행 약기 판정 근거      │
    │ 9  │_stage9_subscript      │ASCII _               │아래첨자 구조               │
    │10  │_stage10_latex_symbols │지원 \cmd             │단순 기호 명령              │
    │10x │_stage10x_minus        │ASCII -               │하이픈(숫자보다 먼저여야)    │
    │11  │_stage11_numbers       │ASCII 숫자            │★**숫자 vs 로마자 a~j 구분**│
    │11b │_stage11b_arithmetic   │ASCII + =             │+ = 원문자                  │
    │11c │_stage11c_math_context…│∼→≠∴,!·′∘△□| 원문자  │수학/텍스트 의미 분기 기회   │
    │11e │_tighten_operator_spac…│점형 연산자 + 칸       │붙임 판정용 칸              │
    │11d │_stage11d_strip_unknow…│미지원 \cmd           │백슬래시(음역 방지)         │
    │12  │substitute_symbols     │남은 유니코드 기호     │기호표 적용 기회            │
    │13  │_stage13_cleanup       │잔여 \cmd·{}          │중괄호                      │
    │14  │_stage14_letters       │**로마자 ASCII**      │★**대문자 판정**            │
    │15  │_stage15_spaces        │_SP sentinel vs ' '   │★**구조 칸 vs 입력 칸 구분**│
    │16  │_restore_text          │sentinel              │—(한글 복원, 종료)          │
    └────┴───────────────────────┴──────────────────────┴────────────────────────────┘

    ★ 문맥 소실 4곳이 실제 사고의 원천이다.
      1) 괄호(1단계 이후): ⠦·⠴가 소괄호·묶음표·로그 내림밑 8/0·%(⠴⠏)·∘(⠸⠴)로 다의가
         된다. T2(병치 닫음표 생략)를 최종 셀열에 넣었더니 log₁₀이 log₁로 깨진 사고가
         이것이다(2026-07-20). **괄호를 보는 규칙은 1단계 안에서 끝낸다.**
      2) 숫자/로마자(11단계 이후): 셀이 동형이라 11a가 구분점 ⠐를 넣는다.
      3) 대문자(14단계 이후): 연속 대문자 판정 불가 → 1a가 대문자 함수명을 제외하는 근거.
      4) 칸(15단계 이후): 구조 칸과 입력 칸이 같아진다 → 칸 기반 규칙은 그 앞에 둔다.

    ⚠ 단계 번호는 역사적 라벨이라 **실행 순서와 어긋난 곳이 있다** — 11e가 11d보다
      먼저 돈다. 아래 호출 나열이 진실이다.
    ⚠ 각 단계의 하위 내용 변환은 convert_latex를 **재귀 호출**한다(분수 분자·근호 안 등).
      재귀분은 전 파이프라인을 다 통과해 이미 완성 점자로 되돌아온다.
    """
    latex, _text_store = _protect_text(latex)   # 0.  P2: \text{한글} → 한글 점자 sentinel
    result = _normalize_latex_input(latex)      # 0a. MinerU/마크다운 입력 정규화

    result = _stage0b_nth_root(result)              # 0b. \sqrt[n]{} — 대괄호 치환보다 먼저
    result = _stage1_math_brackets(result)          # 1·1a. 수학 괄호 + 병치 닫음표 생략
    result = _stage1b_accents(result)               # 1b. 문자 위 기호
    result = _stage1c_permutation(result)           # 1c. 순열·조합
    result = _stage1d_left_scripts(result)          # 1d. 왼쪽 첨자
    result = _stage1e_integral_range(result)        # 1e. 정적분 범위
    result = _stage1f_trig_arg_group(result)        # 1f. 삼각함수 인수 묶음
    result = _apply_fracs(result)                   # 2.  분수
    result = _stage2c_sqrt(result)                  # 2c. 제곱근
    result = _stage3_limit(result)                  # 3.  극한
    result = _stage4_log(result)                    # 4.  로그
    result = _stage5_trig(result)                   # 5·5b. 삼각함수 + 인수 붙임
    result = _stage6_abs(result)                    # 6.  절댓값
    result = _stage7_sum(result)                    # 7.  합 기호
    result = _stage8_superscript(result)            # 8.  위첨자
    result = _stage9_subscript(result)              # 9.  아래첨자
    result = _stage10_latex_symbols(result)         # 10. 단순 LaTeX 기호 명령
    result = _stage10x_minus(result)                # 10x. 뺄셈표 (숫자보다 먼저)
    result = _stage11_numbers(result)               # 11·11a. 숫자 + a~j 구분점
    result = _stage11b_arithmetic(result)           # 11b. + =
    result = _stage11c_math_context_symbols(result)  # 11c. 문맥 overload 분기
    result = _tighten_operator_spacing(result)      # 11e. 연산·비교 기호 앞뒤 붙임
    result = _stage11d_strip_unknown_commands(result)  # 11d. 미처리 \cmd 제거
    result = substitute_symbols(result)             # 12. 남은 유니코드 기호
    result = _stage13_cleanup(result)               # 13. 잔여 \cmd·중괄호 제거
    result = _stage14_letters(result)               # 14. 남은 로마자
    result = _stage15_spaces(result)                # 15. 공백 → ⠀

    result = _restore_text(result, _text_store)     # 16. P2 한글 복원
    return _w2c_sweep_residue(result)               # 17. 비점자 잔류 정화(마지막 그물)

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


def _wrap_ins(inner_braille: str) -> str:
    """점역자 삽입 묶음을 씌운다 — 묶을지 판정(_needs_wrap)이 끝난 내용에만 호출.

    도서 관행(F1, 2026-07-20 실측): 묶을 내용에 소괄호 점형(⠦·⠴)이 있으면 묶음을
    중괄호꼴 동형 ⠶…⠶로 승격한다 — ⠦⠴ 묶음이 내용의 실제 괄호와 겹쳐 읽히는 것을
    피하는 표기. gold 수학2: 분수 인접 ⠶⠌·⠌⠶ 146회·⠴⠶ 145회 vs 동형 겹침 ⠦⠦ 2회.
    예: \\frac{g(x)+1}{x+2} → 분자 ⠶⠛⠦⠭⠴⠢⠼⠁⠶ · 분모 ⠦⠭⠢⠼⠃⠴ (수학2 p094).
    ⚠ 리터럴 중첩 괄호 f(g(x))는 이 함수와 무관 — gold도 ⠦⠦…⠴⠴ 그대로 겹친다
    (수학2 p056·p091 ⠋⠦⠛⠦⠭⠴⠴ 실측). regulation 모드는 항상 규정 원형 ⠷…⠾(제6항 2호).
    """
    if _IS_BOOK_STYLE and ("⠦" in inner_braille or "⠴" in inner_braille):
        return f"⠶{inner_braille}⠶"
    return f"{_WRAP_S}{inner_braille}{_WRAP_E}"


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
    # 이미 완전 괄호 → 추가 묶음 불필요 (제53항 y^(4) — 이중 괄호 방지).
    # ASCII ( ) 와 **1단계 이후의 점형 소괄호 ⠦ ⠴ 를 모두** 본다: 6개 호출부 중
    # 0b만 1단계 앞이고 나머지 5개(2·2c·4·8·9)는 뒤라 점형 괄호를 넘긴다.
    # 점형을 안 보던 구판은 x^{(a+b)} → ⠭⠘⠶⠦⠁⠢⠃⠴⠶ 로 묶음이 겹쳤다(2026-07-21).
    for _op, _cl in (("(", ")"), ("⠦", "⠴")):
        if expr.startswith(_op) and expr.endswith(_cl):
            depth = 0
            for i, ch in enumerate(expr):
                if ch == _op:
                    depth += 1
                elif ch == _cl:
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
    # 곱 판정: 첨자 그룹 제거 후 인수(문자·수·명령·괄호군) 2개 이상.
    # 규정은 곱도 묶으라 하지만(제7항 3호·제22항 [붙임2]) 정답 도서는 묶지 않는다 —
    # A/B에서 곱 묶음 해제가 유사도 +2.1p(temp/wrap_variant_ab.py). 관행이라 book 모드
    # 한정으로 해제하고, regulation 모드는 규정대로 묶는다.
    # (근호 안·삼각 인수의 명시 묶음은 _TRIG_ARG_RE 등 별도 경로가 규정대로 처리한다.)
    if _IS_BOOK_STYLE:
        return False
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
                den_wrapped = _wrap_ins(den) if _needs_wrap(den_raw) else den
                num_wrapped = _wrap_ins(num) if _needs_wrap(num_raw) else num
                result.append(f"{den_wrapped}{_FRACTION_MID}{num_wrapped}")
                i = after_den
                continue
        result.append(latex[i])
        i += 1
    return "".join(result)
