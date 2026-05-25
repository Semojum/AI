"""점자 변환 코어 — 한글·영어·숫자·수식 변환.

공개 API: translate_tagged_text(text: str) -> str

braillify 설치 시 (AI 서버 운영 환경):
  - <formula>...</formula> → kor_math_rules.convert_latex() (LaTeX 전용)
  - 나머지 텍스트 → braillify.translate_to_unicode()
    (한글 약자·약어·수 포함 2024 개정 규정, 영어, 숫자, π·∫·∂ 등 수학 기호)
  주의: 이미 변환된 점자 셀(U+2800-U+28FF)이 braillify에 들어가지 않도록
        <formula> 세그먼트와 일반 텍스트 세그먼트를 분리해 처리한다.

braillify 미설치 시 (폴백):
  - <formula> → convert_latex, 기호 → substitute_symbols, 나머지 → 자모 분해 폴백
  - 약자·약어 미지원

매핑 기준: 한국 점자 규정 2024 개정 (braillify) / 2017 개정 (폴백)
"""

from __future__ import annotations

import re

from app.ai.braille.kor_math_rules import convert_latex, digits_to_braille
from app.ai.braille.symbol_rules import substitute_symbols

try:
    import braillify as _braillify_lib
    _BRAILLIFY_AVAILABLE = True
except ImportError:
    _BRAILLIFY_AVAILABLE = False

# ── 한글 자모 점자 테이블 ──────────────────────────────────────────────────
_CHOSEONG = [
    "⠈",    # ㄱ
    "⠐⠈",  # ㄲ
    "⠉",    # ㄴ
    "⠊",    # ㄷ
    "⠐⠊",  # ㄸ
    "⠐",    # ㄹ
    "⠑",    # ㅁ
    "⠘",    # ㅂ
    "⠐⠘",  # ㅃ
    "⠠",    # ㅅ
    "⠐⠠",  # ㅆ
    "",      # ㅇ (묵음 초성)
    "⠨",    # ㅈ
    "⠐⠨",  # ㅉ
    "⠩",    # ㅊ
    "⠋",    # ㅋ
    "⠌",    # ㅌ
    "⠍",    # ㅍ
    "⠗",    # ㅎ
]

_JUNGSEONG = [
    "⠣",    # ㅏ
    "⠗",    # ㅐ
    "⠜",    # ㅑ
    "⠜⠗",  # ㅒ
    "⠎",    # ㅓ
    "⠺",    # ㅔ
    "⠱",    # ㅕ
    "⠱⠺",  # ㅖ
    "⠥",    # ㅗ
    "⠥⠣",  # ㅘ
    "⠥⠗",  # ㅙ
    "⠥⠊",  # ㅚ
    "⠬",    # ㅛ
    "⠍",    # ㅜ
    "⠍⠎",  # ㅝ
    "⠍⠺",  # ㅞ
    "⠍⠊",  # ㅟ
    "⠴",    # ㅠ
    "⠤",    # ㅡ
    "⠤⠊",  # ㅢ
    "⠊",    # ㅣ
]

_JONGSEONG = [
    "",      # 없음
    "⠁",    # ㄱ
    "⠁⠁",  # ㄲ
    "⠁⠅",  # ㄳ
    "⠒",    # ㄴ
    "⠒⠆",  # ㄵ
    "⠒⠗",  # ㄶ
    "⠂",    # ㄷ
    "⠄",    # ㄹ
    "⠄⠁",  # ㄺ
    "⠄⠢",  # ㄻ
    "⠄⠃",  # ㄼ
    "⠄⠅",  # ㄽ
    "⠄⠌",  # ㄾ
    "⠄⠍",  # ㄿ
    "⠄⠗",  # ㅀ
    "⠢",    # ㅁ
    "⠃",    # ㅂ
    "⠃⠅",  # ㅄ
    "⠅",    # ㅅ
    "⠅⠅",  # ㅆ
    "⠶",    # ㅇ
    "⠆",    # ㅈ
    "⠆",    # ㅊ
    "⠋",    # ㅋ
    "⠌",    # ㅌ
    "⠍",    # ㅍ
    "⠗",    # ㅎ
]

