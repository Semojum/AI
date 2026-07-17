"""점자 변환 코어 — 한글·영어·숫자·수식 변환.

공개 API: translate_tagged_text(text: str) -> str

braillify 설치 시 (AI 서버 운영 환경):
  - <!수식>...<!/수식> → kor_math_rules.convert_latex() (LaTeX 전용)
  - 나머지 텍스트 → braillify.translate_to_unicode()
    (한글 약자·약어·수 포함 2024 개정 규정, 영어, 숫자, π·∫·∂ 등 수학 기호)
  주의: 이미 변환된 점자 셀(U+2800-U+28FF)이 braillify에 들어가지 않도록
        <!수식> 세그먼트와 일반 텍스트 세그먼트를 분리해 처리한다.

braillify 미설치 시 (폴백):
  - <!수식> → convert_latex, 기호 → substitute_symbols, 나머지 → 자모 분해 폴백
  - 약자·약어 미지원

매핑 기준: 한국 점자 규정 2024 개정 (braillify) / 2017 개정 (폴백)
"""

from __future__ import annotations

import logging
import os
import re

from app.ai.braille.kor_math_rules import convert_latex, digits_to_braille
from app.ai.braille.symbol_rules import substitute_symbols

logger = logging.getLogger(__name__)

try:
    import braillify as _braillify_lib
    _BRAILLIFY_AVAILABLE = True
except ImportError:
    _BRAILLIFY_AVAILABLE = False
    logger.warning(
        "braillify 미설치 — 폴백 자모 분해 모드로 동작한다. 자모 점형은 규정값으로 "
        "교정됐으나 약자·약어가 빠져 규정 비준수다. 운영 출력에는 braillify가 필수."
    )

# ── 한글 자모 점자 테이블 ──────────────────────────────────────────────────
# 규정 제1·2항(braillify 실측 검증). 된소리표 = ⠠(제2항 ',') — 옛 폴백 ⠐는 오류.
_CHOSEONG = [
    "⠈",    # ㄱ
    "⠠⠈",  # ㄲ (된소리표 ⠠ + ㄱ)
    "⠉",    # ㄴ
    "⠊",    # ㄷ
    "⠠⠊",  # ㄸ
    "⠐",    # ㄹ
    "⠑",    # ㅁ
    "⠘",    # ㅂ
    "⠠⠘",  # ㅃ
    "⠠",    # ㅅ
    "⠠⠠",  # ㅆ
    "",      # ㅇ (묵음 초성)
    "⠨",    # ㅈ
    "⠠⠨",  # ㅉ
    "⠰",    # ㅊ (제1항: ⠰, 옛 ⠩ 오류)
    "⠋",    # ㅋ
    "⠓",    # ㅌ (⠓, 옛 ⠌ 오류)
    "⠙",    # ㅍ (⠙, 옛 ⠍ 오류)
    "⠚",    # ㅎ (⠚, 옛 ⠗ 오류)
]

# 규정 제6·7항(braillify 실측 검증). 복합모음은 전용 단일셀(ㅘ⠧·ㅚ⠽·ㅝ⠏) — 옛 폴백의 분해는 오류.
_JUNGSEONG = [
    "⠣",    # ㅏ
    "⠗",    # ㅐ
    "⠜",    # ㅑ
    "⠜⠗",  # ㅒ
    "⠎",    # ㅓ
    "⠝",    # ㅔ (⠝, 옛 ⠺ 오류)
    "⠱",    # ㅕ
    "⠌",    # ㅖ (⠌, 옛 ⠱⠺ 오류)
    "⠥",    # ㅗ
    "⠧",    # ㅘ (전용 단일셀 ⠧, 옛 ⠥⠣ 분해 오류)
    "⠧⠗",  # ㅙ
    "⠽",    # ㅚ (⠽, 옛 ⠥⠊ 오류)
    "⠬",    # ㅛ
    "⠍",    # ㅜ
    "⠏",    # ㅝ (⠏, 옛 ⠍⠎ 오류)
    "⠏⠗",  # ㅞ
    "⠍⠗",  # ㅟ (⠍⠗, 옛 ⠍⠊ 오류)
    "⠩",    # ㅠ (⠩, 옛 ⠴ 오류)
    "⠪",    # ㅡ (⠪, 옛 ⠤ 오류)
    "⠺",    # ㅢ (⠺, 옛 ⠤⠊ 오류)
    "⠕",    # ㅣ (⠕, 옛 ⠊ 오류)
]

