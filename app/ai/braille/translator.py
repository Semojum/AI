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
from app.ai.braille import eng_braille, inline_math
from app.ai.braille.constants import WRAP_HYPHEN_CLOSE, WRAP_HYPHEN_OPEN
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


# 섹션번호 로마 숫자(Ⅱ. Ⅲ. …)의 도서 관행: gold는 로마자표(⠴…⠲)·이중 대문자표 없이
# 대문자표 ⠠ 한 번 + 낱자 점형으로 적는다(Ⅱ→⠠⠊⠊, Ⅴ→⠠⠧ 실측 — 사회문화 p046·154,
# 세계사 p016). 영어 단어 경로(_english_run/braillify)는 ⠴⠠⠠⠊⠊⠲로 로만표·이중대문자·
# 종료표를 붙여 gold와 어긋난다(잉여 ⠲·⠴). 낱자 점형을 직접 주입해 관행에 맞춘다.
# 소문자 로마자(ⅰⅱ 하위항목)는 대문자표 없이 낱자만. <!수식> 안 로마자는 건드리지 않는다.
_ROMAN_CELL_UPPER = {r: "⠠" + "".join(_ALPHA_MAP[c] for c in ascii_low.lower())
                     for r, ascii_low in _ROMAN_NUMERAL_MAP.items() if ascii_low[0].isupper()}
_ROMAN_CELL_LOWER = {r: "".join(_ALPHA_MAP[c] for c in ascii_low)
                     for r, ascii_low in _ROMAN_NUMERAL_MAP.items() if ascii_low[0].islower()}
_ROMAN_CELL = {**_ROMAN_CELL_UPPER, **_ROMAN_CELL_LOWER}
_ROMAN_CELL_RE = re.compile("[" + "".join(_ROMAN_CELL) + "]")


def _book_roman_to_cells(text: str) -> str:
    """도서 관행 로마 숫자 섹션번호 → 낱자 점형 직접 주입(book 모드). <!수식> 세그는 보존."""
    parts = _FORMULA_RE.split(text)
    for i in range(0, len(parts), 2):   # 짝수 인덱스 = 수식 밖 일반 텍스트
        parts[i] = _ROMAN_CELL_RE.sub(lambda m: _ROMAN_CELL[m.group()], parts[i])
    # split이 캡처그룹 때문에 [text, formula_inner, text, ...] 형태 → 재조립
    out = []
    for i, seg in enumerate(parts):
        out.append(seg if i % 2 == 0 else f"<!수식>{seg}<!/수식>")
    return "".join(out)

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
    def _seg(seg: str) -> str:
        out = _safe_to_unicode(seg)
        # 붙임표(⠤) 뒤 순수 로마자 세그: 세그 분리로 한글 문맥이 사라져 braillify가
        # 로마자표를 못 붙인다. 정답 관행은 여는 ⠴만·종료표 생략(-⠴UN- , 사회문화
        # p100·108 실측, 교차 59건). 직전 결과가 ⠤로 끝날 때만 ⠴를 접두한다.
        if (result and result[-1].endswith("⠤")
                and seg.strip() and all(c.isalpha() and c.isascii() for c in seg.strip())):
            out = "⠴" + out
        return out

    last = 0
    for m in _BRAILLE_RE.finditer(text):
        pre = text[last:m.start()]
        if pre:
            result.append(_seg(pre))
        result.append(m.group())
        last = m.end()
    tail = text[last:]
    if tail:
        result.append(_seg(tail))


def _preprocess_units(text: str) -> str:
    """숫자 바로 뒤 알파벳에 공백 삽입 — braillify가 로마자로 인식하도록."""
    return _DIGIT_ALPHA_RE.sub(" ", text)


# ── 점자 도서 표기 관행(BOOK_STYLE) ────────────────────────────────────────────
# 정답 도서(수능특강 점역본 1131p 전수 관찰)는 「한국 점자 규정」 제49항과 다르게 적는 자리가
# 있다. 아래 1~5가 그 목록이다.
#
# ★ 기본값은 관행(book)이다(태민 2026-07-17 재판정). "텍스트는 거의 틀리면 안돼"의 잣대가
#   정답 도서이고, 실제 점역사도 이 표기로 검수한다. 시각자료의 관행/규정 갈림은 4안 제공
#   (visual_drafts — 생략/제목/개조식/줄글)으로 점역사가 고르게 해 모드 선택 자체를 없앤다.
#   BRAILLE_STYLE=regulation 이면 규정 표기로 전환(경로·테스트 유지).
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
#   5) 동그라미 자모·음절: 규정 제64항은 ⠶…⠶로 묶으라 하지만 도서는 맨 글자로 적는다
#      (㉠=⠿⠁ 온표+자모(제8항), gold =a 실측 일치) → 자모·음절은 맨 글자 유지.
#      ★동그라미 로마자 ⓐ~ⓩ는 정정(2026-07-19): 구현이 맨글자 'a'였는데 이는 규정(70a7=
#      ⠶⠴⠁⠶, 제64항 예시)도 코퍼스 관행(-0a-=⠤⠴⠁⠤, 생물 4p 일관 실측)도 아닌 제3형.
#      규정 우선 원칙(태민)에 따라 제64항형을 직접 점자로 낸다. 측정은 kpi canon이
#      관행형(⠤⠴x⠤)을 등가 인정. symbol_table.json은 규정 정본이라 손대지 않는다.
_BOOK_STYLE = os.environ.get("BRAILLE_STYLE", "book") != "regulation"

# 동그라미 자모·음절 → 맨 글자 (숫자 ①은 규정=도서 일치(수표+숫자)라 건드리지 않는다)
_CIRCLED = {chr(0x3260 + i): ch for i, ch in enumerate("ㄱㄴㄷㄹㅁㅂㅅㅇㅈㅊㅋㅌㅍㅎ")}
_CIRCLED.update({chr(0x326E + i): ch for i, ch in enumerate("가나다라마바사아자차카타파하")})
# 동그라미 로마자 → 규정 제64항형 점자(⠶ + 로마자표 ⠴ + 글자 + ⠶; 대문자는 ⠠ 추가)
_CIRCLED.update({chr(0x24D0 + i): "⠶⠴" + _ALPHA_MAP[chr(ord("a") + i)] + "⠶"
                 for i in range(26)})   # ⓐ~ⓩ
_CIRCLED.update({chr(0x24B6 + i): "⠶⠴⠠" + _ALPHA_MAP[chr(ord("a") + i)] + "⠶"
                 for i in range(26)})   # Ⓐ~Ⓩ
_CIRCLED_RE = re.compile("[" + "".join(_CIRCLED) + "]")

# 괄호 안이 한글·숫자면 붙임표로 감싼다. 영문이 섞이면 규정 소괄호를 유지한다.
# 정답: -가- 1217 · -나- 663 · -1- 281 · "소계-해당 인구-  100.0-2,575-"(표) …
#       소괄호(⠦⠄…⠠⠴)는 730회로 (A)(B) 같은 로마자 표기에 남아 있다.
# 붙임표 감쌈 대상: 한글·숫자 괄호 + 소문자 포함 영문(단어·구 — 정답 p133 '(Yir Yoront)'
# → -⠴yir yoront- 실측). 대문자·숫자만인 약어 (A)·(SNS)는 소괄호 유지(코퍼스 124/74회).
# 개행 허용·상한 60: MinerU가 괄호 안에 줄바꿈을 넣거나 긴 문장 괄호(정답 p026 실측:
# 문장 전체 괄호도 붙임표)가 있어 줄 단위·20자 규칙이 교차 131건을 놓쳤다(2026-07-18).
_MARK_PAREN_RE = re.compile(r"\(([^()]{1,60})\)")
_UPPER_ONLY_RE = re.compile(r"^[A-Z0-9 ,.·]+$")

# ── 감쌈 붙임표 자리표시자 (x2-a) ─────────────────────────────────────────────
# _paren_repl이 내는 감쌈용 붙임표는 '원문 하이픈'이 아니라 조판 기호다. 그런데
# translate_with_breaks가 요소 단위로 감쌈을 먼저 적용하므로, 그 결과 하이픈이
# 뒤따르는 줄 단위 경로의 _NEG_NUM_RE(음수 부호)에 다시 걸린다 —
# "(2010 수능)" → "-2010 수능-" → ⠔(뺄셈표)⠼⠃⠚⠁⠚…. _NEG_NUM_RE의 가드는 바로
# 붙은 닫는 하이픈("-2010-")만 배제해서 공백이 끼면 뚫린다.
# 그래서 감쌈 하이픈만 비-ASCII 자리표시자로 표시해 음수 판정 구간을 통과시키고,
# 판정이 끝난 자리에서 원래 하이픈으로 되돌린다(symbol_table의 -=⠤를 그대로 태우기
# 위함). 자리표시자는 유니코드 비문자(U+FDD0/1) — 실문서에 나올 수 없고
# sanitize_for_braille의 PUA·제어문자 범위에도 걸리지 않는다.
# ★ inline_math는 이 표식을 하이픈과 같은 수식 원자로 친다 — 아니면 수식 구간이
#   표식에서 쪼개져 라우팅이 달라진다(수학2 173요소 실측). 정의는 constants 공유.
_WRAP_OPEN = WRAP_HYPHEN_OPEN
_WRAP_CLOSE = WRAP_HYPHEN_CLOSE
_WRAP_RESTORE = {ord(_WRAP_OPEN): "-", ord(_WRAP_CLOSE): "-"}


def _restore_wrap_hyphen(s: str) -> str:
    """감쌈 자리표시자 → 원래 붙임표(-). 자리표시자가 없으면 무해한 no-op."""
    return s.translate(_WRAP_RESTORE)


