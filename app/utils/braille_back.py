"""역점역 (점자 BRF → 한국어 텍스트) — 점역 결과 검증 보조 도구.

점역사가 아니어도 점자 출력이 원문과 맞는지 눈으로 확인하려고 만든다.
점자→텍스트는 본질적으로 모호하다(같은 셀이 로마자표·따옴표·단위 접두로 중복,
약자·약어로 다대일). 따라서 이 디코더는 **근사**다:
  - 한글 음절: braillify를 정방향으로 돌려 만든 완전 역맵으로 정확히 복원(약자 포함).
  - 숫자(수표 ⠼)·로마자(로마자표 ⠴…종료표 ⠲)·점역자 주(⠠⠄): 규칙으로 복원.
  - 특수기호·단위·그리스문자: symbol_table 역인덱스(긴 셀 우선).
  - 못 푸는 셀: ⟨XXXX⟩(유니코드 코드포인트)로 남겨 정직하게 표시.

정방향 점역이 약자(braillify)를 쓰므로 100% 가역은 불가능하다. 의미 검증용이지
법적 정본이 아니다.

사용:
    from app.utils.braille_back import decode
    decode("⠑⠯⠨⠕⠂⠺")            # → '물질'
CLI:
    python -m app.utils.braille_back "⠑⠯⠨⠕⠂⠺"
    python -m app.utils.braille_back --file path/to/result.txt
재생성(약자 음절 역맵, braillify 필요):
    python -m app.utils.braille_back --regen
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from app.ai.braille.symbol_rules import SYMBOL_TABLE

_MAP_PATH = Path(__file__).with_name("braille_syllable_map.json")

# ── 셀 상수 ──────────────────────────────────────────────────────────────
_NUMBER_SIGN = "⠼"           # 수표 (뒤 a~j 셀 = 1~0)
_ROMAN_START = "⠴"           # 로마자표
_ROMAN_END = "⠲"             # 로마자 종료표 (= 마침표 셀과 동일)
_CAPITAL = "⠠"               # 대문자 표시 (연속 ⠠⠠ = 대문자 단어)
_TN_MARKER = "⠠⠄"            # 점역자 주(양끝)
_SPACE_CELL = "⠀"            # 점자 공백(U+2800)
# 어말 문장부호 — 받침 셀과 같은 점형이라(같=⠫⠦) 뒤가 공백/끝일 때만 부호로 본다.
_SENT_END = {"⠦": "?", "⠖": "!"}

# 알파벳 점형 → 글자 (translator._ALPHA_MAP의 역)
_ALPHA_REV = {
    "⠁": "a", "⠃": "b", "⠉": "c", "⠙": "d", "⠑": "e", "⠋": "f", "⠛": "g",
    "⠓": "h", "⠊": "i", "⠚": "j", "⠅": "k", "⠇": "l", "⠍": "m", "⠝": "n",
    "⠕": "o", "⠏": "p", "⠟": "q", "⠗": "r", "⠎": "s", "⠞": "t", "⠥": "u",
    "⠧": "v", "⠺": "w", "⠭": "x", "⠽": "y", "⠵": "z",
}
# 수표 뒤 숫자 점형 → 숫자 (1~9,0 = a~i,j 점형)
_DIGIT_REV = {
    "⠁": "1", "⠃": "2", "⠉": "3", "⠙": "4", "⠑": "5",
    "⠋": "6", "⠛": "7", "⠓": "8", "⠊": "9", "⠚": "0",
    "⠂": ",", "⠄": ".",   # 자릿점/소수점(근사)
}

# 단어 약어(braillify) — 음절 분해 불가, 직접 등록. (한글 점자 제3장 단어약어)
_WORD_ABBR = {
    "⠁⠉": "그러나", "⠁⠒": "그러면", "⠁⠢": "그러므로", "⠁⠝": "그런데",
    "⠁⠎": "그래서", "⠁⠥": "그리고", "⠁⠱": "그리하여",
}


def _build_symbol_rev() -> dict[str, str]:
    """symbol_table(문자→점자) 역인덱스. 충돌 시 먼저 등록된 문자 유지."""
    rev: dict[str, str] = {}
    for sym, braille in SYMBOL_TABLE.items():
        if braille and braille not in rev:
            rev[braille] = sym
    return rev


def _load_syllable_rev() -> dict[str, str]:
    """점자셀→한글음절 역맵(JSON 캐시). 없으면 빈 맵(경고)."""
    if _MAP_PATH.exists():
        return json.loads(_MAP_PATH.read_text(encoding="utf-8"))
    return {}


_SYMBOL_REV = _build_symbol_rev()
_SYLLABLE_REV = _load_syllable_rev()
# 통합 역맵(약어 + 음절 + 기호). 긴 셀 우선 매칭을 위해 최대 길이 기록.
_COMBINED: dict[str, str] = {**_SYMBOL_REV, **_SYLLABLE_REV, **_WORD_ABBR}
# 단독 문장부호(마침표·쉼표·느낌표)도 풀리도록 — 기존 기호 매핑은 덮지 않는다.
for _c, _t in (("⠲", "."), ("⠐", ","), ("⠖", "!")):
    _COMBINED.setdefault(_c, _t)
# 변이체 정본화 — 같은 점형이 여러 유니코드(붙임표/하이픈/대시)로 매핑될 때 ASCII 정본 우선.
# ⠤는 symbol_table에서 '–'(en dash)로 먼저 잡히나, 숫자 범위·붙임표는 ASCII '-'가 정본.
for _c, _t in (("⠤", "-"),):
    _COMBINED[_c] = _t
_MAX_CELLS = max((len(k) for k in _COMBINED), default=1)


_SUBSCRIPT = "⠰"   # 첨자·약물 표 등 — 로마자 런 안에서는 근사로 건너뜀

def _decode_roman_run(s: str, i: int) -> tuple[str, int] | None:
    """로마자 런이면 (텍스트, 다음위치), 아니면 None.

    시작: 로마자표 ⠴ , 또는 대문자 단어표 ⠠⠠ 다음에 알파벳(문장 중 영문, 예 TV).
    대문자: ⠠⠠(단어 전체)·⠠(한 글자). 종료: 공백·수표 ⠼·종료표 ⠲·비로마자 셀.
    (단위 ℃=⠴⠙… 는 _COMBINED 긴-셀 매칭이 먼저 잡으므로 여기 도달하지 않는다.)
    """
    n = len(s)
    if s[i] == _ROMAN_START:                       # ⠴ 로마자표
        j = i + 1
    elif s[i:i + 2] == _CAPITAL + _CAPITAL and i + 2 < n and s[i + 2] in _ALPHA_REV:
        j = i                                      # 로마자표 없이 대문자 단어(예: TV)
    else:
        return None

    out: list[str] = []
    caps_word = False
    while j < n:
        c = s[j]
        if c in (_SPACE_CELL, " ", _NUMBER_SIGN):  # 공백·수표 → 런 종료(소비 안 함)
            break
        if c == _ROMAN_END:                        # 종료표 ⠲ → 소비하고 종료
            j += 1
            break
        if s[j:j + 2] == _CAPITAL + _CAPITAL:       # 대문자 단어표
            caps_word = True
            j += 2
            continue
        if c == _CAPITAL:                           # 단일 대문자표
            j += 1
            if j < n and s[j] in _ALPHA_REV:
                out.append(_ALPHA_REV[s[j]].upper())
                j += 1
            continue
        if c in _ALPHA_REV:
            ch = _ALPHA_REV[c]
            out.append(ch.upper() if caps_word else ch)
            j += 1
            continue
        if c == _SUBSCRIPT:                          # 첨자표 등 → 근사로 건너뜀
            j += 1
            continue
        break                                       # 비로마자 셀 → 런 종료
    if not out:
        return None
    return "".join(out), j


def _decode_number(s: str, i: int) -> tuple[str, int]:
    """s[i]=수표 ⠼. 뒤따르는 숫자 셀을 소비해 (숫자문자열, 다음위치) 반환.

    수 안의 소수점은 마침표 셀 ⠲로 적힌다(3.14=⠼⠉⠲⠁⠙) — ⠲ 뒤에 숫자가 오면
    소수점으로 보고 수를 이어 읽는다. 자릿점 쉼표 ⠂는 _DIGIT_REV로 이어진다.
    """
    j = i + 1
    out: list[str] = []
    while j < len(s):
        if s[j] in _DIGIT_REV:
            out.append(_DIGIT_REV[s[j]])
            j += 1
        elif s[j] == _ROMAN_END and j + 1 < len(s) and s[j + 1] in _DIGIT_REV:
            out.append(".")        # 소수점(⠲) — 뒤에 숫자가 있을 때만
            j += 1
        else:
            break
    if not out:                    # 수표 뒤 숫자 없음 → 기호로 둠
        return "⟨⠼⟩", i + 1
    return "".join(out), j


def decode(braille: str) -> str:
    """점자 BRF 문자열 → 한국어 텍스트(근사). 줄바꿈은 보존."""
    out_lines = []
    for line in braille.split("\n"):
        out_lines.append(_decode_line(line))
    return "\n".join(out_lines)


def _decode_line(s: str) -> str:
    out: list[str] = []
    i, n = 0, len(s)
    while i < n:
        ch = s[i]
        # 공백(점자/일반)
        if ch == _SPACE_CELL or ch == " ":
            out.append(" ")
            i += 1
            continue
        # 점역자 주 마커
        if s[i:i + 2] == _TN_MARKER:
            out.append("【점역자주】")
            i += 2
            continue
        # 수표 숫자 — 동그라미숫자 기호(①=⠼⠉ 등)보다 먼저(평문 숫자가 흔함).
        if ch == _NUMBER_SIGN:
            txt, j = _decode_number(s, i)
            out.append(txt)
            i = j
            continue
        # 긴 셀 우선 매칭(단위·기호·약어·음절). 단위(℃=⠴⠙…)를 로마자보다 먼저
        # 잡아야 로마자 런이 멀리 있는 마침표 ⠲까지 삼키지 않는다.
        best_ln = 0
        for ln in range(min(_MAX_CELLS, n - i), 0, -1):
            if s[i:i + ln] in _COMBINED:
                best_ln = ln
                break
        def _final(after: int) -> bool:
            """위치 after가 줄 끝이거나 공백이면 어말(문장부호 분리 판단)."""
            return after >= n or s[after] in (_SPACE_CELL, " ")

        if best_ln >= 2:
            seg = s[i:i + best_ln]
            # 마침표가 음절 뒤에 붙어 다른 음절로 오인된 경우 분리(다.=닾 → 다 + .).
            # ?·!(⠦·⠖)은 받침과 충돌(같=⠫⠦)하므로 **어말일 때만** 분리(요?=⠬⠦ → 요 + ?).
            if seg[-1] == "⠲" and seg[:-1] in _COMBINED:
                out.append(_COMBINED[seg[:-1]])
                out.append(".")
            elif seg[-1] in _SENT_END and seg[:-1] in _COMBINED and _final(i + best_ln):
                out.append(_COMBINED[seg[:-1]])
                out.append(_SENT_END[seg[-1]])
            else:
                out.append(_COMBINED[seg])
            i += best_ln
            continue
        # 로마자 런(로마자표 ⠴ 또는 대문자 단어표 ⠠⠠+알파벳) — 단독 ⠴(따옴표)보다 우선
        roman = _decode_roman_run(s, i)
        if roman is not None:
            txt, j = roman
            out.append(txt)
            i = j
            continue
        # 어말 ?·!(⠦·⠖) — 단독으로 떨어진 경우 따옴표(") 대신 문장부호로(안녕?=…⠦).
        if ch in _SENT_END and _final(i + 1):
            out.append(_SENT_END[ch])
            i += 1
            continue
        # 단일 셀 매칭(따옴표·쉼표 등)
        if best_ln == 1:
            out.append(_COMBINED[ch])
            i += 1
            continue
        # 못 푸는 셀 → 코드포인트 표시(정직)
        out.append(f"⟨{ord(ch):04X}⟩")
        i += 1
    return "".join(out)


# ── 약자 음절 역맵 재생성 (braillify 필요, 개발 시 1회) ───────────────────
def regenerate_syllable_map() -> int:
    """모든 한글 음절(가~힣)을 braillify로 정방향 변환해 셀→음절 역맵 생성·저장.

    braillify가 약자를 적용하므로, 음절을 직접 forward 돌린 결과가 곧 정본 역맵이다.
    충돌(서로 다른 음절이 같은 셀)은 먼저 나온 음절 유지.
    """
    from braillify import translate_to_unicode as _fwd
    rev: dict[str, str] = {}
    for code in range(0xAC00, 0xD7A4):           # 가(AC00) ~ 힣(D7A3)
        syl = chr(code)
        cells = _fwd(syl)
        if cells and cells not in rev:
            rev[cells] = syl
    _MAP_PATH.write_text(json.dumps(rev, ensure_ascii=False, indent=0), encoding="utf-8")
    return len(rev)


def main(argv: list[str] | None = None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    if not argv:
        print(__doc__)
        return 0
    if argv[0] == "--regen":
        n = regenerate_syllable_map()
        print(f"음절 역맵 재생성: {n}개 → {_MAP_PATH}")
        return 0
    if argv[0] == "--file":
        text = Path(argv[1]).read_text(encoding="utf-8")
    else:
        text = " ".join(argv)
    print(decode(text))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
