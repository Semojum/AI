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

import logging
import re

from app.ai.braille.kor_math_rules import convert_latex, digits_to_braille
from app.ai.braille.symbol_rules import substitute_symbols

logger = logging.getLogger(__name__)

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


# ── 인라인 태그 파서 (점역 직전 텍스트 → 점자 마커) — plan §3-5 ──────────────
# 형식: 여는 <!이름>, 닫는 <!/이름>. 유일 인식 앵커 <!. 정규식 옵션 슬래시.
# 매핑은 다대일(태그명 달라도 점자 동일 가능). 미지 태그는 안전 제거(점자화로 안 깨뜨림).
_TAG_TOKEN_RE = re.compile(r"<!/?[^>]+>")

# 단일·대칭 인라인 마커: 태그명 → 점자 글리프
_TAG_INLINE_MARKER: dict[str, str] = {
    "점역자주": "⠠⠄",   # BBPG-1.2.6 점역자 주 — 양끝 동일(대칭)
    "표빈칸":   "⠿⠿",   # 표 기입칸
    "네모빈칸": "⠸⠦",   # 체크박스 □
}

# 테두리(글상자 = 표, BBPG-1.2.5): (캡, 채움) 글리프. 32칸 한 줄로 렌더.
_BORDER_FILL: dict[str, tuple[str, str]] = {
    "표윗테두리":   ("⠿", "⠛"),  # 위: 첫/끝 = , 중간 g
    "표아랫테두리": ("⠿", "⠶"),  # 아래: 첫/끝 = , 중간 7
}
_BORDER_COLS      = 32
_BORDER_BLANK     = "⠀"   # 점자 빈칸(U+2800)
_BORDER_LEFT_FILL = 4     # 캡 뒤 채움 칸 → 제목 7칸에서 시작(BBPG-1.2.5(4)②: 캡1+채움4+빈칸1)

# 신형식 <!이름>…<!/이름> + 구형식 <!이름>…<!이름> 모두 수용(닫기 슬래시 옵션)
_BORDER_PAIR_RE = {
    name: re.compile(rf"<!{re.escape(name)}>(.*?)<!/?{re.escape(name)}>", re.DOTALL)
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


def substitute_tags(text: str) -> str:
    """인라인 태그(<!이름>/<!/이름>)를 점자 마커로 치환. 미지 태그는 안전 제거.

    치환 결과는 점자 Unicode이므로 이후 _emit_mixed/braillify가 보존한다(이중 변환 없음).
    """
    # 1) 테두리 쌍 (중간 제목 가능) → 32칸 줄
    for name, pat in _BORDER_PAIR_RE.items():
        text = pat.sub(
            lambda m, n=name: _border_line(n, _braillify(m.group(1).strip())), text
        )

    # 2) 단일·대칭 인라인 마커 + 미지 태그 제거
    def _token_sub(m: re.Match) -> str:
        name = _tag_name(m.group(0))  # "<!" ... ">" 안쪽, 닫기 슬래시 제거
        if name in _TAG_INLINE_MARKER:
            return _TAG_INLINE_MARKER[name]
        logger.warning("translator: 미지 태그 제거 %s", m.group(0))
        return ""

    text = _TAG_TOKEN_RE.sub(_token_sub, text)
    # 3) 그 외 잔여 <...>(비-! 태그) 안전 제거
    return _TAG_RE.sub("", text)


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
    result = substitute_tags(result)
    result = substitute_symbols(result)
    return _braillify_fallback(result)


def translate_tagged_text(text: str) -> str:
    """<formula> 태그가 포함된 텍스트를 점자 BRF로 변환."""
    if _BRAILLIFY_AVAILABLE:
        return _translate_with_braillify(text)
    return _translate_fallback(text)