# 출처/연도 대괄호 → 소괄호 관행(정답 도서 실측: 생물 p009 '[2011학년도 대수능]',
# p012 '[실험 과정]'·'[실험 결과]' → gold는 소괄호 셀 ⠦⠄…⠠⠴로 적는다. 대괄호 셀
# ⠦⠆…⠰⠴가 아니다). ⚠ 세계사 '[1096~1270]' 같은 연대 범위 대괄호는 gold가 대괄호를
# 그대로 유지하므로(⠦⠆…⠰⠴, 33/35회 실측) 건드리면 안 된다 — 출처/실험 표제 키워드가
# 든 대괄호만 소괄호로 바꾼다(문맥 가드). 소괄호를 '문자'로 넣으면 _MARK_PAREN_RE가
# 붙임표 -…-로 감싸버리므로(gold는 붙임표 아님), 소괄호 셀을 직접 주입한다.
_OPEN_PAREN_CELL = "⠦⠄"
_CLOSE_PAREN_CELL = "⠠⠴"
_SRC_BRACKET_RE = re.compile(r"\[([^\[\]\n]{1,40})\]")
_SRC_ATTR_RE = re.compile(
    r"수능|학년도|평가원|모의평가|모의고사|모평|학력평가|학평|기출|교육청|실험\s*과정|실험\s*결과")
# 지문 라벨 대괄호 [A]~[Z] → 소괄호 관행(정답 도서 실측: gold ⠦⠄⠴⠠x⠠⠴ = 소괄호+로마자표+
# 대문자표+글자. val 170/172·dev 38/38이 소괄호. 언어 지문 "[A]의 '갑'은…" 라벨이 대표).
# 대괄호 셀 ⠦⠆…⠰⠴로 내면 어긋나므로 소괄호 셀을 직접 주입(출처 대괄호와 동형 처리).
_BR_UPPER_RE = re.compile(r"^[A-Z]$")
# 문항 번호·범위 대괄호 [01~03]·[16] → 소괄호 관행(gold 범위 57/57·10/10, 숫자 20/20).
# ⚠ 4자리 연대 범위 [1096~1270]은 gold가 대괄호 유지(33/35 실측)라 \d{1,2}로 제외한다.
_BR_NUMRANGE_RE = re.compile(r"^\d{1,2}(?:\s*[~∼〜]\s*\d{1,2})?$")


def _src_bracket_repl(m: re.Match) -> str:
    inner = m.group(1).strip()
    if _SRC_ATTR_RE.search(inner):
        return _OPEN_PAREN_CELL + inner + _CLOSE_PAREN_CELL
    if _BR_UPPER_RE.match(inner):
        # gold 정확형 ⠦⠄⠴⠠x⠠⠴ 직접 주입(로마자표+대문자표 포함, CER·텍스트 축 동시 정합)
        return _OPEN_PAREN_CELL + "⠴⠠" + _ALPHA_MAP[inner.lower()] + _CLOSE_PAREN_CELL
    if _BR_NUMRANGE_RE.match(inner):
        # 소괄호 셀 + 원문 숫자(수표·범위 줄표는 이후 단계가 부여)
        return _OPEN_PAREN_CELL + inner + _CLOSE_PAREN_CELL
    return m.group(0)


_HANJA_ONLY_RE = re.compile(r"^[\u4e00-\u9fff\s·]+$")


def _paren_repl(m: re.Match) -> str:
    inner = m.group(1)
    if _HANJA_ONLY_RE.match(inner):
        return ""                  # 한자 병기 괄호는 통째 생략 (정답 언어 p053 '과목(果木)'→'과목')
    if len(inner) == 1 and inner.isalpha() and inner.isascii():
        # 단일 대문자 라벨 (A)(B)(C) → 붙임표 관행(정답 도서 실측: gold ⠤⠴⠠x⠤ =
        # 붙임표+로마자표+대문자표+글자. 전 과목 500/522, 소괄호 0건. 외국어 444·생물 54·
        # 언어 8·사회문화 6·세계사 4·수학2 2). 구 코드는 소괄호(⠦⠄…⠠⠴)로 내 gold와
        # 어긋나고 로마자표도 빠졌다("124/74회 소괄호"는 오측이었다). 소괄호 셀을 문자로
        # 넣으면 자신을 재귀 감싸므로 정확형 셀을 직접 주입한다.
        # ⚠ 소문자 (x)(t)는 수학2에서 수식 변수 f(x)(수식괄호 1609건)라 건드리지 않고
        #   종전 형을 유지한다 — 대문자 라벨만 바꾼다.
        if inner.isupper():
            # ⚠ 배열형 답지 (A)-(B)-(C)(문단 순서 문제, 외국어 문단배열)는 gold가 붙임표도
            #   소괄호도 아닌 동그라미형 묶음 ⠶⠠x⠶(제64항 계열, gold 516건 전부 외국어)으로
            #   적는다. 붙임표를 씌우면 연결 붙임표(-)와 셀이 겹쳐 오히려 어긋난다(실측:
            #   p123 단독 +235셀). 괄호+연결부호로 이어진 배열형이면 gold 정확형을 낸다.
            after = m.string[m.end():]
            before = m.string[:m.start()]
            if re.match(r"\s*[-–—~∼〜]\s*\(", after) or re.search(r"\)\s*[-–—~∼〜]\s*$", before):
                return "⠶⠠" + _ALPHA_MAP[inner.lower()] + "⠶"
            return "⠤⠴⠠" + _ALPHA_MAP[inner.lower()] + "⠤"
        return m.group(0)          # 소문자 (x)는 종전 유지(수식 변수 회귀 방지)
    # 대문자 약어 (SNS)도 붙임표 — "약어는 소괄호" 가정은 dev·val 교차 스캔에서 어긋
    # 최다(21건)로 판명, 정답 실측 '-⠴SNS-' (사회문화 p062, 2026-07-18 정정).
    # 감쌈 붙임표는 자리표시자로 낸다(위 _WRAP_OPEN 주석) — 하류의 음수 판정이
    # 이 하이픈을 뺄셈표로 재해석하지 못하게 하고, 판정 뒤 원래 -로 되돌린다.
    return f"{_WRAP_OPEN}{inner}{_WRAP_CLOSE}"
_ANGLE_RE = re.compile(r"[〈《<「『]([^〈《<>》〉「」『』\n]{1,20})[〉》>」』]")
# 문중 빈칸 네모 □ — 숨김표(제49항 표: ×=_xl=⠸⠭⠇)로 적되 ⠭를 글자 수만큼 반복한다
# (정답 생물 p046 실측: _xl·_xxl·_xxxl — □ 1·2·3글자).
# 줄머리 □은 원래 전부 제외(글머리 제72항 불릿)했으나, 오디코딩 복원(⇂→□) 후 줄머리
# 빈칸이 200건 나타나면서 재검토 — 실측상 진짜 불릿은 '단독 □ + 공백'뿐이고, 줄머리
# '□는·□이라고'(붙은 조사)·'□□…'(복수)는 전부 빈칸이다(genuine □ 14건도 모두 빈칸).
# 그래서 '줄머리 단독 □ + (공백|줄끝)'만 불릿으로 남기고 나머지는 빈칸으로 본다.
_BOX_BLANK_RE = re.compile(r"□+", re.M)


def _box_blank_repl(m: re.Match) -> str:
    """□런 → 숨김표 틀 ⠸⠭ⁿ⠇. 줄머리 단독 □+공백은 제72항 불릿이라 braillify에 맡긴다."""
    s, run = m.string, m.group()
    at_line_start = m.start() == 0 or s[m.start() - 1] == "\n"
    after = s[m.end():m.end() + 1]
    if at_line_start and len(run) == 1 and (after == "" or after in " \t\n"):
        return run                      # 줄머리 단독 □ + 공백/줄끝 = 글머리 불릿
    return "⠸" + "⠭" * len(run) + "⠇"
_TILDE_RE = re.compile(r"[~∼〜]")
# MinerU는 〈보기〉 상자를 괄호 없이 '보기\x00'로 낸다. 정답 관행은 위치별로 다르다
# (생물 p011 원본 27-28행 실측): **문중 참조 = ‘보기’(따옴표), 박스 제목 줄 = 맨 '보기'**.
# 단독 줄은 잡음(\x00·공백)만 정리하고 맨 글자로 둔다 — ‘보기’ 감쌈은 val 99건 역효과로
# 판명된 과적합이었다(2026-07-17 정정).
_BOGI_LINE_RE = re.compile(r"(?m)^[ \t]*(보기)[ \t\x00]*$")
# MinerU가 문중 〈보기〉를 박스로 떼어내면 문장에 "…만을 에서 …" 구멍이 남는다
# (생물 p011·026·053 실측, 수능 정형구 "옳은 것만을 〈보기〉에서 있는 대로 고른 것은?").
# 조사 '만을' 바로 뒤 '에서'는 이 소실뿐이라 ‘보기’를 복원한다.
_BOGI_GAP_RE = re.compile(r"(만을)\s+(에서)")
# MinerU 마크다운 잔재 백틱이 숫자·한글 사이에 끼면 수가 갈라진다('41`쪽'→#d#a, 수학2 p061).
_NOISE_BACKTICK_RE = re.compile(r"(?<=[0-9가-힣])`(?=[0-9가-힣])")
# 한컴 수식 마크 백틱: `f(x)=0 처럼 백틱+영문 시작 구간은 인라인 수식이다(수학2 p016·036·052
# 실측 — 정답은 수학 괄호 ⠦…⠴, 텍스트 괄호로 점역하면 어긋 dev11/val44). 한글 앞까지를
# 수식 태그로 라우팅해 convert_latex가 처리하게 한다.
# 문자 집합에 감쌈 자리표시자를 하이픈과 같이 넣는다 — 빼면 "`f(1)의"처럼 감쌈이 낀
# 백틱 수식이 구간을 못 이뤄 텍스트 경로로 새고 로마자표가 붙는다(수학2 실측).
_BACKTICK_MATH_RE = re.compile(
    r"`\s*([A-Za-z][A-Za-z0-9(){}\[\]=+\-*/^'′,.\s"
    + WRAP_HYPHEN_OPEN + WRAP_HYPHEN_CLOSE + r"]*?)(?=[가-힣]|$|\n)")
