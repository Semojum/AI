"""KOR_MATH 수식 점자 규칙 엔진.

한국 점자 규정 2017 개정 기준 LaTeX → 점자 BRF 변환.
배포 전 공식 규정집 대조 검증 필요.

C5-critical: _DIGIT_MAP 오류 시 단위 테스트에서 즉시 차단.
"""

from __future__ import annotations

import re

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

# 수학 구조
_FRACTION_START  = "⠜"
_FRACTION_MID    = "⠌"
_FRACTION_END    = "⠱"
_SUPERSCRIPT_IND = "⠘"
_SUBSCRIPT_IND   = "⠢"
_SQRT            = "⠬⠄"

# 집합 기호
_SET_SYMBOLS: dict[str, str] = {
    "∈": "⠈⠑", "∉": "⠈⠑⠈", "⊂": "⠈⠃", "⊃": "⠃⠈",
    "⊆": "⠈⠃⠶", "⊇": "⠃⠈⠶", "∪": "⠈⠥", "∩": "⠈⠍",
    "∅": "⠼⠚", "≤": "⠐⠣", "≥": "⠐⠜", "≠": "⠐⠶", "≈": "⠐⠐",
    "±": "⠬", "×": "⠐⠦", "÷": "⠐⠲",
}

_FRAC_RE = re.compile(r"\\frac\{([^{}]*)\}\{([^{}]*)\}")
_SUP_RE  = re.compile(r"\{([^{}]*)\}\^?\^\{([^{}]*)\}|([A-Za-z0-9])\^([A-Za-z0-9])")
_SUB_RE  = re.compile(r"\{([^{}]*)\}_\{([^{}]*)\}|([A-Za-z0-9])_([A-Za-z0-9])")
_SQRT_RE = re.compile(r"\\sqrt\{([^{}]*)\}")
_NUM_RE  = re.compile(r"-?\d+(?:[.,]\d+)*")


def digits_to_braille(num_str: str) -> str:
    """숫자 문자열 → 수표시 + 점자 (C5-critical)."""
    result = [_NUMBER_INDICATOR]
    for ch in num_str:
        if ch in _DIGIT_MAP:
            result.append(_DIGIT_MAP[ch])
        elif ch in (".", ","):
            result.append("⠂")  # 소수점
        elif ch == "-":
            result.append("⠤")  # 음수 부호
        else:
            result.append(ch)
    return "".join(result)


def convert_latex(latex: str) -> str:
    """LaTeX 수식 문자열 → 점자 BRF."""
    result = latex

    # 집합 기호 치환
    for sym, braille in _SET_SYMBOLS.items():
        result = result.replace(sym, braille)

    # \frac{A}{B} → ⠜A⠌B⠱
    def _frac_replace(m: re.Match) -> str:
        num = convert_latex(m.group(1))
        den = convert_latex(m.group(2))
        return f"{_FRACTION_START}{num}{_FRACTION_MID}{den}{_FRACTION_END}"
    result = _FRAC_RE.sub(_frac_replace, result)

    # \sqrt{X} → ⠬⠄X
    def _sqrt_replace(m: re.Match) -> str:
        inner = convert_latex(m.group(1))
        return f"{_SQRT}{inner}"
    result = _SQRT_RE.sub(_sqrt_replace, result)

    # 위첨자: x^n → x⠘n
    def _sup_replace(m: re.Match) -> str:
        base = m.group(1) or m.group(3) or ""
        exp  = m.group(2) or m.group(4) or ""
        return f"{base}{_SUPERSCRIPT_IND}{exp}"
    result = _SUP_RE.sub(_sup_replace, result)

    # 아래첨자: x_n → x⠢n
    def _sub_replace(m: re.Match) -> str:
        base = m.group(1) or m.group(3) or ""
        sub  = m.group(2) or m.group(4) or ""
        return f"{base}{_SUBSCRIPT_IND}{sub}"
    result = _SUB_RE.sub(_sub_replace, result)

    # 숫자 → 수표시 + 점자
    def _num_replace(m: re.Match) -> str:
        return digits_to_braille(m.group())
    result = _NUM_RE.sub(_num_replace, result)

    # 나머지 LaTeX 명령어 제거
    result = re.sub(r"\\[a-zA-Z]+", "", result)
    result = re.sub(r"[{}]", "", result)

    return result
