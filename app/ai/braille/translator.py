"""점자 변환 코어 — 한글·영어·숫자·수식 변환.

공개 API: translate_tagged_text(text: str) -> str
  - <formula>...</formula> → kor_math_rules.convert_latex()
  - 한글 음절 → 6점자 인코딩
  - 영문자 → 로마자표(⠴) + 알파벳 매핑 + 종료표(⠲)
  - 숫자 → 수표시(⠼) + 점자

매핑 기준: 한국 점자 규정 2017 개정
배포 전 공식 규정집 대조 검증 필요.
"""

from __future__ import annotations

import re

from app.ai.braille.kor_math_rules import convert_latex, digits_to_braille
from app.ai.braille.symbol_rules import substitute_symbols

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

_FORMULA_RE  = re.compile(r"<formula>(.*?)</formula>", re.DOTALL)
_TAG_RE      = re.compile(r"<[^>]+>")
_NUMBER_RE   = re.compile(r"-?\d+(?:[.,]\d+)*")
_ALPHA_RUN_RE = re.compile(r"[A-Za-z]+")


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


def _braillify(text: str) -> str:
    """태그 없는 순수 텍스트 → 점자 변환."""
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


def translate_tagged_text(text: str) -> str:
    """<formula> 태그가 포함된 텍스트를 점자 BRF로 변환."""
    def _formula_sub(m: re.Match) -> str:
        return convert_latex(m.group(1))

    result = _FORMULA_RE.sub(_formula_sub, text)
    result = _TAG_RE.sub("", result)      # 나머지 태그 제거
    result = substitute_symbols(result)   # 특수기호 → 점자 셀 치환 (T3-5)
    return _braillify(result)