# 앰퍼샌드: 규정 [다만]은 한글 사이 &를 로마자표 감쌈 ⠴⠈⠯⠲(0@&4 예시 명시)으로, 정답
# 도서는 ⠯ 단독(이탈 — regulation_vs_book 기록). book=⠯, regulation=규정 그대로(symbol_table).
_AMP_RE = re.compile(r"\s*&\s*")
# 한컴 수식폰트 잡음: MinerU가 ≥를 æ로 낸다('(분자의 차수)æ(분모의 차수)', 수학2 p005).
# 외국어 발음기호 [dæd]와 충돌하지 않게 수학 문맥(괄호·숫자·한글 인접)만 복원.
_AE_GEQ_RE = re.compile(r"(?<=[)\d가-힣])\s*æ\s*(?=[(\d가-힣])")
# ❌ 폐기(2026-07-18): "문항 부정어 드러냄 생략" 규칙은 과적합이었다. dev 2페이지(p024·p023)
# 실측으로 도입했으나 dev·val 교차 스캔에서 정답이 드러냄표를 치는 케이스가 139건(안 침 36건)
# — 정답 도서 혼용 중 다수는 침이고 규정 제56항도 침. 다수·규정 방향으로 롤백.
# PDF 박스 구획선이 텍스트로 흘러든 세로선 잔재. 정답 도서는 세로선 셀을 전혀 안 쓴다
# (제71항 _\·_| 모두 1131p 0회). 형태에 따라 정답 관행이 갈려 둘로 나눈다.
#   ① 줄 전체가 라벨 하나뿐인 박스 표제 "|정답|" → 붙임표 감쌈 ⠤정답⠤
#      (정답 실측 ⠤정답⠤ 131회·⠤보기⠤ 15회. (가)→⠤가⠤와 같은 도서 관행이다.)
#   ② 그 밖의 세로선(칸 구분자 "| 출제 의도 | 곡선…", 러닝헤더 "EBS … | VIII.")
#      → 공백. 정답은 ⠰⠯⠨⠝⠀⠺⠊⠥(출제 의도)를 앞뒤 빈칸으로만 두른다(실측 24회).
_LABEL_BOX_RE = re.compile(r"(?m)^[ \t]*\|[ \t]*([^|\n]{1,14}?)[ \t]*\|[ \t]*$")
_BAR_RESIDUE_RE = re.compile(r"[ \t]*\|[ \t]*")
# 어절 경계에 홀로 선 자모 + 마침표 (항목 머리표 "ㄱ." "ㄴ.")
_JAMO_MARK_RE = re.compile(r"(?<![가-힣A-Za-z0-9])([ㄱ-ㅎ])\.(?=\s|$)")
# 문항 번호: 요소 첫머리 숫자 뒤에 본문이 이어질 때만 마침표를 붙인다("3\n다음은…" → "3.").
# 뒤에 아무것도 없는 숫자(페이지 번호 "16")는 그대로 둔다 — 정답도 마침표를 안 찍는다.
# 정확도 실측(2026-07-27 독립 검증, 발동 요소 dev 91·val 445를 gold 줄머리와 전수 대조):
#   gold도 마침표를 찍는 자리 dev 87.9% · val 88.8%, 명백한 오발동 2.2%/2.5%.
#   ⚠ 과목별로 갈린다 — 언어 98.1%·수학2 95.5%·세계사 92.7%·사회문화 86.8%인데
#   **외국어 45.5%·생물 20%**. 그래서 주지표 기준으로 언어(dev +14·val +97셀)와
#   생물(val +69셀)은 오히려 악화했다(전체는 dev −114·val −492로 net-positive).
#   오발동 계열 4종: 페이지번호+러닝헤더('64\nEBS 수능특강 외국어영역') · 강 헤더('19\n강') ·
#   보기 라벨 · 축 눈금. 전부 **요소 타입**으로 구분되므로 header_footer·page_number 제외 +
#   본문이 숫자 나열뿐이면 제외하는 타입 가드로 구조적으로 막을 수 있다(리터럴이 아니라
#   과적합 아님). 별도 라운드에서 단독 A/B로 검증할 것 — 후속 후보.
_QNUM_RE = re.compile(r"^(\d{1,2})(?=\s+\S)")
# 음수·뺄셈표(「한국 점자 규정」 제45항 연산·비교 기호 — 2026-07-27 원문 대조로 '수학 제45항'
# 표기를 정정. 수학편 제45항은 함수다): 부호 = 뺄셈표 ⠔. symbol_table의 붙임표 -=⠤가
# 음수 부호까지 삼켜 ①-4가 ⠤⠼⠙(붙임표)로 나가던 것을 바로잡는다(gold ⠔⠼⠙, 수학2 p119).
# 앞머리 부호만 잡는다 — 앞이 숫자·문자·한글·소수점·쉼표가 아닌 - + 숫자. 숫자 사이
# -(2-3·02-123·날짜·계좌)와 물결표 범위(~→―→⠤⠤)는 붙임표/범위 관행이라 건드리지 않는다.
# braillify에 ⠔(점자 셀)를 넘기면 _emit_mixed가 뒤 숫자에 수표 ⠼를 정상 부여한다.
# ★ 뒤에 닫는 -가 오는 -N- 은 제외한다. translate_with_breaks가 요소 단위로 (N)→-N-
# 붙임표 감쌈을 먼저 걸어 두기 때문에, 그걸 음수로 오인하면 감쌈 관행이 통째로 깨진다
# (실측: 오인 시 valall 텍스트 66.4→64.9p).
_NEG_NUM_RE = re.compile(r"(?<![0-9A-Za-z가-힣.,])-(?=\d+(?![\d-]))")
# 줄머리 하이픈 글머리("- 내용") — 관행: ⠤⠤ 붙임(위 _apply_book_style 참조)
_HYPHEN_BULLET_RE = re.compile(r"(?m)^[ \t]*-[ \t]+")
# 어휘 뒤 각주 참조 *: 정답은 번호 붙임표 -1-(⠤⠼⠁⠤)로 적는다(세계사 p019·021·040 실측,
# dev·val 교차 71건). 줄머리 * (글머리·각주 설명부)는 보존. 요소 내 등장 순으로 번호.
_FOOTNOTE_STAR_RE = re.compile(r"(?<=[가-힣])\*")
# 줄머리 불릿(•▪·◦)은 지우지 않는다 — layout._apply_bullet_marker가 ○□△와 같은 방식으로
# 정답 도서의 글머리표 ⠔⠔로 정정한다(아래 근거). 여기서 지우면 그 기회가 사라진다.
#   규정 제72항은 •를 ⠸⠲(_4)로 지정하지만 정답 코퍼스 1131p에 _4는 0회,
#   ⠔⠔(99)가 2,642회(줄머리 454 / 중간 20). 원문 '•' 시작 줄 ↔ 정답 대조 10/11 일치.
#   (2026-07-16 이전엔 "정답은 글머리를 안 찍는다"고 보고 지웠으나 전수 확인 결과 오판)


# ── 보기 마커 원문 복원 (근거 tier ②: OCR가 망친 ㄱㄴㄷㄹ 자모 회복) ─────────
# 보기 상자의 항목 라벨 ㄱ. ㄴ. ㄷ. ㄹ. 은 OCR이 시각 유사 글자로 자주 오독한다:
#   ㄱ→'7', ㄴ→'L'/'l', ㄷ→'c'/'C', ㄹ→'己'. 규정은 ㄱㄴㄷㄹ을 =a·=3·=9·=1로 점역하나
# 오독 입력('7.'·'L.'…)은 엉뚱한 점형이 된다. 정답은 자모형이므로 원문 복원이 맞다.
# ★ 과적합·오탐 가드 2중: (1) 한 요소에 라벨 줄이 2개 이상이고 (2) 매핑 결과가
#   ㄱㄴㄷㄹㅁ 순서로 단조 증가하는 '보기 나열'이며 (3) 최소 하나가 명백한 오독 문자일 때만
#   발동. 진짜 '7.'·'c.' 단독 항목은 건드리지 않는다.
_BOGI_MARK_MAP = {"7": "ㄱ", "L": "ㄴ", "l": "ㄴ", "c": "ㄷ", "C": "ㄷ", "己": "ㄹ",
                  "근": "ㄹ", "리": "ㄹ",   # ㄹ의 추가 오독(PDF 대조 실측, dev18)
                  "ㄱ": "ㄱ", "ㄴ": "ㄴ", "ㄷ": "ㄷ", "ㄹ": "ㄹ", "ㅁ": "ㅁ"}
_BOGI_MISREAD = "7LlcC己근리"
_BOGI_ORDER = "ㄱㄴㄷㄹㅁ"
# 후행: 공백 또는 보기 내용 시작(원문자·괄호·한글). 숫자 제외 → '7.5' 소수점 오탐 방지.
_BOGI_MARK_LINE = re.compile(
    r"(?m)^([ \t]*)([7LlcC己근리ㄱㄴㄷㄹㅁ])([.．·])(?=[ \t　(（①-⑳㉠-㉿가-힣])")