_HANGUL_BASE    = 0xAC00
_HANGUL_END     = 0xD7A3
_JONGSEONG_CNT  = 28
_JUNGSEONG_CNT  = 21

_ROMAN_START = "⠴"
_ROMAN_END   = "⠲"
_CAPITAL_IND = "⠠"

_ALPHA_MAP: dict[str, str] = {
    "a": "⠁", "b": "⠃", "c": "⠉", "d": "⠙", "e": "⠑",
    "f": "⠋", "g": "⠛", "h": "⠓", "i": "⠊", "j": "⠚",
    "k": "⠅", "l": "⠇", "m": "⠍", "n": "⠝", "o": "⠕",
    "p": "⠏", "q": "⠟", "r": "⠗", "s": "⠎", "t": "⠞",
    "u": "⠥", "v": "⠧", "w": "⠺", "x": "⠭", "y": "⠽", "z": "⠵",
}

_FORMULA_RE      = re.compile(r"<formula>(.*?)</formula>", re.DOTALL)
_TAG_RE          = re.compile(r"<[^>]+>")
_NUMBER_RE       = re.compile(r"-?\d+(?:[.,]\d+)*")
_ALPHA_RUN_RE    = re.compile(r"[A-Za-z]+")
_BRAILLE_RE      = re.compile(r"[⠀-⣿]+")
_DIGIT_ALPHA_RE  = re.compile(r"(?<=\d)(?=[A-Za-z])")   # 숫자 뒤 바로 오는 알파벳
_HANGUL_SYL_RE   = re.compile(r"[가-힣]")        # 완성형 한글 음절