# 규정 제3·4·5항(braillify 실측 검증). 받침 base 교정 → 겹받침도 재구성, ㅆ받침=약자 ⠌(제4항).
_JONGSEONG = [
    "",      # 없음
    "⠁",    # ㄱ
    "⠁⠁",  # ㄲ
    "⠁⠄",  # ㄳ (ㄱ+ㅅ⠄)
    "⠒",    # ㄴ
    "⠒⠅",  # ㄵ (ㄴ+ㅈ⠅)
    "⠒⠴",  # ㄶ (ㄴ+ㅎ⠴)
    "⠔",    # ㄷ (⠔, 옛 ⠂ 오류)
    "⠂",    # ㄹ (⠂, 옛 ⠄ 오류)
    "⠂⠁",  # ㄺ (ㄹ⠂+ㄱ)
    "⠂⠢",  # ㄻ (ㄹ+ㅁ⠢)
    "⠂⠃",  # ㄼ (ㄹ+ㅂ⠃)
    "⠂⠄",  # ㄽ (ㄹ+ㅅ⠄)
    "⠂⠦",  # ㄾ (ㄹ+ㅌ⠦)
    "⠂⠲",  # ㄿ (ㄹ+ㅍ⠲)
    "⠂⠴",  # ㅀ (ㄹ+ㅎ⠴)
    "⠢",    # ㅁ
    "⠃",    # ㅂ
    "⠃⠄",  # ㅄ (ㅂ+ㅅ⠄)
    "⠄",    # ㅅ (⠄, 옛 ⠅ 오류)
    "⠌",    # ㅆ (약자 /, 제4항; 옛 ⠅⠅ 오류)
    "⠶",    # ㅇ
    "⠅",    # ㅈ (⠅, 옛 ⠆ 오류)
    "⠆",    # ㅊ
    "⠖",    # ㅋ (⠖, 옛 ⠋ 오류)
    "⠦",    # ㅌ (⠦, 옛 ⠌ 오류)
    "⠲",    # ㅍ (⠲, 옛 ⠍ 오류)
    "⠴",    # ㅎ (⠴, 옛 ⠗ 오류)
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

# 로마 숫자(유니코드 Number Forms) → 해당 로마자. 한국 점자 규정 제36항
# "로마 숫자는 해당 로마자를 사용하여 적는다" → 정규화 후 기존 로마자 경로
# (로마자표 ⠴ … 종료표 ⠲, 제29항)가 점역한다. 대문자/소문자 보존.
_ROMAN_NUMERAL_MAP: dict[str, str] = {
    "Ⅰ": "I", "Ⅱ": "II", "Ⅲ": "III", "Ⅳ": "IV", "Ⅴ": "V", "Ⅵ": "VI",
    "Ⅶ": "VII", "Ⅷ": "VIII", "Ⅸ": "IX", "Ⅹ": "X", "Ⅺ": "XI", "Ⅻ": "XII",
    "Ⅼ": "L", "Ⅽ": "C", "Ⅾ": "D", "Ⅿ": "M",
    "ⅰ": "i", "ⅱ": "ii", "ⅲ": "iii", "ⅳ": "iv", "ⅴ": "v", "ⅵ": "vi",
    "ⅶ": "vii", "ⅷ": "viii", "ⅸ": "ix", "ⅹ": "x", "ⅺ": "xi", "ⅻ": "xii",
    "ⅼ": "l", "ⅽ": "c", "ⅾ": "d", "ⅿ": "m",
}
_ROMAN_NUMERAL_RE = re.compile("[" + "".join(_ROMAN_NUMERAL_MAP) + "]")


def _normalize_roman_numerals(text: str) -> str:
    """로마 숫자 유니코드 → 해당 로마자(제36항). 멱등 — 재적용해도 변화 없음."""
    return _ROMAN_NUMERAL_RE.sub(lambda m: _ROMAN_NUMERAL_MAP[m.group()], text)

_FORMULA_RE      = re.compile(r"<!수식>(.*?)<!/수식>", re.DOTALL)
_TAG_RE          = re.compile(r"<[^>]+>")
# 잔여 <!…> 정식 태그만 안전 제거(아래 _ANGLE_LABEL_RE가 본문 <…>를 살린 뒤).
_RESIDUAL_BANG_TAG_RE = re.compile(r"<!/?[^>]*>")
# <보기>·<학습 활동>처럼 한글/영문으로 시작하는 꺽쇠 묶음은 마크업이 아니라 본문이다.
# 홑화살괄호 〈 〉로 바꿔 점역한다(빈 결과 금지·문장 부호 제13절). 부등호(< 10 …)는
# 공백·숫자로 시작하므로 매칭되지 않아 그대로 수학 기호로 처리된다.
_ANGLE_LABEL_RE  = re.compile(r"<([가-힣A-Za-z][^<>]*)>")

# 텍스트 안의 LaTeX 수식 구분자 → <!수식> 태그 정규화(P1: 인라인 수식 라우팅).
# MinerU/추출 텍스트는 수식을 $…$ · $$…$$ · \(…\) · \[…\]로 내보낸다. 이를 수식 태그로
# 감싸야 _FORMULA_RE 분리에서 convert_latex 경로를 타고(본문은 한글 점자), 안 그러면
# \frac·\sqrt 같은 명령어가 영어 단어로 음역된다. $$를 $보다 먼저 매칭하도록 순서 주의.
_INLINE_MATH_RE = re.compile(
    r"\$\$(.+?)\$\$"          # $$ … $$  (디스플레이 수식)
    r"|\$(.+?)\$"            # $ … $    (인라인 수식)
    r"|\\\((.+?)\\\)"        # \( … \)
    r"|\\\[(.+?)\\\]",       # \[ … \]
    re.DOTALL,
)
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
        return _safe_to_unicode(text)
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
            result.append(_safe_to_unicode(pre))
        result.append(m.group())
        last = m.end()
    tail = text[last:]
    if tail:
        result.append(_safe_to_unicode(tail))


def _preprocess_units(text: str) -> str:
    """숫자 바로 뒤 알파벳에 공백 삽입 — braillify가 로마자로 인식하도록."""
    return _DIGIT_ALPHA_RE.sub(" ", text)


# ── 점자 도서 표기 관행(BOOK_STYLE) ────────────────────────────────────────────
# 정답 도서(수능특강 점역본 1131p 전수 관찰)는 「한국 점자 규정」 제49항과 다르게 적는 자리가
# 있다. 아래 1~5가 그 목록이다.
#
# ★ 기본값은 규정이다(태민 2026-07-17). 보유한 묵자-점자 도서가 규정을 완벽히 준수하진
#   않으므로 규정을 정답으로 본다. BRAILLE_STYLE=book 이면 도서 관행으로 되돌린다.
#
# ⚠ 대가: 우리 KPI(무수정 사용률)는 그 도서를 정답으로 놓고 잰다. 규정 모드는 도서와
#   약 10,700곳에서 어긋나므로 측정치가 떨어진다. 지표 문제만이 아니라 — 실제 점역사가
#   도서 관행대로 쓰는 사람이면 우리 출력을 고치므로 무수정 사용률이 실제로 떨어진다.
#   그래서 관행 경로를 지우지 않고 스위치로 남긴다. 두 모드 수치 비교는
#   workspace/reports/regulation_vs_book.md.
#
#   1) 표시 문자 괄호: (가)·(1) → 붙임표로 감싼다  -가-  (정답: -가- 1217회 / -1- 281회.
#      일반 괄호는 규정 소괄호를 그대로 쓴다 — 730회. 영문 (A)(B)도 소괄호 유지 — 124/74회)
#   2) 화살괄호: 〈보기〉·《…》 → 작은따옴표 ‘보기’ (정답 코퍼스에 화살괄호 0회, 작은따옴표 3618회)
#   3) 물결표: ~·∼ → 줄표 ― (정답에 물결표 0회 / 줄표 2004회. 범위 표기 "㉠~㉤"도 줄표)
#   4) 표시 문자 자모 뒤 마침표 생략: "ㄱ. 내용" → "ㄱ 내용" (정답은 온표+자모만 적고 마침표 없음)
#   5) 동그라미 문자: 규정 제64항은 ⠶…⠶로 묶으라 하지만(㉠=⠶⠿⠁⠶, ⓐ=⠶⠴⠁⠶), 도서는 묶음 없이
#      맨 글자로 적는다(㉠=⠿⠁ 온표+자모(제8항), ⓐ=⠴⠁⠠⠤ 로마자표+글자+종료표).
#      → 원문에서 동그라미를 벗겨 맨 글자로 넘긴다. symbol_table.json은 규정 정본이라 손대지 않는다.
_BOOK_STYLE = os.environ.get("BRAILLE_STYLE", "regulation") == "book"

# 동그라미 문자 → 맨 글자 (숫자 ①은 규정=도서 일치(수표+숫자)라 건드리지 않는다)
_CIRCLED = {chr(0x3260 + i): ch for i, ch in enumerate("ㄱㄴㄷㄹㅁㅂㅅㅇㅈㅊㅋㅌㅍㅎ")}
_CIRCLED.update({chr(0x326E + i): ch for i, ch in enumerate("가나다라마바사아자차카타파하")})
_CIRCLED.update({chr(0x24D0 + i): chr(ord("a") + i) for i in range(26)})   # ⓐ~ⓩ
_CIRCLED.update({chr(0x24B6 + i): chr(ord("A") + i) for i in range(26)})   # Ⓐ~Ⓩ
_CIRCLED_RE = re.compile("[" + "".join(_CIRCLED) + "]")

# 괄호 안이 한글·숫자면 붙임표로 감싼다. 영문이 섞이면 규정 소괄호를 유지한다.
# 정답: -가- 1217 · -나- 663 · -1- 281 · "소계-해당 인구-  100.0-2,575-"(표) …
#       소괄호(⠦⠄…⠠⠴)는 730회로 (A)(B) 같은 로마자 표기에 남아 있다.
_MARK_PAREN_RE = re.compile(r"\(([^()A-Za-z\n]{1,12})\)")
_ANGLE_RE = re.compile(r"[〈《<]([^〈《<>》〉\n]{1,20})[〉》>]")
_TILDE_RE = re.compile(r"[~∼〜]")
# 어절 경계에 홀로 선 자모 + 마침표 (항목 머리표 "ㄱ." "ㄴ.")
_JAMO_MARK_RE = re.compile(r"(?<![가-힣A-Za-z0-9])([ㄱ-ㅎ])\.(?=\s|$)")
# 문항 번호: 요소 첫머리 숫자 뒤에 본문이 이어질 때만 마침표를 붙인다("3\n다음은…" → "3.").
# 뒤에 아무것도 없는 숫자(페이지 번호 "16")는 그대로 둔다 — 정답도 마침표를 안 찍는다.
_QNUM_RE = re.compile(r"^(\d{1,2})(?=\s+\S)")
# 줄머리 불릿(•▪·◦)은 지우지 않는다 — layout._apply_bullet_marker가 ○□△와 같은 방식으로
# 정답 도서의 글머리표 ⠔⠔로 정정한다(아래 근거). 여기서 지우면 그 기회가 사라진다.
#   규정 제72항은 •를 ⠸⠲(_4)로 지정하지만 정답 코퍼스 1131p에 _4는 0회,
#   ⠔⠔(99)가 2,642회(줄머리 454 / 중간 20). 원문 '•' 시작 줄 ↔ 정답 대조 10/11 일치.
#   (2026-07-16 이전엔 "정답은 글머리를 안 찍는다"고 보고 지웠으나 전수 확인 결과 오판)


def _apply_book_style(text: str) -> str:
    """도서 관행 표기로 원문을 다듬는다(점역 경로 전용 — text_list 원문은 그대로 둔다)."""
    if not _BOOK_STYLE:
        return text
    text = _QNUM_RE.sub(r"\1.", text)
    text = _CIRCLED_RE.sub(lambda m: _CIRCLED[m.group()], text)
    text = _MARK_PAREN_RE.sub(r"-\1-", text)
    text = _ANGLE_RE.sub(r"‘\1’", text)
    text = _TILDE_RE.sub("―", text)
    return _JAMO_MARK_RE.sub(r"\1", text)


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


# ── 인라인 태그 파서 (점역 직전 텍스트 → 점자 마커) — plan §3-5 ──────────────
# 형식: 여는 <!이름>, 닫는 <!/이름>. 유일 인식 앵커 <!. 정규식 옵션 슬래시.
# 매핑은 다대일(태그명 달라도 점자 동일 가능). 미지 태그는 안전 제거(점자화로 안 깨뜨림).
_TAG_TOKEN_RE = re.compile(r"<!/?[^>]+>")

# 단일·대칭 인라인 마커: 태그명 → 점자 글리프
_TAG_INLINE_MARKER: dict[str, str] = {
    "점역자주": "⠠⠄",   # BBPG-1.2.6 점역자 주 — 양끝 동일(대칭)
    "빈칸_표":   "⠿⠿",   # 표 기입칸
    "빈칸_네모": "⠸⠦",   # 체크박스 □
}

# 비대칭 인라인 마커: (여는, 닫는)
_TAG_PAIR_MARKER: dict[str, tuple[str, str]] = {
    # 규정 제56항: 밑줄·드러냄표로 강조된 글자체 = ⠠⠤ … ⠤⠄ (정답 도서 1204회)
    "드러냄": ("⠠⠤", "⠤⠄"),
}

# 테두리(글상자 = 표, BBPG-1.2.5): (캡, 채움) 글리프. 32칸 한 줄로 렌더.
_BORDER_FILL: dict[str, tuple[str, str]] = {
    "테두리_위":   ("⠿", "⠛"),  # 위: 첫/끝 = , 중간 g
    "테두리_아래": ("⠿", "⠶"),  # 아래: 첫/끝 = , 중간 7
}
from app.ai.braille.constants import COLS as _BORDER_COLS  # noqa: E402 (공용 상수)
_BORDER_BLANK     = "⠀"   # 점자 빈칸(U+2800)
_BORDER_LEFT_FILL = 4     # 캡 뒤 채움 칸 → 제목 7칸에서 시작(BBPG-1.2.5(4)②: 캡1+채움4+빈칸1)

# 신형식 <!이름>…<!/이름> + 구형식 <!이름>…<!이름> 모두 수용(닫기 슬래시 옵션).
# 위계: 이름 뒤 단계 숫자 옵션(<!테두리_위2>=2단계, 없으면 1단계). group(1)=단계, group(2)=제목.
_BORDER_PAIR_RE = {
    name: re.compile(rf"<!{re.escape(name)}([23]?)>(.*?)<!/?{re.escape(name)}\1>", re.DOTALL)
    for name in _BORDER_FILL
}


def _border_line(name: str, title_braille: str) -> str:
    """글상자/표 테두리 32칸 줄. 제목 있으면 BBPG-1.2.5(4)② 배치(7칸, 양옆 띔)."""
    cap, fill = _BORDER_FILL[name]
    inner = _BORDER_COLS - 2
    if not title_braille:
        return cap + fill * inner + cap
    # 케이스②: 캡1 + 채움4 + 빈칸1 + 제목 + 빈칸1 + 채움R + 캡1 = 32
    max_title = inner - _BORDER_LEFT_FILL - 2          # = 24
    t = title_braille[:max_title]                       # 초과 시 클립(케이스① 윗줄 5칸은 TODO: layout)
    right_fill = inner - _BORDER_LEFT_FILL - 2 - len(t)
    return (cap + fill * _BORDER_LEFT_FILL + _BORDER_BLANK
            + t + _BORDER_BLANK + fill * right_fill + cap)


# 글상자 테두리 태그(위/아래, 위계 옵션) 문서 순서 수집 — box_borders(BBPG-1.2.5) layout 재렌더
# group(1)=이름, group(2)=단계 숫자(옵션), group(3)=제목
_BORDER_ANY_RE = re.compile(r"<!(테두리_위|테두리_아래)([23]?)>(.*?)<!/?\1\2>", re.DOTALL)
_BORDER_KIND = {"테두리_위": "top", "테두리_아래": "bottom"}


def box_borders_from_source(source_text: str) -> list[tuple[str, int, str]]:
    """원본의 글상자 테두리 태그를 문서 순서대로 (kind, level, 제목점자)로 수집(BBPG-1.2.5).

    layout이 이 목록으로 위계별 테두리·제목 배치(중간7칸/윗줄5칸/케이스①)를 재렌더한다.
    translator는 인라인 32칸 테두리(위치 마커, 항상 1단계 ⠿ 형식)도 그대로 둔다(_border_line).
    위계: 태그 이름 뒤 단계 숫자(<!테두리_위2>=2단계, 없으면 1단계). ※§3-5 태그 규약 확장(태민 검토).
    """
    out: list[tuple[str, int, str]] = []
    for m in _BORDER_ANY_RE.finditer(source_text):
        kind = _BORDER_KIND[m.group(1)]
        level = int(m.group(2)) if m.group(2) else 1
        title_raw = (m.group(3) or "").strip()
        title = _braillify(title_raw) if (kind == "top" and title_raw) else ""
        out.append((kind, level, title))
    return out


TN_MARKER = "⠠⠄"  # 점역자 주 점자 마커 (BBPG-1.2.6), 양끝 동일


def _tag_name(token: str) -> str:
    """<!이름> / <!/이름> 토큰에서 이름만 추출 (닫기 슬래시 제거)."""
    return token[2:-1].lstrip("/")


def source_has_tn(text: str) -> bool:
    """원본(점역 전) 텍스트에 점역자 주 마커(⠠⠄)를 만드는 태그가 있는지.

    출력 점자만 스캔하면 ∽(닮음)·ː(장음) 등 동일 점형(⠠⠄)을 점역자 주로 오인한다(B1 오탐).
    점역자 주 마커는 오직 태그에서만 삽입되므로, '원본 태그 유무'로 emit을 판정한다.
    """
    return any(
        _TAG_INLINE_MARKER.get(_tag_name(m.group(0))) == TN_MARKER
        for m in _TAG_TOKEN_RE.finditer(text)
    )


def tn_marker_spans(braille: str, source_text: str | None = None) -> list[tuple[int, int, str]]:
    """점역 결과 점자에서 점역자 주 마커(⠠⠄) 위치 → (start, end, tag) 목록.

    첫 마커 = tn_open, 마지막 마커 = tn_close (TN은 내용 전체를 감싸므로 최외곽이 양끝).
    rule_trail 점자 좌표 emit용 (plan §3-4·§3-5). 마커 없으면 빈 목록.

    source_text를 주면 그 원본에 점역자 주 태그가 있을 때만 emit한다 —
    ∽·ː 등 동일 점형(⠠⠄)을 점역자 주로 오인하는 B1 오탐 방지.
    (점자 좌표 정밀 보정은 Phase B 좌표 배선과 함께 처리.)
    """
    if source_text is not None and not source_has_tn(source_text):
        return []
    i = braille.find(TN_MARKER)
    if i == -1:
        return []
    w = len(TN_MARKER)
    spans = [(i, i + w, "tn_open")]
    j = braille.rfind(TN_MARKER)
    if j != i:
        spans.append((j, j + w, "tn_close"))
    return spans


# 리터럴 점역자주 마커 방어: LLM·외부 입력이 태그 대신 리터럴(【점역자주】·[점역자주])을
# 내면 대괄호+한글 음절 21셀이 통째로 점자화된다(2026-07-17 실측 — <!태그> 형식을 쓰는 이유).
# 쌍 단위로 <!점역자주>/<!/점역자주>로 승격하고, 홀수 잔여는 제거한다.
_LITERAL_TN_RE = re.compile(r"【점역자주】|\[점역자주\]")


def _promote_literal_tn(text: str) -> str:
    n = [0]

    def _sub(m: re.Match) -> str:
        n[0] += 1
        return "<!점역자주>" if n[0] % 2 else "<!/점역자주>"

    out = _LITERAL_TN_RE.sub(_sub, text)
    if n[0] % 2:                       # 홀수 — 마지막으로 승격된 여는 태그가 짝이 없다
        i = out.rfind("<!점역자주>")
        if i >= 0:
            out = out[:i] + out[i + len("<!점역자주>"):]
        logger.warning("translator: 리터럴 점역자주 마커 홀수(%d) — 마지막 1개 제거", n[0])
    if n[0]:
        logger.info("translator: 리터럴 점역자주 마커 %d개를 태그로 승격", n[0])
    return out


def substitute_tags(text: str) -> str:
    """인라인 태그(<!이름>/<!/이름>)를 점자 마커로 치환. 미지 태그는 안전 제거.

    치환 결과는 점자 Unicode이므로 이후 _emit_mixed/braillify가 보존한다(이중 변환 없음).
    """
    text = _promote_literal_tn(text)
    # 1) 테두리 쌍 (중간 제목 가능) → 32칸 줄(위치 마커). 위계는 box_borders로 layout이 재렌더.
    for name, pat in _BORDER_PAIR_RE.items():
        text = pat.sub(
            lambda m, n=name: _border_line(n, _braillify(m.group(2).strip())), text
        )

    # 2) 단일·대칭 인라인 마커 + 미지 태그 제거
    def _token_sub(m: re.Match) -> str:
        tok = m.group(0)
        name = _tag_name(tok)  # "<!" ... ">" 안쪽, 닫기 슬래시 제거
        if name in _TAG_INLINE_MARKER:
            return _TAG_INLINE_MARKER[name]
        if name in _TAG_PAIR_MARKER:
            return _TAG_PAIR_MARKER[name][1 if tok.startswith("<!/") else 0]
        logger.warning("translator: 미지 태그 제거 %s", tok)
        return ""

    text = _TAG_TOKEN_RE.sub(_token_sub, text)
    # 3) 잔여 <!…> 정식 태그만 제거. 그 밖의 <보기>류는 본문이므로 삭제 금지 —
    #    홑화살괄호 〈 〉로 바꿔 점역(빈 결과 금지). symbol_table이 〈=⠐⠶·〉=⠶⠂로 치환.
    text = _RESIDUAL_BANG_TAG_RE.sub("", text)
    return _ANGLE_LABEL_RE.sub(r"〈\1〉", text)


def _translate_with_braillify(text: str) -> str:
    parts = _FORMULA_RE.split(text)
    chunks: list[tuple[bool, str]] = []  # (is_formula, braille)

    for i, part in enumerate(parts):
        if i % 2 == 0:  # 일반 텍스트 세그먼트
            clean = substitute_tags(part)
            if i > 0:                # 수식 직후: 앞 공백 제거
                clean = clean.lstrip()
            if i < len(parts) - 1:  # 수식 직전: 뒤 공백 제거
                clean = clean.rstrip()
            if clean:
                preprocessed = _preprocess_units(_apply_book_style(clean))
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
    result = substitute_tags(result)
    result = substitute_symbols(result)
    return _braillify_fallback(result)


# braillify가 거부하는 문자: PUA(사설영역)·비공백 제어문자.
# 한컴/HWP 수식 폰트는 수식 글리프를 PUA(U+E000~)로 인코딩 → PyMuPDF가 매핑 없는
# raw 코드포인트로 추출한다. 한 글자라도 braillify에 들어가면 "Invalid symbol character"
# 예외로 요소 전체가 [처리 불가]가 되므로(빈 결과 금지 위반), 정화해 견고하게 만든다.
# PUA가 많은 페이지 자체는 pdf_analyzer가 STANDARD(MinerU)로 라우팅한다(텍스트레이어 비신뢰).
_BRAILLIFY_HOSTILE_RE = re.compile(
    r"[-\U000f0000-\U0010fffd\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f]+"
)


# braillify가 거부하는 비-PUA 특수문자 → 받아들이는 등가물(품질 보존).
# 전각 ASCII(U+FF01~FF5E)는 코드포인트 산술로 반각화, 그 밖은 아래 표로.
# 거부 예: ～(전각물결) ｢｣(반각모서리) ，．？！（）；(전각문장부호) ◦(흰 불릿).
_SPECIAL_MAP = {
    "｢": "「", "｣": "」",            # 반각 모서리괄호 → 전각(symbol_table가 점역)
    "◦": "·", "◌": "·", "∘": "·",   # 흰 불릿류 → 가운뎃점
    "　": " ",                       # 전각 공백
}


def _normalize_special(s: str) -> str:
    out = []
    for ch in s:
        o = ord(ch)
        if 0xFF01 <= o <= 0xFF5E:        # 전각 ASCII → 반각(，．？！（）；～ 등)
            out.append(chr(o - 0xFEE0))
        else:
            out.append(_SPECIAL_MAP.get(ch, ch))
    return "".join(out)


def sanitize_for_braille(text: str) -> str:
    """braillify가 거부하는 문자를 안전화(요소 격리·빈 결과 금지).

    1) PUA·제어문자 런 → 단일 공백.
    2) 전각 문장부호·반각괄호·불릿 → 받아들이는 등가물(품질 보존).
    주변 한글·영문·숫자는 보존하고, 이중 공백은 이후 _collapse_spaces가 정리한다.
    """
    text = _BRAILLIFY_HOSTILE_RE.sub(" ", text)
    return _normalize_special(text)


def _safe_to_unicode(seg: str) -> str:
    """braillify 변환 + 최후 폴백. 정규화 후에도 남은 미지 글자가 줄 전체를 깨지 않도록,
    세그먼트가 실패하면 글자 단위로 변환하고 변환 불가 글자만 공백으로 대체한다."""
    try:
        return _braillify_lib.translate_to_unicode(seg)
    except Exception:  # noqa: BLE001 — 미지 글자 격리(줄 보존)
        out = []
        for ch in seg:
            try:
                out.append(_braillify_lib.translate_to_unicode(ch))
            except Exception:  # noqa: BLE001
                out.append(" ")
        return "".join(out)


def _normalize_inline_math(text: str) -> str:
    """텍스트 속 LaTeX 수식 구분자($…$ 등)를 <!수식>…<!/수식> 태그로 정규화한다.

    이미 <!수식> 태그가 있으면 그대로 두고, raw 수식 구분자만 감싼다. 빈 수식은 제거.
    이렇게 해야 수식이 convert_latex 경로로 라우팅되어 수학 점자로 변환된다(P1).
    """
    if "$" not in text and "\\(" not in text and "\\[" not in text:
        return text

    def _wrap(m: re.Match) -> str:
        inner = next((g for g in m.groups() if g is not None), "").strip()
        return f"<!수식>{inner}<!/수식>" if inner else ""

    return _INLINE_MATH_RE.sub(_wrap, text)


def translate_tagged_text(text: str) -> str:
    """<!수식> 태그가 포함된 텍스트를 점자 BRF로 변환."""
    text = _normalize_inline_math(text)     # $…$/\(…\) → <!수식> (P1: 수식 라우팅)
    text = _normalize_roman_numerals(text)  # 로마 숫자 → 로마자(제36항), braillify 거부 방지
    text = sanitize_for_braille(text)        # PUA·제어문자 정화(요소 전체 소실 방지)
    if _BRAILLIFY_AVAILABLE:
        return _translate_with_braillify(text)
    return _translate_fallback(text)


# ── 음절 단위 줄바꿈 지점 산출 (BBPG-1.2.1) ──────────────────────────────────
# 한글은 음절 단위, 외국어는 단어 단위 줄바꿈이 원칙. 운영 경로(braillify)는 약자를
# 적용해 음절↔점자 매핑이 불투명하므로, '접두 일관성'으로 약자를 깨지 않는 경계만 고른다:
# 어절[:b] 점역 결과가 어절 점역 전체의 접두이면 b는 안전한 줄바꿈 지점(약자가 b를
# 가로지르면 접두가 깨져 자동 제외). 숫자·로마자 런은 한 단위이므로 내부 후보를 만들지
# 않는다(접두 검사만으로는 ⠼⠃ ⊂ ⠼⠃⠑ 라 수 내부를 허용해버림).
_NUM_RUN_RE = re.compile(r"-?\d[\d.,]*")
_ROMAN_RUN_RE = re.compile(r"[A-Za-z]+")


def _no_cut_interior(src: str) -> list[bool]:
    """숫자·로마자 런 '내부' 위치 마스크 — 그 앞에서 줄바꿈 금지(단위 보존)."""
    mask = [False] * (len(src) + 1)
    for rx in (_NUM_RUN_RE, _ROMAN_RUN_RE):
        for m in rx.finditer(src):
            for i in range(m.start() + 1, m.end()):
                mask[i] = True
    return mask


def _break_offsets(src: str, braille: str) -> list[int]:
    """src(원문 한 줄)→braille의 줄바꿈 허용 셀 offset 목록(그 위치 '앞'에서 끊기 가능).

    접두 일관성 기반 — 안전(fail-safe): 잘못된 지점은 접두 불일치로 자동 탈락하고,
    드물게 놓친 경계는 그 어절이 통째로 다음 줄로 갈 뿐(규정 허용). 숫자/로마자 런
    내부는 마스크로 제외(단위 보존). 양 경로(braillify·fallback) 공통.
    """
    if len(braille) <= 1:
        return []
    offs: set[int] = set()
    # 바닥선: 출력 점자 공백 = 어절 경계, 항상 안전한 줄바꿈 지점(§1.2.1 단어 단위).
    # 한영 혼합 등 접두가 깨지는 경우에도 최소 어절 단위 줄바꿈은 보장한다.
    for i, ch in enumerate(braille):
        if ch in (" ", "⠀") and 0 < i < len(braille):
            offs.add(i)
    # 음절 단위: 약자를 깨지 않는 경계만 접두 일관성으로 추가(순수 한글에서 촘촘히).
    mask = _no_cut_interior(src)
    for sp in range(1, len(src)):
        if mask[sp]:
            continue
        pre = translate_tagged_text(src[:sp])
        if pre and len(pre) < len(braille) and braille.startswith(pre):
            offs.add(len(pre))
    return sorted(offs)


def translate_with_breaks(text: str) -> tuple[list[str], list[list[int]]]:
    """텍스트 → (논리 줄별 점자, 줄별 음절 줄바꿈 offset). 32칸 분리는 layout이 수행.

    원문 개행(\\n)으로만 논리 줄을 나눈다(하드 32분리 폐기 — 음절·지시부호·마커를
    칸 중간에서 쪼개지 않기 위함, §1.2.1). 각 줄의 break offset은 layout `_wrap_line`이
    32칸 줄바꿈에 사용한다.
    """
    lines: list[str] = []
    breaks: list[list[int]] = []
    for src_line in text.split("\n"):
        braille = translate_tagged_text(src_line)
        lines.append(braille)
        breaks.append(_break_offsets(src_line, braille))
    return (lines or [""], breaks or [[]])


# 수식 속 \text{한글}을 한글 점자로 변환하는 훅 등록(P2). kor_math_rules는 translator를
# import하지 않고(순환 회피) 런타임 주입만 받는다. 평문(한글)은 <!수식>·$ 가 없어
# translate_tagged_text가 convert_latex로 재진입하지 않으므로 무한 재귀가 없다.
from app.ai.braille import kor_math_rules as _kor_math_rules  # noqa: E402

_kor_math_rules.register_text_hook(translate_tagged_text)