# 원문자 자모 참조 복원: ㉠㉡㉢ 을 OCR이 원문자 숫자 ⑦⑧⑨로 오독한다(원 안 글자 혼동).
# 선택지는 ①~⑤라 ⑦⑧⑨는 선택지가 아니고, 뒤에 조사(은/는/이/가/을/를/의/에)가 붙으면
# 지시 참조 자모(㉠…)가 거의 확실하다. gold 대조로 ⑦→㉠ 확인(사회문화 p140 =az).
_CIRCLED_JAMO_MISREAD = {"⑦": "㉠", "⑧": "㉡", "⑨": "㉢", "⑩": "㉣"}
_CIRCLED_JAMO_RE = re.compile(r"([⑦⑧⑨⑩])(?=[은는이가을를의에도만])")


def _restore_circled_jamo(text: str) -> str:
    return _CIRCLED_JAMO_RE.sub(lambda m: _CIRCLED_JAMO_MISREAD[m.group(1)], text)


def _normalize_bogi_markers(text: str) -> str:
    text = _restore_circled_jamo(text)
    ms = list(_BOGI_MARK_LINE.finditer(text))
    if len(ms) < 2:
        return text
    mapped = [_BOGI_MARK_MAP.get(m.group(2), "") for m in ms]
    idxs = [_BOGI_ORDER.find(x) for x in mapped]
    if any(i < 0 for i in idxs):
        return text
    if not any(m.group(2) in _BOGI_MISREAD for m in ms):
        return text  # 이미 전부 올바른 자모면 손대지 않음
    if not all(idxs[i] < idxs[i + 1] for i in range(len(idxs) - 1)):
        return text  # 단조 증가(보기 나열)가 아니면 보수적으로 스킵
    return _BOGI_MARK_LINE.sub(
        lambda m: m.group(1) + _BOGI_MARK_MAP[m.group(2)] + m.group(3), text)


def _apply_book_style(text: str) -> str:
    """도서 관행 표기로 원문을 다듬는다(점역 경로 전용 — text_list 원문은 그대로 둔다)."""
    if not _BOOK_STYLE:
        return text
    text = _normalize_bogi_markers(text)   # 원문 복원은 다른 치환보다 먼저(줄머리 기준)
    text = _LABEL_BOX_RE.sub(r"-\1-", text)      # 박스 표제 |정답| → ⠤정답⠤ (표제 판정이 먼저)
    text = _BAR_RESIDUE_RE.sub(" ", text)        # 남은 구획선 잔재 → 공백
    text = _AE_GEQ_RE.sub("≥", text)   # 괄호→붙임표보다 먼저(인접 판정이 원문 괄호 기준)
    text = _SRC_BRACKET_RE.sub(_src_bracket_repl, text)  # 출처 대괄호→소괄호 셀(가드)
    text = _QNUM_RE.sub(r"\1.", text)
    text = _CIRCLED_RE.sub(lambda m: _CIRCLED[m.group()], text)
    text = _MARK_PAREN_RE.sub(_paren_repl, text)
    # 이 단계는 이미 음수 판정(_NEG_NUM_RE) 뒤라 자리표시자를 유지할 이유가 없다 —
    # 여기서 만들어진 감쌈만 되돌린다(밖에서 온 것은 앞서 복원돼 no-op).
    text = _restore_wrap_hyphen(text)
    text = _ANGLE_RE.sub(r"‘\1’", text)
    text = _BOGI_LINE_RE.sub(r"\1", text)
    text = _BOGI_GAP_RE.sub(r"\1 ‘보기’\2", text)
    text = _NOISE_BACKTICK_RE.sub("", text)
    text = _AMP_RE.sub("⠯", text)
    text = _BOX_BLANK_RE.sub(_box_blank_repl, text)
    text = _TILDE_RE.sub("―", text)
    # 줄머리 하이픈 글머리: 정답은 ⠤⠤ + 공백 없이 내용을 붙인다(사회문화 p030 실측 '--.ul').
    # 줄표 ―로 바꾸면 braillify가 ⠤⠤로 점역한다. BBPG의 ⠤ 1셀·뒤 1칸과 다른 도서 관행.
    text = _HYPHEN_BULLET_RE.sub("―", text)
    _fn = [0]
    def _star_num(m):
        _fn[0] += 1
        return f"-{_fn[0]}-"
    text = _FOOTNOTE_STAR_RE.sub(_star_num, text)
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


# ── 국어 문장 안 인라인 첨자 토큰 (r22, 2026-07-26) ──────────────────────────
# O₂·t₁·PCO₂처럼 **글자와 아래첨자만으로 된 토큰**은 수식이라기보다 국어 문장 안의 로마자
# 표기다. gold도 그렇게 적는다 — 우리 수식 경로가 붙이던 제11항 두 칸과 대문자 구절표는
# 정답 도서에 없고, 대신 로마자표 ⠴가 붙는다.
#   규정: 「한글 점자」 제29항(국어 문장 안 로마자 = 로마자표) · 수학 제12항 3호
#         "국어 문장 안의 로마자는 제29항에 따르되 **대문자 구절표를 사용하지 않는다**".
#         제11항 두 칸은 '수식'에 붙는 규정인데, gold는 단독 첨자 토큰을 수식으로 조판하지
#         않는다(아래 실측). 제12항 1호의 '로마자표 생략'은 진짜 수식 안에만 적용된다.
#   gold 실측(dev+val, gold에서 형태가 확정된 매치 145건 — temp/r22_measure_gold.py):
#         로마자표 있음 106 · 없음 39   겹 대문자표 ⠠⠠ **0**
#         앞 공백 0칸 36 · 1칸 88 · 2칸 5   뒤 공백 0칸 101 · 1칸 37 · 2칸 2
#         → 두 칸(제11항)은 사실상 0. 대표형 CO₂=`0,CO2`(⠴⠠⠉⠕⠆) · t₁=`0T1`(⠴⠞⠂).
#   ⚠ 측정 스크립트 한계(독립 검증 2026-07-26): expected_core가 대문자마다 대문자표를 붙여
#     `,C,O2`를 찾는 탓에 gold 표기 `0,CO2`(CO₂)가 25p에서 매치를 놓친다. 위 145건은 그
#     한계를 안은 하한이고, 결론(로마자표 우세·겹 대문자표 0·두 칸 0)은 독립 gold 스캔으로
#     따로 확인됐다. 이 주석의 N을 다른 판단의 근거로 재사용하기 전에 스크립트부터 고칠 것.
#   범위: 연산자·등호가 하나라도 있으면 진짜 수식이라 제외(S₁+S₂=10은 종전대로 제11항).
#         한글이 없는 요소(순수 수식·표 셀)도 제외 — '국어 문장 안'이 규정 전제다.
_INLINE_SUB_TOKEN_RE = re.compile(r"^(?:[A-Za-z]+_\{?\d+\}?)+[A-Za-z]*$")
# 괄호로 묶인 첨자 토큰 '산소(O₂)와' — gold는 수학 괄호 ⠦…⠴가 아니라 **붙임표 ⠤…⠤**로
# 감싼다(생물 p087 `L3,U-O2-V`=산소-O₂-와 · p030 `-0,NAHCO3-`, dev+val 붙임표 25건 대
# 수학괄호 0건). (가)→⠤가⠤와 같은 도서 관행(D-01)이다.
# ⚠ 실제로 도달하는 형태는 `-O₂-`다: translate_with_breaks가 _paren_repl로 (X)→-X-를
#   먼저 적용하고, 그 붙임표까지 inline_math가 수식 구간에 삼켜 convert_latex이 **뺄셈
#   ⠔**로 내보내고 있었다(생물 p087 실측 `⠔⠠⠕⠆⠔`, gold `⠤⠕⠆⠤`). 두 형태 모두 받는다.
_INLINE_SUB_PAREN_RE = re.compile(r"^\((?:[A-Za-z]+_\{?\d+\}?)+[A-Za-z]*\)$")
_INLINE_SUB_HYPHEN_RE = re.compile(r"^-(?:[A-Za-z]+_\{?\d+\}?)+[A-Za-z]*-$")
_BOOK_HYPHEN = "⠤"


def _has_hangul_outside_math(parts: list[str]) -> bool:
    """수식 밖 본문에 한글이 있는가 — 태그명(<!수식>)은 제외하고 본다."""
    return any(_HANGUL_SYL_RE.search(_RESIDUAL_BANG_TAG_RE.sub("", parts[i]))
               for i in range(0, len(parts), 2))


def _inline_sub_braille(b: str) -> str:
    """인라인 첨자 토큰 점형: 로마자표 ⠴ 접두 + 대문자 구절표 ⠠⠠ → 홑 대문자표 ⠠."""
    return _ROMAN_START + b.replace(_CAPITAL_IND * 2, _CAPITAL_IND)