def _syllable_to_braille(syl: str) -> str:
    code = ord(syl) - _HANGUL_BASE
    jong = code % _JONGSEONG_CNT
    jung = (code // _JONGSEONG_CNT) % _JUNGSEONG_CNT
    cho  = code // _JONGSEONG_CNT // _JUNGSEONG_CNT
    return _CHOSEONG[cho] + _JUNGSEONG[jung] + _JONGSEONG[jong]


def _is_hangul(ch: str) -> bool:
    return _HANGUL_BASE <= ord(ch) <= _HANGUL_END


def _english_run(run: str) -> str:
    cells = []
    for ch in run:
        if ch.isupper():
            cells.append(_CAPITAL_IND)
            cells.append(_ALPHA_MAP.get(ch.lower(), ch))
        else:
            cells.append(_ALPHA_MAP.get(ch, ch))
    return _ROMAN_START + "".join(cells) + _ROMAN_END


def _braillify_fallback(text: str) -> str:
    """braillify 미설치 시 폴백 — 기본 자모 분해만 처리 (약자·약어 미지원)."""
    result = []
    i = 0
    while i < len(text):
        ch = text[i]
        if _is_hangul(ch):
            result.append(_syllable_to_braille(ch))
            i += 1
        elif ch.isdigit() or (ch == "-" and i + 1 < len(text) and text[i + 1].isdigit()):
            m = _NUMBER_RE.match(text, i)
            if m:
                result.append(digits_to_braille(m.group()))
                i = m.end()
            else:
                result.append(ch); i += 1
        elif ch.isalpha():
            m = _ALPHA_RUN_RE.match(text, i)
            if m:
                result.append(_english_run(m.group()))
                i = m.end()
            else:
                result.append(ch); i += 1
        else:
            result.append(ch); i += 1
    return "".join(result)


def _braillify(text: str) -> str:
    """태그 없는 순수 텍스트 → 점자 변환 (외부 직접 호출용 래퍼)."""
    if _BRAILLIFY_AVAILABLE:
        return _braillify_lib.translate_to_unicode(text)
    return _braillify_fallback(text)


def _emit_mixed(text: str, result: list[str]) -> None:
    """substitute_symbols() 출력을 점자 Unicode 구간과 일반 텍스트 구간으로 분리.

    이미 변환된 점자 Unicode(U+2800-U+28FF)는 braillify를 거치지 않고 그대로 pass.
    나머지 한글·영어·숫자 구간만 braillify에 전달한다.

    braillify 2.0.0은 \x00, PUA(U+E000+) 등 제어문자를 거부하므로
    플레이스홀더 방식 대신 이 세그먼트 분리 방식을 사용한다.
    """
    last = 0
    for m in _BRAILLE_RE.finditer(text):
        pre = text[last:m.start()]
        if pre:
            result.append(_braillify_lib.translate_to_unicode(pre))
        result.append(m.group())
        last = m.end()
    tail = text[last:]
    if tail:
        result.append(_braillify_lib.translate_to_unicode(tail))


def _preprocess_units(text: str) -> str:
    """숫자 바로 뒤 알파벳에 공백 삽입 — braillify가 로마자로 인식하도록."""
    return _DIGIT_ALPHA_RE.sub(" ", text)


def _collapse_spaces(braille: str) -> str:
    """이중 점자 공백(⠀⠀) → 단일 공백(⠀) — 숫자/영어 모드 전환 시 발생."""
    while "⠀⠀" in braille:
        braille = braille.replace("⠀⠀", "⠀")
    return braille


def _fix_leading_roman(text_orig: str, braille: str) -> str:
    """대문자 영어로 시작하는 한영 혼합 텍스트에서 ⠴ 누락을 보정."""
    if not _HANGUL_SYL_RE.search(text_orig):
        return braille
    if not re.match(r"^[A-Z]", text_orig):
        return braille
    if braille.startswith(_ROMAN_START):
        return braille
    if not braille.startswith(_CAPITAL_IND):
        return braille
    sp = braille.find("⠀")
    if sp == -1:
        return _ROMAN_START + braille + _ROMAN_END
    return _ROMAN_START + braille[:sp] + _ROMAN_END + braille[sp:]


def _translate_with_braillify(text: str) -> str:
    parts = _FORMULA_RE.split(text)
    chunks: list[tuple[bool, str]] = []  # (is_formula, braille)

    for i, part in enumerate(parts):
        if i % 2 == 0:  # 일반 텍스트 세그먼트
            clean = _TAG_RE.sub("", part)
            if i > 0:                # 수식 직후: 앞 공백 제거
                clean = clean.lstrip()
            if i < len(parts) - 1:  # 수식 직전: 뒤 공백 제거
                clean = clean.rstrip()
            if clean:
                preprocessed = _preprocess_units(clean)
                substituted = substitute_symbols(preprocessed)
                text_result: list[str] = []
                _emit_mixed(substituted, text_result)
                chunks.append((False, _collapse_spaces("".join(text_result))))
        else:  # 수식 세그먼트
            chunks.append((True, convert_latex(part)))

    # 수학 점자 규정 제11항: 수식 앞뒤 두 칸 공백(⠀⠀)
    result_parts: list[str] = []
    for j, (_, braille) in enumerate(chunks):
        if j > 0:
            result_parts.append("⠀⠀")
        result_parts.append(braille)

    braille = "".join(result_parts)
    braille = _fix_leading_roman(text, braille)
    return braille


def _translate_fallback(text: str) -> str:
    # braillify 미설치 시: 수식→convert_latex, 기호→substitute_symbols, 나머지→폴백
    def _formula_sub(m: re.Match) -> str:
        return convert_latex(m.group(1))

    result = _FORMULA_RE.sub(_formula_sub, text)
    result = _TAG_RE.sub("", result)
    result = substitute_symbols(result)
    return _braillify_fallback(result)


def translate_tagged_text(text: str) -> str:
    """<formula> 태그가 포함된 텍스트를 점자 BRF로 변환."""
    if _BRAILLIFY_AVAILABLE:
        return _translate_with_braillify(text)
    return _translate_fallback(text)