def _translate_with_braillify(text: str) -> str:
    parts = _FORMULA_RE.split(text)
    # (종류, 점자, 앞 원문공백, 뒤 원문공백). 종류: "t"=텍스트 "f"=수식 "i"=인라인 첨자 토큰
    chunks: list[tuple[str, str, bool, bool]] = []
    # 국어 문장 안일 때만 인라인 첨자 관행 적용(제12항 2·3호 전제)
    inline_sub = _has_hangul_outside_math(parts)

    for i, part in enumerate(parts):
        if i % 2 == 0:  # 일반 텍스트 세그먼트
            lead_ws = bool(part[:1].strip() == "" and part[:1])
            trail_ws = bool(part[-1:].strip() == "" and part[-1:])
            clean = substitute_tags(part)
            if i > 0:                # 수식 직후: 앞 공백 제거
                clean = clean.lstrip()
            if i < len(parts) - 1:  # 수식 직전: 뒤 공백 제거
                clean = clean.rstrip()
            if clean:
                # 음수 부호(제45항 연산·비교 기호)를 뺄셈표 셀 ⠔로 미리 고정 — symbol_table의 붙임표
                # -=⠤가 삼키기 전에. ★ book_style의 (N)→붙임표 -N- 감쌈보다 먼저 원문에
                # 적용해야 감쌈용 붙임표를 음수로 오인하지 않는다(-1- 감쌈 281회 보호).
                clean = _NEG_NUM_RE.sub("⠔", clean)
                # 음수 판정이 끝났으니 감쌈 자리표시자를 원래 붙임표로 되돌린다
                # (뒤의 _apply_book_style·substitute_symbols의 -=⠤ 매핑을 그대로 태운다).
                clean = _restore_wrap_hyphen(clean)
                preprocessed = _preprocess_units(_apply_book_style(clean))
                substituted = substitute_symbols(preprocessed)
                text_result: list[str] = []
                _emit_mixed(substituted, text_result)
                chunks.append(("t", _collapse_spaces("".join(text_result)),
                               lead_ws, trail_ws))
            else:
                # 빈 텍스트(공백뿐)라도 띄어쓰기 정보는 다음 구분에 넘긴다
                chunks.append(("t", "", lead_ws, trail_ws))
        else:  # 수식 세그먼트
            # 수식 구간은 _NEG_NUM_RE를 타지 않으므로 여기서 바로 되돌린다
            # (_INLINE_SUB_HYPHEN_RE가 '-O₂-' 형을 그대로 받도록).
            part = _restore_wrap_hyphen(part)
            core = part.strip()
            if inline_sub and _INLINE_SUB_TOKEN_RE.match(core):
                chunks.append(("i", _inline_sub_braille(convert_latex(core)),
                               False, False))
            elif inline_sub and (_INLINE_SUB_PAREN_RE.match(core)
                                 or _INLINE_SUB_HYPHEN_RE.match(core)):
                inner = _inline_sub_braille(convert_latex(core[1:-1]))
                chunks.append(("i", _BOOK_HYPHEN + inner + _BOOK_HYPHEN,
                               False, False))
            else:
                chunks.append(("f", convert_latex(part), False, False))

    # 수학 점자 규정 제11항: 수식 앞뒤 두 칸 공백(⠀⠀).
    # 단 인라인 첨자 토큰(O₂·t₁)은 gold가 두 칸을 쓰지 않으므로 원문 띄어쓰기를 그대로 둔다.
    result_parts: list[str] = []
    prev_kind: str | None = None
    pending_ws = False
    for kind, braille, lead_ws, trail_ws in chunks:
        if not braille:
            pending_ws = pending_ws or lead_ws or trail_ws
            continue
        if prev_kind is not None:
            if kind == "i" or prev_kind == "i":
                if pending_ws or lead_ws:
                    result_parts.append("⠀")
            else:
                result_parts.append("⠀⠀")
        result_parts.append(braille)
        prev_kind = kind
        pending_ws = trail_ws

    braille = "".join(result_parts)
    braille = _fix_leading_roman(text, braille)
    return braille


def _translate_fallback(text: str) -> str:
    # braillify 미설치 시: 수식→convert_latex, 기호→substitute_symbols, 나머지→폴백
    def _formula_sub(m: re.Match) -> str:
        return convert_latex(m.group(1))

    result = _FORMULA_RE.sub(_formula_sub, text)
    result = _restore_wrap_hyphen(result)   # 폴백 경로엔 음수 판정이 없다 — 즉시 복원
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

# ── 한컴 레거시 심볼 폰트 오디코딩 복원 ──────────────────────────────────────
# 교과서 PDF의 심볼 폰트는 글리프를 엉뚱한 코드포인트로 인코딩한다. 매핑이 없어
# braillify·symbol_table 어느 쪽도 못 받고 **예외도 플래그도 없이 사라진다** —
# 원문 글자가 조용히 없어지는 유일한 경로라 cosmetic이 아니다(Ca²⁺→Ca⁺, 40°C→40C).
# PUA 수식 글리프(_sanitize_repl)와 같은 계열, 다른 코드 영역.
# 정체는 코퍼스 원문 문맥으로 개별 확인했다:
#   ⇂  빈칸 네모 □ — "과정을 ⇂⇂라고 한다"(소화)·"혈액형은 ⇂⇂ 형"(AB).
#      정답 도서도 네모 수만큼 ⠸⠭ⁿ⠇로 적는다(생물 p049 gold 7군 전수 일치).
#   ¤  위첨자 2 — "a¤ -ab+b¤"(a²-ab+b²)·"x¤ +1>0". 수학2에 집중.
#   ‹  위첨자 3 — "a‹ +b‹ =(a+b)(a¤ -ab+b¤ )"(a³+b³ 인수분해 공식).
#   ˘  도 ° — "37˘C"·"45˘"·"0˘<A<90˘".
#   ⇨  함의 화살표 ⇒ — "y=cosx ⇨y'=-sinx"(전량 수학2 도함수 공식).
#   ›  위첨자 4 — "x› -8x¤ -9=0"(x⁴-8x²-9)·"e›"·"(3x+1)›"·생물 p008 "⁄`›`CO™"(¹⁴CO₂).
#      ‹(³)와 같은 폰트 슬롯 연쇄(Mac Roman 0xDC·0xDD)라 ‹=³의 검증이 그대로 이어진다.
#      dev+val 37건 중 35건이 수학2·생물의 진짜 4제곱/질량수, 나머지 2건(세계사 p091
#      깨진 폰트 런, 언어 p093 '고종(孤›)' 미인코딩 한자)은 이미 복구 불가한 쓰레기다.
#      복원 전에는 ›가 **예외도 플래그도 없이 사라져** x⁴가 x로 나갔다(r22 실측).
# ※ ⁄는 위첨자 ¹이 **아니다** — dev+val 523건 중 496건이 수학2 `lim x ⁄0`의 화살표 →이고
#   생물 `녹말1111⁄ 엿당`도 화살표다(1=화살대). r16이 '원문자 ① 480회'로 적은 기각 사유는
#   오진이었고, 정정된 실측으로도 결론은 같다 — ⁄→¹ 치환은 화살표 496건을 오염시켜 기각.
#   백틱·▶◀도 정체 확증이 부족해 제외.
_LEGACY_GLYPH_MAP = {
    "⇂": "□", "¤": "²", "‹": "³", "›": "⁴", "˘": "°", "⇨": "⇒",
}
_LEGACY_GLYPH_RE = re.compile("[" + "".join(_LEGACY_GLYPH_MAP) + "]")
_SPECIAL_MAP.update(_LEGACY_GLYPH_MAP)   # sanitize 경로(다른 호출자)에도 같은 표를 건다


def _restore_legacy_glyphs(s: str) -> str:
    """오디코딩 글리프를 원래 문자로. 수식 라우팅 전에 돌려야 제곱이 ⠣로 나간다."""
    return _LEGACY_GLYPH_RE.sub(lambda m: _LEGACY_GLYPH_MAP[m.group()], s)


# ── 깨진 아래첨자 글리프 복원 (r16, 2026-07-22) ──────────────────────────────
# 생물·수학2 교재 PDF의 커스텀 폰트가 아래첨자(₁₂₃₄₆)를 비-PUA 코드포인트로 매핑해
# 깨뜨린다: ¡=₁ ™=₂ £=₃ ¢=₄ §=₆. PUA가 아니라 PUA 감지·MinerU 재라우팅이 못 잡고,
# symbol_table이 ™→상표(⠘⠞)·£→파운드·¢→센트·§→구역기호로 조용히 오역한다(r15 실측).
# 원소기호·변수 직후로만 한정해 유니코드 아래첨자로 되돌리면 inline_math가 이를 ₀-₉로
# 인식해 수식 경로(kor_math_rules._stage9_subscript, book 모드 내림 숫자)로 흘려보낸다 —
# 그 규칙은 이미 gold형(내림 숫자, 수표·첨자표 없음)이라 규칙은 손대지 않는다.
#   근거: gold 전수 실측(r15) — CO₂=⠴⠠⠉⠕⠆(내림 2), 규정형 ⠰⠼는 gold 0회.
#         내림 숫자형은 화학식뿐 아니라 생물 시점변수 t₁·t₂·t₃, 수학 S₁·x₂도 동일(gold 실측
#         생물 p062 t_1·t_2 / 수학2 p054 ^s_1 ^s_2 ^s_3 — 전 가족 내림 숫자).
#   가드: 라틴 글자 + 아래첨자 글리프 런. 단 **소문자 변수는 앞이 또 라틴 글자면 제외**해
#         'Windows™'류 상표(뒤 s가 단어 일부)를 보호한다. 대문자 앞(원소기호 O·H·변수 S)은
#         항상 치환(코퍼스에 상표·파운드가 라틴 글자 뒤에 붙는 정상 용례는 0건, r16 grep 확인).
#         £100(파운드)은 £가 숫자 앞이라 글자-뒤 가드에 안 걸린다. ™(상표) 매핑은 유지(정상 용례용).
_BROKEN_SUBSCRIPT_MAP = {"¡": "₁", "™": "₂", "£": "₃", "¢": "₄", "§": "₆"}
_BROKEN_SUBSCRIPT_RE = re.compile(r"([A-Za-z])([¡™£¢§]+)")


def _restore_broken_subscripts(s: str) -> str:
    """깨진 아래첨자 글리프를 유니코드 아래첨자로. 수식 라우팅(inline_math)보다 먼저."""
    def _rep(m: re.Match) -> str:
        letter, run = m.group(1), m.group(2)
        # 소문자 변수가 단어 일부(앞이 라틴 글자)면 상표 ™ 등일 수 있어 건드리지 않는다.
        prev = s[m.start(1) - 1] if m.start(1) > 0 else ""
        if letter.islower() and prev.isascii() and prev.isalpha():
            return m.group(0)
        return letter + "".join(_BROKEN_SUBSCRIPT_MAP[g] for g in run)

    return _BROKEN_SUBSCRIPT_RE.sub(_rep, s)


def _normalize_special(s: str) -> str:
    out = []
    for ch in s:
        o = ord(ch)
        if 0xFF01 <= o <= 0xFF5E:        # 전각 ASCII → 반각(，．？！（）；～ 등)
            out.append(chr(o - 0xFEE0))
        else:
            out.append(_SPECIAL_MAP.get(ch, ch))
    return "".join(out)


def _sanitize_repl(m: re.Match) -> str:
    """hostile 런을 문자별로: braillify가 처리 가능하면 보존(옛한글 PUA 등),
    못 하는 것(수식 글리프·제어문자)만 공백. 규정 08절 옛한글 PUA 소실 버그 수정(2026-07-18)."""
    out = []
    for ch in m.group():
        # PUA(옛한글 자모 등)만 braillify 가능 여부로 보존 판정. 나머지(제어문자·hyphen 등)는
        # 기존대로 공백 — hyphen 처리 등 다른 동작을 건드리지 않는다(roundtrip 회귀 방지).
        is_pua = 0xE000 <= ord(ch) <= 0xF8FF or 0xF0000 <= ord(ch) <= 0x10FFFD
        if is_pua:
            try:
                _braillify_lib.translate_to_unicode(ch)
                out.append(ch)      # braillify 처리 가능 PUA → 보존
                continue
            except Exception:       # noqa: BLE001
                pass
        out.append(" ")            # 제어문자·미처리 PUA·hyphen 등 → 공백
    return "".join(out)


def sanitize_for_braille(text: str) -> str:
    """braillify가 거부하는 문자를 안전화(요소 격리·빈 결과 금지).

    1) 제어문자·braillify 미처리 PUA(수식 글리프) → 단일 공백.
       단, braillify가 처리 가능한 PUA(옛한글 자모 등)는 보존한다.
    2) 전각 문장부호·반각괄호·불릿 → 받아들이는 등가물(품질 보존).
    주변 한글·영문·숫자는 보존하고, 이중 공백은 이후 _collapse_spaces가 정리한다.
    """
    text = _BRAILLIFY_HOSTILE_RE.sub(_sanitize_repl, text)
    return _normalize_special(text)


_ENG_RUN_RE = re.compile(r"[A-Za-z][A-Za-z'\- ]*[A-Za-z]|[A-Za-z]")

# 제32항 — 로마자표와 종료표 사이는 통일영어점자를 따른다. 즉 라틴 런 사이에 공백·숫자·
# 영어 문장부호만 끼면 그 전체가 **하나의 로마자 구간**이고 로마자표·종료표는 각각 한 번뿐이다.
# 규정 실측: `KBS 1 TV 좀…` → ⠴⠠⠠KBS ⠼⠁ ⠠⠠TV⠲ (규정_텍스트.txt:1748).
_SPAN_BRIDGE_RE = re.compile(r"[0-9,.:;'‐-―\- ]+")

# 제32항 — 구간 내부 문장부호는 통일영어점자 점형. 한글 점자와 점형이 다른 것만 적는다
# (`.`·`-`는 두 규정이 같은 셀이라 목록에 없어도 결과가 같다).
_UEB_PUNCT = {",": "⠂", ";": "⠆", ":": "⠒", "'": "⠄"}

# 제33항 — 로마자와 한글 사이에 오는 이 부호들은 종료표를 적지 않고 한글 점자로 적는다.
_ART33_PUNCT = ",:;–—―"

def _english_spans(seg: str, runs: list[tuple[int, int]]) -> list[list[tuple[int, int]]]:
    """라틴 런 목록 → 로마자 구간(제32항) 목록. 구간 = 브리지 가능한 간극으로 이어진 런들.

    (A/B 단계 분해에 쓰던 env 토글 BR_ENG_SPAN_MERGE·BR_ENG_NO_TERM_NUM·BR_ENG_ART33은
     병합 시 제거했다 — 프로덕션 점역 출력이 환경변수에 좌우되면 안 된다. 세 단계 모두
     규정이 정본이고 A/B로 확인된 값이라 상시 적용한다. 단계별 기여는 temp/x1_experiment.md.)
    """
    spans: list[list[tuple[int, int]]] = [[runs[0]]]
    for r in runs[1:]:
        gap = seg[spans[-1][-1][1]:r[0]]
        if _SPAN_BRIDGE_RE.fullmatch(gap):
            spans[-1].append(r)
        else:
            spans.append([r])
    return spans


def _span_gap(gap: str) -> str:
    """구간 **내부** 간극(라틴 런 사이) 점역. 앞선 런에 바로 붙은 문장부호만 통일영어점자로.

    공백을 건너뛰어 붙지 않은 부호(예: 수 안의 `1,000`)까지 바꾸면 근거를 벗어나므로,
    규정 예시(`a,` `apples,` `1998a,`)와 같은 '런에 붙은' 자리로 한정한다.
    """
    i = 0
    out: list[str] = []
    while i < len(gap) and gap[i] in _UEB_PUNCT:
        out.append(_UEB_PUNCT[gap[i]])
        i += 1
    if i < len(gap):
        out.append(_braillify_korean(gap[i:]))
    return "".join(out)


def _eng_terminator(seg: str, end: int) -> str:
    """구간 뒤에 로마자 종료표를 적을지 판정(제33·35항)."""
    rest = seg[end:]
    if not rest.strip():
        return "⠲"
    # 제35항 — 로마자와 숫자가 이어 나올 때에는 종료표를 적지 않는다.
    j = 0
    while j < len(rest) and rest[j] == " ":
        j += 1
    if j < len(rest) and rest[j].isdigit():
        return ""
    if rest[0] in _ART33_PUNCT:
        # 제33항 — 점형이 다른 부호(, : ; ―)가 로마자와 한글 사이면 종료표를 적지 않는다.
        k = 1
        while k < len(rest) and rest[k] == " ":
            k += 1
        if k < len(rest) and _is_hangul(rest[k]):
            return ""
    return "⠲"


def _split_english(seg: str) -> str | None:
    r"""세그먼트 안의 영어 구간을 eng_braille(Grade 2)로, 나머지는 braillify로 점역.

    규정 [부록 1] 제1항이 외국어를 해당 국가 규정에 위임하므로 영어 약자는 영어 점자
    표준을 따라야 하는데, braillify는 letter-group 약자만 구현한다(the→⠹⠑, 정답 ⠮).
    그래서 영어 구간만 이 경로로 분리한다 — 코퍼스 A/B에서 영어 구절 완전일치가
    7/561 → 168/481, 최장일치 40.3% → 75.4%로 올랐다(2026-07-19).

    로마자표는 규정 제2항(⠴ … 종료표 ⠲)·제4항(전체가 외국어면 생략)을 따른다 —
    세그먼트에 한글이 섞였을 때만 붙인다(braillify의 기존 판정과 같다).

    ★ 2026-07-27: 단위를 낱말 → **구간(span)** 으로 교체. 종전에는 라틴 런마다 ⠴…⠲를
    감싸 `MP4 Player`가 ⠴MP⠲⠼⠙ ⠴Player⠲로 나갔는데, 제32항은 로마자표·종료표 사이를
    통일영어점자로 적으라 하므로 사이에 낀 공백·숫자·영어 문장부호는 구간 **내부**다.
    제35항(숫자가 이어지면 종료표 없음)·제33항(로마자와 한글 사이 `, : ; ―`는 종료표
    없이 한글 점자)도 함께 반영한다. 규정 예시 12건 대조 = temp/x1_replay.py.

    ※ 라틴 런 + 공백 + 한글(제29항 자리)의 종료표는 이 변경의 범위가 아니다 — 그대로 둔다.

    영어가 없으면 None을 돌려 호출부가 종전 braillify 경로를 그대로 쓰게 한다.
    """
    runs = [m.span() for m in _ENG_RUN_RE.finditer(seg)]
    if not runs:
        return None
    has_hangul = any(_is_hangul(c) for c in seg)
    out: list[str] = []
    last = 0
    for span in _english_spans(seg, runs):
        start, end = span[0][0], span[-1][1]
        if start > last:
            out.append(_braillify_korean(seg[last:start]))
        body: list[str] = []
        pos = start
        for s, e in span:
            if s > pos:
                body.append(_span_gap(seg[pos:s]))
            # 낱말 사이 공백은 점자 빈칸으로 — 한글 구간(braillify) 출력과 통일한다.
            body.append(eng_braille.translate(seg[s:e]).replace(" ", "⠀"))
            pos = e
        core = "".join(body)
        out.append(f"⠴{core}{_eng_terminator(seg, end)}" if has_hangul else core)
        last = end
    if seg[last:]:
        out.append(_braillify_korean(seg[last:]))
    return "".join(out)


def _braillify_korean(seg: str) -> str:
    """영어를 뺀 구간(한글·숫자·기호) → braillify. 영어 분리 경로가 재사용한다."""
    return _safe_to_unicode(seg, _split_eng=False)


def _safe_to_unicode(seg: str, _split_eng: bool = True) -> str:
    """braillify 변환 + 최후 폴백. 정규화 후에도 남은 미지 글자가 줄 전체를 깨지 않도록,
    세그먼트가 실패하면 글자 단위로 변환하고 변환 불가 글자만 공백으로 대체한다.

    ★ braillify는 세그먼트 가장자리 공백을 삼킨다(' 질문은'=='질문은' 실측 2026-07-17).
      점자런과 텍스트런 경계의 공백(예: 선지 번호 ⠼⠁ 뒤 한 칸)이 사라져 정답과 어긋나므로
      가장자리 공백을 점자 빈칸으로 보존한다.
    """
    if _split_eng and _BRAILLIFY_AVAILABLE:
        split = _split_english(seg)
        if split is not None:
            return split
    core = seg.strip(" ")
    lead = "⠀" * (len(seg) - len(seg.lstrip(" ")))
    trail = "⠀" * (len(seg) - len(seg.rstrip(" ")))
    if not core:
        return lead
    seg = core
    try:
        return lead + _braillify_lib.translate_to_unicode(seg) + trail
    except Exception:  # noqa: BLE001 — 미지 글자 격리(줄 보존)
        # ★ 글자 단위 폴백은 약자·어절 공백을 깨뜨린다(䤎 하나로 '하였'의 ⠣ 소실,
        #   세계사 p019·021 실측 — 교차 31건). 먼저 변환 불가 글자만 제거하고 세그먼트를
        #   통짜로 재시도해 약자를 보존한다. 그래도 실패하면 글자 단위 최후 폴백.
        bad = set()
        for ch in set(seg):
            try:
                _braillify_lib.translate_to_unicode(ch)
            except Exception:  # noqa: BLE001
                bad.add(ch)
        if bad:
            cleaned = "".join(ch for ch in seg if ch not in bad)
            try:
                return lead + _braillify_lib.translate_to_unicode(cleaned) + trail
            except Exception:  # noqa: BLE001
                pass
        out = []
        for ch in seg:
            try:
                out.append(_braillify_lib.translate_to_unicode(ch))
            except Exception:  # noqa: BLE001
                out.append(" ")
        return lead + "".join(out) + trail


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


# 줄머리 선지 번호(①-⑳) 뒤 공백 1 보장. 정답 도서는 원문에 공백이 없어도 넣는다
# (사회문화 p101 '①2000년' → #1 #bjjj — listitem_diff.md 실측, ①선지 실패 56건의 주범).
# 문중 참조("㉠과")는 붙어야 하므로 줄머리만 잡는다.
_CHOICE_HEAD_RE = re.compile(r"(?m)^([①-⑳])\s*")

# ── 레거시 폰트 오디코딩 복원 (w1, 2026-07-21) ──────────────────────────────
# 교재 PDF의 사설 인코딩 폰트(딩뱃)가 매핑 없는 코드포인트로 추출돼 braillify가 요소
# 전체를 거부(→약자 없는 폴백)하는 것을 원래 글자로 복원한다. 원본 PDF 크롭으로 자형을,
# gold BRF로 점형을 확인하고 전 코퍼스 독립 A/B로 검증했다.
#   · 검은 원문자 ❶–❻(U+2776–U+277B)는 흰 원문자 ①–⑥과 동형으로 점역(생물 p019
#     정답목록 ❶미량… → gold ⠼⠂·⠼⠆… 확정, 자형은 생물 p019 크롭으로 흑원 숫자 확인).
#     braillify가 ①–⑥→⠼⠂…를 정확히 처리하므로 ①–⑥으로 정규화해 맡긴다. 단 인용 콜아웃
#     '❶[2013 수능]…'(언어)은 gold가 번호를 붙이지 않으므로 '[' 직전의 흑원 문자는 삭제한다.
#     독립 A/B(부분문자열 flip): dev gain45/loss0, val gain310/loss6 — 양쪽 net-positive.
#   ⚠ 미채택: 䤎(U+490E, 둥근 불릿)은 세계사·생물 목록(list_item)에선 gold ⠔⠔로 맞지만
#     외국어 어휘 사이드바(text)에선 gold가 불릿 없이 ⠴표제어로 적어 문자 문맥만으론 못
#     가른다(독립 A/B val net-negative). 요소 타입 배선 시 list_item 한정 재도입 후보.
#     䤋(U+490B, 어휘 표제 별표→관행상 불릿 ⠔⠔)은 gold-correct·0 loss지만 효과가 코퍼스
#     반올림 이하(~416셀)라 이번엔 보류.
# ⚠ _SPECIAL_MAP(sanitize)와 분리한 전용 경로 — 병합 충돌 회피.
_LEGACY_CIRCLED_BLACK = {"❶": "①", "❷": "②", "❸": "③", "❹": "④", "❺": "⑤", "❻": "⑥"}
_LEGACY_CIRCLED_RE = re.compile(r"[❶-❻]")


def _restore_circled_black(text: str) -> str:
    # 인용 콜아웃 ❶[…]은 gold가 번호를 안 붙임 → 제거, 그 밖은 흰 원문자로 정규화.
    # ⚠ _restore_legacy_glyphs(:800)와 이름·정규식을 반드시 분리할 것 — 한때 양쪽이
    #   같은 이름을 써서 나중 정의가 5자 복원을 통째로 가리는 사고가 있었다.
    def _rep(m: re.Match) -> str:
        return "" if text[m.end():m.end() + 1] == "[" else _LEGACY_CIRCLED_BLACK[m.group()]
    return _LEGACY_CIRCLED_RE.sub(_rep, text)


# ── 숨김표 반복 (제57항) ─────────────────────────────────────────────────────
# 제57항: "숨김표가 여러 개 붙어 나올 때에는 _과 l 사이에 해당 숨김표의 점형을 묵자의
# 개수만큼 적어 나타낸다." 규정 예시(한국점자규정 제5장 제13절, 원문 BRF 그대로):
#     김○○ 씨    @o5_00l`,,o     → 래퍼 하나 안에 ⠴ 두 개  (⠸⠴⠴⠇)
#     이 ×××야!   o`_xxxl>6       → ⠸⠭⠭⠭⠇
#     △△도서관    _++liu,s@v3     → ⠸⠬⠬⠇
# 우리는 글자마다 래퍼를 새로 씌워 ⠸⠴⠇⠸⠴⠇로 냈다(묵자 n글자에 3n셀 — 규정은 n+2셀).
#
# ★ 점자 출력에서 합친다(원문에서가 아니라). 규정이 조건으로 삼는 "붙어 나온다"는
#   묵자 기준인데, 추출이 그 사이에 잡음을 끼워 넣는 일이 있다(사회문화 p055 원문
#   `(가) ○`○ 유치원` — MinerU 백틱). 그 잡음은 braillify를 지나며 사라지므로 원문
#   단계에서 런을 재면 같은 숨김표 쌍을 놓친다. 출력에서 실제로 인접한 것만 합친다.
# ★ 래퍼가 완전히 같은 것끼리만 합친다 — 서로 다른 숨김표가 섞인 배열(○△)은 제57항이
#   말하는 "해당 숨김표"가 하나로 정해지지 않으므로 건드리지 않는다.
# 글자 점형 자체는 바꾸지 않는다(gold가 규정 표와 다른 글리프를 쓰는 사례가 있으나
# 그건 별건 — 이 함수는 반복 표기 방식만 고친다).
_HIDDEN_RUN_RE = re.compile(r"(⠸(.)⠇)(?:\1)+")


def merge_hidden_runs(braille: str) -> str:
    """이어진 같은 숨김표 래퍼 ⠸X⠇⠸X⠇… → ⠸XX…⠇ (제57항)."""
    return _HIDDEN_RUN_RE.sub(
        lambda m: "⠸" + m.group(2) * (len(m.group(0)) // 3) + "⠇", braille)


def translate_tagged_text(text: str) -> str:
    """<!수식> 태그가 포함된 텍스트를 점자 BRF로 변환."""
    # 레거시 심볼 폰트 복원은 **수식 라우팅보다 먼저** 해야 한다. 뒤에 두면 "x¤ +1>0"이
    # 수식으로 안 잡혀 위첨자표(⠘⠼⠃)로 나가는데, 정답 도서는 제곱을 ⠣로 적는다.
    text = _restore_legacy_glyphs(text)     # 오디코딩 5자(⇂¤‹˘⇨)
    text = _restore_broken_subscripts(text)  # 깨진 아래첨자 ¡™£¢§ → ₁₂₃₄₆ (수식 라우팅 전, r16)
    text = _restore_circled_black(text)     # 검은 원문자 ❶-❻ (선지머리 정규화보다 먼저)
    text = _CHOICE_HEAD_RE.sub(r"\1 ", text)
    text = _BACKTICK_MATH_RE.sub(lambda m: f"<!수식>{m.group(1).rstrip()}<!/수식> ", text)
    text = _normalize_inline_math(text)     # $…$/\(…\) → <!수식> (P1: 수식 라우팅)
    # 구분자 없는 평문 수식(cos 2α=1-2 sin² α)도 같은 경로로 보낸다 — 수학 본문의
    # 16%가 이 형태다(inline_math 모듈이 오탐 없이 구간만 골라 태그를 붙인다).
    text = inline_math.wrap(text)
    if _BOOK_STYLE:
        text = _book_roman_to_cells(text)   # 로마 숫자 섹션번호 → 낱자 점형(도서 관행, 수식 밖만)
    text = _normalize_roman_numerals(text)  # 로마 숫자 → 로마자(제36항), braillify 거부 방지
    text = sanitize_for_braille(text)        # PUA·제어문자 정화(요소 전체 소실 방지)
    if _BRAILLIFY_AVAILABLE:
        return merge_hidden_runs(_translate_with_braillify(text))
    return merge_hidden_runs(_translate_fallback(text))


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


# ── 드러냄표(제56항) 오검출 억제 ─────────────────────────────────────────────
# 밑줄 감지는 '글자 아래 얇은 가로선'이라 분수 가로선·선지 밑줄·영문 빈칸선까지 집는다.
# 실측(전 코퍼스): 한글이 없는 드러냄 태그 389건 중 354건(91%)이 **정답에 드러냄표가
# 한 번도 없는 페이지**에 찍힌다. 과목 분해가 원인을 확정한다 —
#   수학2 우리 142회 / 정답 0회(97p 전수 0). 태그 내용이 '6'·'x'·'f(x)'·'1+cosb' 로
#   전부 분수 분자다(가로선=분수선 오인). 외국어 175건은 영문 빈칸선, 생물 40건은 선지 ①ㄱ.
# 근본 수정은 pdf_analyzer.underline_rects(분수선 배제)지만 그건 재추출이 필요하다.
# 여기서는 '한글 없는 드러냄'만 태그를 걷어낸다(내용은 보존 — 글자를 잃지 않는다).
_EMPH_PAIR_RE = re.compile(r"<!드러냄>(.*?)<!/드러냄>", re.S)
_HANGUL_ANY_RE = re.compile(r"[가-힣]")


def _drop_nonkorean_emphasis(text: str) -> str:
    """한글이 없는 드러냄 구간은 밑줄 오검출로 보고 태그만 제거(내용은 유지)."""
    return _EMPH_PAIR_RE.sub(
        lambda m: m.group(1) if not _HANGUL_ANY_RE.search(m.group(1)) else m.group(0),
        text,
    )


# ── ASCII 작은따옴표 복원(제49항 표) ─────────────────────────────────────────
# 규정 제49항 표: 여는 작은따옴표 ‘=`,8`(⠠⠦) · 닫는 작은따옴표 ’=`0'`(⠴⠄).
# 제61항: 아포스트로피(’)=`'`(⠄). 즉 **같은 묵자 글자가 문맥에 따라 두 점형**이고,
# symbol_table의 `'`→⠄는 제61항(아포스트로피) 쪽 매핑이다.
# 문제: 추출(PyMuPDF·MinerU)이 곡선 따옴표 ‘ ’를 ASCII '로 평탄화해 올 때가 있어,
# 인용부호로 쓰인 따옴표가 통째로 아포스트로피 한 셀(⠄)로 뭉개진다.
#   언어 p197 '배열' → 우리 ⠄⠘⠗⠳⠄ / 정답·braillify ⠠⠦⠘⠗⠳⠴⠄
# 그래서 **인용부호가 확실한 짝만** 곡선 따옴표로 되돌려 symbol_table의 ‘·’ 매핑에 태운다.
# ⚠ 코퍼스의 ASCII '는 대부분 따옴표가 아니다(dev 63요소·val 223요소 중 한글 감쌈은
#   13·64요소뿐). 나머지는 한컴 수식 폰트 오독 — 근호 '3=√3·'ƒ2x+1=√(2x+1) 와
#   도함수/유전자 프라임 f'(x)·y'·X'Y 다. 그래서 조건을 아래로 좁힌다:
#     ① 짝을 이루고 ② 안쪽에 한글이 있고 ③ 안쪽에 수식 잔재(= ( ) ƒ ∂ ¤ ` $ \ 태그)가 없고
#     ④ 여는 따옴표 앞이 영숫자가 아니며(f'·y'·X'·2'5 배제)
#     ⑤ 여는 따옴표 앞이 '로마자 한 글자 + 공백'이 아니다(깨진 표기 `f '(x)` 배제).
# 실측(코퍼스 요소 단위 재점역 대조): 뒤집힘 dev 11요소 중 +1 / val 58요소 중 +20,
# 역전(적중→미스) dev·val 모두 0.
_ASCII_SQ_PAIR_RE = re.compile(r"(?<![0-9A-Za-z])'([^'\n]{1,40}?)'(?!\()")
_SQ_INNER_BAN_RE = re.compile(r"[=()ƒ∂¤`$\\<>⠀-⣿]|<!")
_SQ_PRIME_LEAD_RE = re.compile(r"[A-Za-z][ \t]$")


def _restore_ascii_single_quotes(text: str) -> str:
    """인용부호가 확실한 ASCII ' 짝만 곡선 따옴표 ‘ ’로 되돌린다(제49항)."""
    if "'" not in text:
        return text
    out: list[str] = []
    pos = 0
    for m in _ASCII_SQ_PAIR_RE.finditer(text):
        if m.start() < pos:
            continue
        inner = m.group(1)
        if not _HANGUL_ANY_RE.search(inner) or _SQ_INNER_BAN_RE.search(inner):
            continue
        if _SQ_PRIME_LEAD_RE.search(text[:m.start()]):
            continue
        out.append(text[pos:m.start()])
        out.append("‘" + inner + "’")
        pos = m.end()
    if not out:
        return text
    out.append(text[pos:])
    return "".join(out)


EMPHASIS_OPEN, EMPHASIS_CLOSE = _TAG_PAIR_MARKER["드러냄"]  # ⠠⠤ … ⠤⠄ (제56항)


def emphasis_marker_spans(
    braille: str, source_text: str
) -> list[tuple[int, int, str]]:
    """점역 결과에서 드러냄표 마커(⠠⠤…⠤⠄, KBR-6.13.56) 위치 → (start, end, tag) 목록.

    source-gate(tn_marker_spans와 같은 원칙): 출력만 스캔하면 붙임표(⠤)·점역자 주(⠠⠄)
    등 유사 점형을 오인하므로, 원본의 **한글 든 드러냄 쌍 개수만큼만** 앞에서부터
    쌍(open→close)으로 짝지어 emit한다. 한글 없는 쌍은 _drop_nonkorean_emphasis가
    태그를 걷어내 마커 자체가 없다(개수 일치). 표 격자 경로는 drop 미적용이라 이
    게이트가 보수적 — 부족 emit은 허용, 과잉 emit(환각) 금지.
    """
    n = sum(
        1 for m in _EMPH_PAIR_RE.finditer(source_text)
        if _HANGUL_ANY_RE.search(m.group(1))
    )
    if n == 0:
        return []
    spans: list[tuple[int, int, str]] = []
    pos = 0
    for _ in range(n):
        i = braille.find(EMPHASIS_OPEN, pos)
        if i == -1:
            break
        j = braille.find(EMPHASIS_CLOSE, i + len(EMPHASIS_OPEN))
        if j == -1:
            break
        spans.append((i, i + len(EMPHASIS_OPEN), "emphasis_open"))
        spans.append((j, j + len(EMPHASIS_CLOSE), "emphasis_close"))
        pos = j + len(EMPHASIS_CLOSE)
    return spans


def translate_with_breaks(text: str) -> tuple[list[str], list[list[int]]]:
    """텍스트 → (논리 줄별 점자, 줄별 음절 줄바꿈 offset). 32칸 분리는 layout이 수행.

    원문 개행(\\n)으로만 논리 줄을 나눈다(하드 32분리 폐기 — 음절·지시부호·마커를
    칸 중간에서 쪼개지 않기 위함, §1.2.1). 각 줄의 break offset은 layout `_wrap_line`이
    32칸 줄바꿈에 사용한다.
    """
    # ★ 문항 번호 마침표(_QNUM_RE)는 요소 전체에서 먼저 본다 — 아래 split("\n")이
    #   줄을 쪼개면 추출이 흔히 번호를 자기 줄에 홀로 주는 탓에 '\s+\S' 룩어헤드가
    #   사라져 _apply_book_style 안의 같은 규칙이 영영 발동하지 못한다("2\n다음은…").
    #   _apply_book_style의 호출은 그대로 둔다 — 치환 뒤엔 '2.' 다음이 '.'이라
    #   룩어헤드가 실패하므로 이중 적용되지 않는다(멱등).
    text = _QNUM_RE.sub(r"\1.", text)
    # ★ '만을\n에서' 소실 구멍·개행 낀 괄호는 줄 단위 관행 정규화가 못 잡는다 —
    #   요소 전체 수준에서 선적용(이 개행은 원문 구조가 아니라 추출 산물).
    text = _BOGI_GAP_RE.sub(r"\1 ‘보기’\2", text)
    text = _drop_nonkorean_emphasis(text)
    # 추출이 평탄화한 ASCII 작은따옴표 복원 — 줄 분리 전에 요소 전체에서 짝을 본다.
    text = _restore_ascii_single_quotes(text)
    if _BOOK_STYLE:
        # ★ 보기 마커 원문 복원(ㄱㄴㄷㄹ)은 나열 시퀀스가 필요해 요소 전체에서 선적용해야
        #   한다 — 줄 분리 후엔 줄당 마커 1개라 ≥2 가드에 걸려 발동 못 한다(2026-07-18).
        text = _normalize_bogi_markers(text)
        text = _MARK_PAREN_RE.sub(_paren_repl, text)
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
# 잔류 정화용 비재귀 훅 — _braillify는 수식 라우팅을 타지 않아 convert_latex로 되돌아오지
# 않는다(잔류 조각 '_'·'.'을 translate_tagged_text로 넘기면 inline_math.wrap이 다시
# 수식으로 감싸 무한 재귀가 된다).
_kor_math_rules.w2c_register_plain_hook(_braillify)
