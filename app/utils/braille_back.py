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
import os
import re
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

# 받침 ㅍ 음절 — ⠲가 마침표인지 받침 ㅍ인지 가른다(높=⠉⠥⠲ vs 노+마침표).
# 한국어에서 받침 ㅍ이 실제로 쓰이는 음절은 닫힌 집합이라 목록으로 가르는 게 가장 정확하다.
# (위치로 가르면 닫는 따옴표 앞에서 틀린다 — `나타난다.’` → `나타난닾’`.)
_PIEUP_FINAL = frozenset("갚겊깊높늪덮릎섶숲싶앞엎옆잎짚")

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
# ── 하단 숫자 (R2, 2026-08-24) ──────────────────────────────────────────────
# 정방향 `kor_math_rules._DROPPED_DIGIT` 의 역. 수표 뒤 항목 번호·로그 밑에 쓰인다.
# 이게 없어 `⠼⠆`(=2) 가 `⟨⠼⟩;` 로 샜다 — 정답 도서에도 같은 꼴이 92줄에 나온다
# (`⠼⠂ … ⠼⠆ … ⠼⠒` = 1·2·3 연번이 결정적 근거였다).
# ⚠ 위 `_DIGIT_REV` 와 겹치는 키가 없다(⠂ 만 겹치고 자릿점 쪽이 먼저다 — 숫자 런 안에서만
#   쓰이므로 항목 번호 자리에는 안 걸린다).
_DROPPED_DIGIT_REV = {
    "⠂": "1", "⠆": "2", "⠒": "3", "⠲": "4", "⠢": "5",
    "⠖": "6", "⠶": "7", "⠦": "8", "⠔": "9", "⠴": "0",
}

# 단어 약어(braillify) — 음절 분해 불가, 직접 등록. (한글 점자 제3장 단어약어)
_WORD_ABBR = {
    "⠁⠉": "그러나", "⠁⠒": "그러면", "⠁⠢": "그러므로", "⠁⠝": "그런데",
    "⠁⠎": "그래서", "⠁⠥": "그리고", "⠁⠱": "그리하여",
}

# ── 수학 점자 역맵 (수식 구역에서만 적용) ────────────────────────────────
# 정방향 kor_math_rules가 쓰는 구조·연산자·그리스 셀의 역. 같은 점형이 한글 음절과
# 겹치므로(⠘=바·⠜=야·⠌=예·⠡=연) **수식 토큰으로 판정된 경우에만** 이 맵을 적용한다.
# (판정: 토큰에 수표 ⠼와 수학 셀이 함께 있거나, 호출자가 math=True로 요소가 수식임을
#  알려줄 때. 한글 본문의 ⠘/⠜ 약자는 수표가 없어 텍스트로 남는다.)
_MATH_REV_MULTI = {       # 다중 셀(긴 것 먼저 매칭)
    "⠨⠒⠒": "≠", "⠸⠰⠑": "ln",
    "⠸⠌": "/", "⠌⠌": "÷", "⠒⠒": "=", "⠖⠖": "≤", "⠲⠲": "≥",
    # 「수학 점자」 제4항 부등호 — < 와 > 가 빠져 있었다(≤·≥·≠만 있었다).
    # 그래서 `(x < t)`가 `(x--t)`로 나왔다. 홑 ⠔는 음수·붙임표, ⠢는 덧셈이라
    # 두 칸을 먼저 봐야 갈린다(_MATH_REV_MULTI는 긴 것부터 맞춘다).
    "⠔⠔": "<", "⠢⠢": ">", "⠨⠔⠔": "≮", "⠨⠢⠢": "≯",
    # 수학 기호 역매핑 누락분(2026-08-24). 수식 모드 전용 표라 한글·영어와 겹쳐도 안전하다.
    # ★ 한 칸짜리는 넣지 않는다. ∫=⠮ 는 한글 '을', ∪=⠬ 는 '료', ∩=⠩ 는 '유'와 점형이 같아
    #   인라인 수식으로 잘못 분류된 한글 토큰을 먹는다(실측 val 악화 34건 중 22건이 이것).
    #   ∮=⠾ 는 묶음 괄호 닫기(제6항 2호)와 같은 셀이라 역시 넣지 않는다.
    #   적분·합집합은 코퍼스 산출물에서 실사용이 확인되지 않아 손해만 남는다.
    "⠮⠮": "∬", "⠐⠲": "⊃", "⠨⠖": "∉", "⠠⠨⠎": "Σ", "⠶⠶": "≡", "⠢⠔": "±",
    "⠴⠄": "⊥",
    # ⚠ 구판 "⠦⠦→≤"는 폰트 오독(66=⠖⠖) + 중첩 묶음 ⠦⠦…에 오발동해 제거(2026-07-19)
    "⠒⠕": "→", "⠸⠩": "∇",
    # 일반연산·평행 (수학 제15·44항 — 정방향 2026-07-19 정정과 정합)
    "⠸⠴⠴": "⦾", "⠸⠴": "∘", "⠸⠲": "∙", "⠸⠢": "⊕", "⠸⠔": "⊖", "⠰⠆": "∥",
    # 그리스 소문자 (수학 제13항 표 — η=.:·χ=.& 정정 반영)
    "⠨⠁": "α", "⠨⠃": "β", "⠨⠛": "γ", "⠨⠙": "δ", "⠨⠑": "ε", "⠨⠵": "ζ",
    "⠨⠱": "η", "⠨⠹": "θ", "⠨⠊": "ι", "⠨⠅": "κ", "⠨⠇": "λ", "⠨⠍": "μ",
    "⠨⠝": "ν", "⠨⠭": "ξ", "⠨⠏": "π", "⠨⠗": "ρ", "⠨⠎": "σ", "⠨⠞": "τ",
    "⠨⠥": "υ", "⠨⠋": "φ", "⠨⠯": "χ", "⠨⠽": "ψ", "⠨⠺": "ω",
}
_MATH_REV_SINGLE = {
    "⠘": "^", "⠰": "_", "⠜": "√", "⠻": "√", "⠌": "분의",
    "⠷": "(", "⠾": ")", "⠡": "×", "⠢": "+", "⠔": "-", "⠐": "·", "⠿": "∞",
    # 수학 소괄호(제6항 8`0) — 도서 랩 관행도 이 점형(2026-07-19 정방향 정합)
    "⠦": "(", "⠴": ")",
}
# 대괄호(제6항 ('…,))·도 단위는 다중 셀에서 우선 매칭
_MATH_REV_MULTI.update({"⠷⠄": "[", "⠠⠾": "]", "⠴⠙": "°"})

# ── 새던 여덟 종 (R2, 2026-08-24) ────────────────────────────────────────────
# 대표가 실물 검수에서 지적한 `속⟨2808⟩난⟨2812⟩` 꼴이 이것이다. 정방향은 내는데 역맵에
# 없어 코드포인트가 그대로 샜다. formula 요소 267건 중 **100건(37.5%)** 이 샜고 348회다.
# 무엇이 몇 번 샜는지: ⠠ 132 · ⠸ 83 · ⠶ 72 · ⠈ 19 · ⠒ 18 · ⠆ 12 · ⠼ 10 · ⠂ 2.
#
# 정방향 정의(`kor_math_rules`)를 그대로 뒤집는다.
_MATH_REV_MULTI.update({
    # log — `_LOG_IND="⠸"` + `_LOG_NUM_SEP="⠠"`(밑이 숫자) / ⠰(밑이 변수)
    "⠸⠠": "log_", "⠸⠰": "log_",
    # 연립·조건분기 묶음 — `_SYS_OPEN/_SYS_CLOSE = "⠶⠄", "⠠⠶"`
    "⠶⠄": "{", "⠠⠶": "}",
    # 대문자 구절표 열기·닫기 — `_CAPS_OPEN="⠠⠠⠠"`, `_CAPS_CLOSE="⠠⠄"`
    "⠠⠠⠠": "", "⠠⠄": "",
    # 윗줄(bar)·모자(hat) — `_ACC_POSTFIX_MARK`
    "⠈⠉": "̅", "⠈⠈⠢": "̂",
})
_MATH_REV_SINGLE.update({
    "⠸": "log",     # 밑이 안 붙는 홑 log 지시자
    "⠶": "{",       # 중괄호(정방향 `\{`·`\}` 가 둘 다 ⠶) — 짝을 못 가르므로 여는 쪽으로 편다
    "⠠": "",        # 대문자표: 다음 글자를 크게 만드는 표시라 글자로는 안 남는다
    "⠈": "'",       # 프라임(제17항)
    "⠒": "=",       # 홑 ⠒ 는 등호 계열 잔재
    "⠆": ";",       # 구분자
    "⠂": ",",       # 쉼표
})
_MATH_MAX = max(len(k) for k in _MATH_REV_MULTI)
# 토큰이 수식인지 판정 — 첨자·근호·분수 셀(⠘⠰⠜⠻⠌)이 **수식 피연산자**(수표 ⠼ 또는
# 수식 여는괄호 ⠷)에 바로 이어질 때만 수식으로 본다. 한글 약자(바=⠘⠣·예=⠌⠣ 등)는
# 뒤에 모음 셀이 와서 이 패턴에 안 걸리므로 '3반'·'1/2개' 같은 숫자+한글이 오판되지 않는다.
_MATH_SIGNAL_RE = re.compile(r"[⠘⠰⠜⠻⠌][⠼⠷]")
_MATH_PAREN_CELLS = ("⠷", "⠾")                           # 수식 괄호(텍스트 괄호와 다름)
_BARE_OPS = {"⠡", "⠢", "⠔", "⠒⠒", "⠌⠌"}                 # 단독 토큰 연산자(×+−=÷)
# 그리스 소문자 접두 관행(2026-07-21): book 모드 정방향은 ⠈x를 낸다(kor_math_rules
# ._LC_GREEK 주석 참조). 역점역도 같은 판본을 읽어야 왕복이 성립하므로 ⠈x 별칭을 더한다.
# ⚠ ⠈은 초성 ㄱ이라 ⠈⠍=구·⠈⠎=거·⠈⠗=개처럼 흔한 한글 음절과 겹친다. 아래 GREEK 분류가
# '수식 토큰에 인접할 때만 수식'이라는 보수 규칙이라 단독 한글은 보존된다.
_LC_GREEK_REV = "⠈" if os.environ.get("BRAILLE_STYLE", "book") != "regulation" else "⠨"
if _LC_GREEK_REV != "⠨":
    _MATH_REV_MULTI.update({
        _LC_GREEK_REV + k[1]: v
        for k, v in list(_MATH_REV_MULTI.items())
        if k.startswith("⠨") and len(k) == 2 and v in "αβγδεζηθικλμνξοπρστυφχψω"
    })
# 그리스 소문자 토큰(접두+자음, 2셀) — 한글 음절과 겹쳐(π=줘) 단독으론 한글 우선,
# 수식 토큰에 인접할 때만 수식으로 본다.
_GREEK_TOKENS = {k for k, v in _MATH_REV_MULTI.items()
                 if len(k) == 2 and k[0] in "⠨⠈" and v in "αβγδεζηθικλμνξοπρστυφχψω"}


def _build_symbol_rev() -> dict[str, str]:
    """symbol_table(문자→점자) 역인덱스. 충돌 시 먼저 등록된 문자 유지."""
    rev: dict[str, str] = {}
    for sym, braille in SYMBOL_TABLE.items():
        if braille and braille not in rev:
            rev[braille] = sym
    # 그리스 소문자는 **두 접두 판본을 모두 읽는다**(2026-07-21). 정방향은 모드에 따라
    # 한 판본만 내지만, 역점역의 입력은 남의 점자책이라 규정형 ⠨x와 관행형 ⠈x가 섞여
    # 들어온다. 역방향은 다대일이라 둘 다 받는 게 정보 손실이 없다. 기존 키는 안 덮는다.
    for cells, sym in list(rev.items()):          # rev은 점자→문자 방향이다
        if len(cells) == 2 and cells[0] in "⠨⠈" and sym in "αβγδεζηθικλμνξοπρστυφχψω":
            alt = ("⠨" if cells[0] == "⠈" else "⠈") + cells[1]
            rev.setdefault(alt, sym)
    return rev


def _load_syllable_rev() -> dict[str, str]:
    """점자셀→한글음절 역맵(JSON 캐시). 없으면 빈 맵(경고)."""
    if _MAP_PATH.exists():
        return json.loads(_MAP_PATH.read_text(encoding="utf-8"))
    return {}


_SYMBOL_REV = _build_symbol_rev()
_SYLLABLE_REV = _load_syllable_rev()


def _load_special_rev() -> dict:
    """동그라미 숫자(①=⠼⠂, 제64항)·동그라미 문자·낱자(㉠=⠿⠁) 역맵.

    정방향 번역기로 생성(braille_special_rev.json). 이 문자들은 수표 ⠼·온표 ⠿ 뒤에
    특수 점형이 와서 평문 숫자·∞로 오인됐다 — _decode_line에서 수표보다 먼저 검사한다.
    """
    p = Path(__file__).with_name("braille_special_rev.json")
    try:
        return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}
    except Exception:
        return {}


_SPECIAL_REV = _load_special_rev()
_SPECIAL_MAX = max((len(k) for k in _SPECIAL_REV), default=0)
# 통합 역맵(약어 + 음절 + 기호). 긴 셀 우선 매칭을 위해 최대 길이 기록.
_COMBINED: dict[str, str] = {**_SYMBOL_REV, **_SYLLABLE_REV, **_WORD_ABBR}
# 단독 문장부호(마침표·쉼표·느낌표)도 풀리도록 — 기존 기호 매핑은 덮지 않는다.
# (⠲는 symbol_table에서 ∋로 먼저 잡힘 → 단독 ∋은 그대로, 어말 마침표는 _decode_line의
#  위치 규칙이 별도 처리한다.)
for _c, _t in (("⠲", "."), ("⠐", ","), ("⠖", "!")):
    _COMBINED.setdefault(_c, _t)
# 변이체 정본화 — 같은 점형이 여러 유니코드(붙임표/하이픈/대시)로 매핑될 때 ASCII 정본 우선.
for _c, _t in (("⠤", "-"),):
    _COMBINED[_c] = _t
# 소괄호 자리표시자(_mark_paren_pairs가 붙인다) → 실제 괄호
_COMBINED["\ufdd2"] = "("
_COMBINED["\ufdd3"] = ")"
_MAX_CELLS = max((len(k) for k in _COMBINED), default=1)


_SUBSCRIPT = "⠰"   # 첨자·약물 표 등 — 로마자 런 안에서는 근사로 건너뜀

# ── 영어 Grade 2 약자 역매핑 (2026-08-06) ──────────────────────────────────
# 정방향 `eng_braille`는 낱말을 약자로 줄인다(Player → ⠠⠏⠇⠁⠽⠻, er=⠻).
# 역점역이 그걸 모르면 약자 셀에서 런이 끊겨 뒤가 통째로 한글로 오독됐다
#   실측: 'Player' → '숴삭외영∋' · 'Windows' → 'W⟨2814⟩프어'
# 표는 **정방향 모듈에서 뒤집어 만든다** — 손으로 적으면 정방향과 어긋난다.
# 위치 제약(첫머리 전용·끝 전용)도 정방향 규칙 그대로 따른다.
def _build_eng_reverse() -> tuple[dict[str, str], dict[str, str], dict[str, str]]:
    """(어디서나, 낱말 첫머리 전용, 낱말 끝 쪽 전용) 세 벌의 셀→글자 표."""
    from app.ai.braille import eng_braille as _E

    anywhere: dict[str, str] = {}
    initial: dict[str, str] = {}
    final: dict[str, str] = {}
    for word, cell in _E.STRONG_GROUPS.items():
        anywhere.setdefault(cell, word)
    for word, cell in _E.WORD_INITIAL_SYLLABLE.items():
        initial.setdefault(cell, word)
    for word, cell in _E.INITIAL_5.items():
        initial.setdefault("⠐" + cell, word)
    for word, cell in _E.INITIAL_45.items():
        initial.setdefault("⠘" + cell, word)
    for word, cell in _E.INITIAL_456.items():
        initial.setdefault("⠸" + cell, word)
    for word, cell in _E.FINAL_46.items():
        final.setdefault("⠨" + cell, word)
    for word, cell in _E.FINAL_56.items():
        final.setdefault("⠰" + cell, word)
    for word, cell in _E.FINAL_EBAE_ONLY.items():
        final.setdefault(cell, word)
    # 낱자와 겹치는 것은 낱자를 이긴다고 보지 않는다 — 낱자는 마지막 폴백이다.
    return anywhere, initial, final


def _build_eng_words() -> dict[str, str]:
    """낱말 **전체**가 일치할 때만 쓰는 셀→낱말 표(단어기호 + 단축형).

    이게 없으면 `the`(⠮)가 한글 '을', `such`(⠎⠡)가 'sch'로 떨어진다 — 낱자 폴백이
    약자를 모르기 때문이다. 낱말 경계(로마자표 직후·공백·종료표)에서만 맞춰 본다.
    한 점형에 두 낱말이 걸리면(⠴=was/by) 정방향 표 순서대로 먼저 것을 쓴다.
    """
    from app.ai.braille import eng_braille as _E

    # ★ 한 칸짜리는 넣지 않는다. `WORDSIGNS`가 그렇다(x=⠭ it · k=⠅ knowledge ·
    #   f=⠋ from · y=⠽ you). 수식 변수와 점형이 같아서 넣으면 수식이 통째로 깨진다 —
    #   실측 32,036요소에서 개선 5 · 악화 962였다. 여러 칸 단축형만 쓴다.
    words: dict[str, str] = {}
    for word, cell in _E.SHORT_FORMS.items():
        if len(cell) >= 2:
            words.setdefault(cell, word)
    return words


_ENG_WORD = _build_eng_words()
_ENG_WORD_MAX = max((len(k) for k in _ENG_WORD), default=1)
_ENG_ANY, _ENG_INIT, _ENG_FINAL = _build_eng_reverse()
_ENG_MAX = max((len(k) for k in list(_ENG_ANY) + list(_ENG_INIT) + list(_ENG_FINAL)),
               default=1)


def _eng_group_at(s: str, j: int, at_word_start: bool) -> tuple[str, int] | None:
    """s[j]에서 시작하는 영어 약자 → (글자, 소비한 셀 수). 없으면 None."""
    for ln in range(min(_ENG_MAX, len(s) - j), 0, -1):
        seg = s[j:j + ln]
        if at_word_start and seg in _ENG_INIT:
            return _ENG_INIT[seg], ln
        if not at_word_start and seg in _ENG_FINAL:
            return _ENG_FINAL[seg], ln
        if seg in _ENG_ANY:
            return _ENG_ANY[seg], ln
    return None


def _roman_span_ahead(s: str, at: int) -> bool:
    """`at`부터 로마자 구간이 이어지는가 — **종료표 ⠲가 앞에 실제로 있는지**로 본다.

    제35항: 로마자 구간 안 숫자는 구간을 끊지 않는다(`A4`·`MP3`·`V1`). 숫자에서 끊으면
    뒤가 로마자 문맥을 잃는다. 다만 숫자 뒤가 한글인 표기도 있어(`A4용지`) 무조건 이으면
    한글을 삼킨다 — 그래서 종료표를 증거로 요구한다.

    ★ 종료표를 **증거로 요구한다**. 한글 음절 셀과 알파벳 셀이 대부분 겹치므로,
      "로마자로 읽히니까 이어 간다"로 판정하면 한글을 통째로 삼킨다.
      실측: `A4용지`(⠴⠠⠁⠼⠙⠬⠶⠨⠕ — 종료표 없음)가 `A4inggg지`로 깨졌다.
      제4항으로 종료표를 생략한 표기는 여기서 이어 가지 않는다 — 안전한 쪽으로 판단한다.
    """
    n = len(s)
    j = at
    seen = False
    while j < n:
        c = s[j]
        if c == _ROMAN_END:
            return seen                      # 종료표를 만났다 = 구간 안이었다
        if c in (_SPACE_CELL, " "):
            j += 1
            continue
        if (c in _ALPHA_REV or c in (_CAPITAL, _NUMBER_SIGN) or c in _DIGIT_REV
                or _eng_group_at(s, j, False) is not None
                or _eng_group_at(s, j, True) is not None):
            seen = True
            j += 1
            continue
        return False                          # 로마자로 안 읽히는 셀 → 구간 밖
    return False                              # 종료표 없이 끝 → 끊는다


def _decode_roman_run(s: str, i: int) -> tuple[str, int] | None:
    """로마자 런이면 (텍스트, 다음위치), 아니면 None.

    시작: 로마자표 ⠴ , 또는 대문자 단어표 ⠠⠠ 다음에 알파벳(문장 중 영문, 예 TV).
    대문자: ⠠⠠(단어 전체)·⠠(한 글자). 종료: 공백·종료표 ⠲·비로마자 셀.
    (단위 ℃=⠴⠙… 는 _COMBINED 긴-셀 매칭이 먼저 잡으므로 여기 도달하지 않는다.)

    ⚠ **⠼는 런 종료가 아니다** — 수표(제40항)이자 영어 약자 ble(EBAE)이라 두 뜻이 겹친다.
    가르는 기준은 **뒤 셀**이다: 뒤가 숫자 셀이면 수표(제35항 A4=⠴⠠⠁⠼⠙·MP3), 아니면 ble.
    코퍼스 실측(`V2/temp/i2_romanctx.py`, 2026-07-27): 로마자 런 안 ⠼ 중 뒤가 숫자 셀인
    것은 val 61/66 · dev 12/12이고 전부 V1·Ca2·A4형 수표, 뒤가 비숫자인 val 5는 전부 ble.
    '뒤가 숫자 셀인 ble'(-bled·-bler류)은 이 실측에서 로마자 런 안에 0건이라 수표로 둔다.
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
        if c in (_SPACE_CELL, " "):                # 공백 → 원칙은 런 종료
            # 제32항은 로마자표~종료표 **사이**를 한 구간으로 본다(`such tactics`).
            # 그래서 종료표가 실제로 앞에 있으면 공백을 넘어 이어 간다 —
            # `_roman_span_ahead`가 그 증거를 요구하므로 한글을 삼키지 않는다.
            # 증거가 없으면 종전대로 끊는다(⠴는 닫는 따옴표, ⠲는 마침표와 같은 셀이라
            # 구간처럼 보이는 한글 오탐이 정답 도서에 절반이다).
            if s[i] == _ROMAN_START and _roman_span_ahead(s, j + 1):
                out.append(" ")
                caps_word = False          # 대문자 단어표는 낱말 하나까지다
                j += 1
                continue
            # ⚠ 제32항은 로마자표~종료표 **사이**를 한 구간으로 보므로 원칙적으로는
            #   공백을 넘어 이어져야 한다(`MP4 Player`). 하지만 그렇게 못 한다:
            #   ① `decode`가 줄을 **공백 단위로 쪼개** 토큰마다 따로 디코드한다.
            #   ② 구간 경계를 못 믿는다 — ⠴는 닫는 따옴표, ⠲는 마침표와 같은 셀이라
            #      정답 도서에서 `⠴…⠲`를 찾으면 15,996건 중 절반이 **한글 오탐**이다
            #      (예 `⠴⠊⠉⠵⠀⠸⠎⠕⠢⠲` = 한글). 이걸 구간으로 보면 한글을 통째로 삼킨다.
            #   그래서 낱말 안에서만 정확히 하고 공백은 끊는다. 여는 부분은 제대로 나오고
            #   (`MP4`), 뒤 낱말은 한글로 오독되지만 그건 지금도 같다.
            break
        if c == _NUMBER_SIGN:                      # 수표 또는 영어 약자 ble (같은 점형)
            if j + 1 < n and s[j + 1] in _DIGIT_REV:
                # 제35항: 로마자 구간 안 숫자는 구간을 끊지 않는다(MP4 · A4 · Windows 10).
                # 여기서 끊으면 숫자 뒤 낱말이 로마자 문맥을 잃고 한글로 오독된다.
                # 명시적 로마자표 ⠴로 시작한 런에서만 이어 간다 — 종료표가 어디서 끝나는지
                # 알 수 있기 때문이다.
                if s[i] == _ROMAN_START and _roman_span_ahead(s, j + 2):
                    num, j = _decode_number(s, j)
                    out.append(num)
                    continue
                break                              # 뒤가 숫자 셀 → 수표(소비 안 함)
            out.append("ble")
            j += 1
            continue
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
        # 영어 약자(er=⠻ · in=⠔ · the=⠮ …)를 낱자보다 먼저 본다. 낱자로 읽으면
        # 여기서 런이 깨져 뒤 낱말이 통째로 한글로 오독된다.
        _word_start = j == i + 1 or s[j - 1] in (_SPACE_CELL, " ", _CAPITAL)
        # 단축형은 **로마자표가 낱말 앞에 온 런에서만** 본다(제29항). 낱말 중간의 ⠴는
        # 로마자표가 아니라 닫는 낫표·따옴표다(』=⠴⠆) — 거기서 단축형을 대면
        # `『대의각미록』에`가 `『대의각미록beneath`가 된다(실측 악화 10건 전부 이것).
        if _word_start and not caps_word and (i == 0 or s[i - 1] in (_SPACE_CELL, " ")):
            _end = j
            while _end < n and s[_end] not in (_SPACE_CELL, " ", _ROMAN_END):
                _end += 1
            _w = _ENG_WORD.get(s[j:_end]) if _end - j <= _ENG_WORD_MAX else None
            if _w is not None:
                out.append(_w.upper() if caps_word else _w)
                j = _end
                continue
        _g = _eng_group_at(s, j, _word_start)
        if _g is not None:
            txt, ln = _g
            out.append(txt.upper() if caps_word else txt)
            j += ln
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
    if not out:                    # 수표 뒤 일반 숫자 없음
        # 하단 숫자일 수 있다(항목 번호·로그 밑). `⠼⠆` = 2 (R2)
        if i + 1 < len(s) and s[i + 1] in _DROPPED_DIGIT_REV:
            k = i + 1
            got = []
            while k < len(s) and s[k] in _DROPPED_DIGIT_REV:
                got.append(_DROPPED_DIGIT_REV[s[k]])
                k += 1
            return "".join(got), k
        return "⟨⠼⟩", i + 1
    return "".join(out), j


def _decode_math_token(tok: str) -> str:
    """수식 토큰을 수학 의미로 디코드 — 구조·연산자 셀을 ^ _ √ × + 등으로 복원.

    수·로마자(변수)·그리스는 그대로 풀고, \\text 한글 등은 _COMBINED로 폴백한다.
    한글 음절과 겹치는 셀(⠘⠜⠌⠡)도 여기서는 수학 기호로 본다(토큰이 이미 수식 판정).
    """
    out: list[str] = []
    i, n = 0, len(tok)
    while i < n:
        c = tok[i]
        if c == _NUMBER_SIGN:                       # 수표 → 숫자
            txt, j = _decode_number(tok, i)
            out.append(txt)
            i = j
            continue
        matched = False                             # 다중 셀 수학 기호(≠·÷·그리스 등)
        for ln in range(min(_MATH_MAX, n - i), 1, -1):
            if tok[i:i + ln] in _MATH_REV_MULTI:
                out.append(_MATH_REV_MULTI[tok[i:i + ln]])
                i += ln
                matched = True
                break
        if matched:
            continue
        if c in _MATH_REV_SINGLE:                    # 단일 셀 수학 기호
            out.append(_MATH_REV_SINGLE[c])
            i += 1
            continue
        if c in _ALPHA_REV:                          # 변수(로마자)
            out.append(_ALPHA_REV[c])
            i += 1
            # 관행 제곱 약기: 변수 직후 ⠣ = ^2 (도서 관행, 정방향 book 모드와 대칭.
            #   한글 ㅏ와 충돌하므로 **로마자 직후**로 한정. 2026-07-19)
            if i < n and tok[i] == "⠣":
                out.append("^2")
                i += 1
            continue
        best = 0                                     # \text 한글·기호 폴백(긴 셀 우선)
        for ln in range(min(_MAX_CELLS, n - i), 0, -1):
            if tok[i:i + ln] in _COMBINED:
                best = ln
                break
        if best:
            out.append(_COMBINED[tok[i:i + best]])
            i += best
            continue
        out.append(f"⟨{ord(c):04X}⟩")
        i += 1
    return "".join(out)


def _classify_token(tok: str) -> str:
    """토큰을 MATH/NUM/OP/TEXT로 분류(인라인 수식 감지용).

    · MATH = 수표 ⠼와 수학 셀(첨자·근호·괄호·분수·곱)이 함께 있음 → 명백한 수식.
      (한글 본문 약자 ⠘/⠜는 수표가 없어 TEXT로 남음 — 오판 방지.)
    · OP   = 토큰 전체가 단독 연산자 셀(× + − = ÷).
    · NUM  = 수표만(평문 숫자).
    """
    if tok in _BARE_OPS:
        return "OP"
    if tok in _GREEK_TOKENS:
        return "GREEK"
    has_num = _NUMBER_SIGN in tok
    if has_num and (_MATH_SIGNAL_RE.search(tok) or any(p in tok for p in _MATH_PAREN_CELLS)):
        # ★ 단위 기호가 수식 신호를 품는다 (2026-08-09). 규정 제68항이 ㎡를 문자 그대로
        #   `m` 위첨자 `2`로 적으므로(`0m^#b` = ⠴⠍⠘⠼⠃) 토큰 안에 ⠘⠼가 들어 있고,
        #   그대로 두면 `2㎡`가 수식으로 분류돼 `2)m^2`로 풀린다.
        #   등록된 기호가 그 수식 신호를 **덮고 있으면** 수식이 아니라 기호다.
        #   (기호표에 없는 진짜 첨자 수식은 종전대로 MATH로 남는다.)
        if not _math_signal_is_inside_symbol(tok):
            return "MATH"
    return "NUM" if has_num else "TEXT"


def _math_signal_is_inside_symbol(tok: str) -> bool:
    """토큰의 수식 신호(⠘⠼ 등)가 등록된 기호 시퀀스 안에 들어 있는가."""
    covered: set[int] = set()
    i, n = 0, len(tok)
    while i < n:                                   # 긴 셀 우선으로 기호 구간을 표시
        for ln in range(min(_MAX_CELLS, n - i), 1, -1):
            if tok[i:i + ln] in _SYMBOL_REV:
                covered.update(range(i, i + ln))
                i += ln
                break
        else:
            i += 1
    if not covered:
        return False
    for m in _MATH_SIGNAL_RE.finditer(tok):        # 신호가 하나라도 기호 밖이면 진짜 수식
        if not (set(range(m.start(), m.end())) <= covered):
            return False
    for idx, ch in enumerate(tok):
        if ch in _MATH_PAREN_CELLS and idx not in covered:
            return False
    return True


def _resolve_math_context(classes: list[str]) -> list[bool]:
    """토큰별 수식 여부 확정. OP는 양옆이 수치/수식일 때만 연산자, NUM은 수식에 인접하면 수식."""
    res = [c == "MATH" for c in classes]
    n = len(classes)
    for i, c in enumerate(classes):                 # 단독 연산자: 양옆이 수치·수식·연산자
        if c == "OP":
            left = classes[i - 1] if i > 0 else None
            right = classes[i + 1] if i + 1 < n else None
            if left in ("MATH", "NUM", "OP") and right in ("MATH", "NUM", "OP"):
                res[i] = True
    changed = True                                  # 수식 문맥에 인접한 숫자·그리스 흡수
    while changed:
        changed = False
        for i, c in enumerate(classes):
            if c in ("NUM", "GREEK") and not res[i]:
                if (i > 0 and res[i - 1]) or (i + 1 < n and res[i + 1]):
                    res[i] = True
                    changed = True
    return res


# 수식 구역 판정 문턱 (R2, 2026-08-24). `math=True` 로 부른 요소라도 **한글이 이만큼 섞였으면**
# 자동 판별(토큰별)로 읽는다. 수식 요소에 설명 문장이 섞이면 그 한글이 수학 셀로 오독돼
# `개체군 밀도` 가 `ρ_nγ eo,iu` 로 깨지기 때문이다.
# ★ 문턱은 전수로 골랐다(formula 218건, 원문 대비 difflib 유사도):
#     math=True 단독 0.684 · math=False 단독 0.494 · 문턱 0.40 **0.699**
#   0.15~0.30 은 오히려 나빴다(0.592~0.671) — 순수 수식까지 자동 판별로 보내 깎인다.
#   ⚠ 눈으로 세 건만 보면 False 가 나아 보인다. 그 셋이 전부 한글 섞인 소수 계열이었다.
_MATH_KOR_RATIO = 0.40
# 이보다 짧은 수식은 통째로 수식으로 읽는다 — 설명 문장이 섞일 길이가 아니다.
_MATH_KOR_MIN_CELLS = 24


def decode(braille: str, *, math: bool = False) -> str:
    """점자 BRF 문자열 → 한국어 텍스트(근사). 줄바꿈은 보존.

    math=True면 전체를 수식 구역으로 보고 디코드한다(요소 type이 formula일 때 호출자가 지정).
    기본(False)은 공백 단위 토큰별로 수식/한글을 자동 판별한다(인라인 수식).
    """
    if math and len(braille) >= _MATH_KOR_MIN_CELLS:
        # 한글이 많이 섞인 수식 요소는 전체를 수식으로 보면 깨진다(R2). 자동 판별로 읽는다.
        # ⚠ **짧은 순수 수식은 제외한다.** `π`(⠨⠏)·`θ`(⠨⠹) 같은 두 셀짜리는 자동 판별이
        #   한글 음절로 읽어 비율이 100%가 되고, 그러면 `줘`·`적` 으로 깨진다
        #   (회귀 테스트 `test_역점역_정확도_floor[build-math]` 가 잡았다).
        loose = "\n".join(_decode_line_router(ln, False) for ln in braille.split("\n"))
        body = "".join(loose.split())
        if body and sum(1 for c in body if "가" <= c <= "힣") / len(body) >= _MATH_KOR_RATIO:
            return loose
    out_lines = []
    for line in braille.split("\n"):
        out_lines.append(_decode_line_router(line, math))
    return "\n".join(out_lines)


# ── 감쌈 붙임표 → 괄호 복원 (2026-08-06) ──────────────────────────────────
# 정방향은 도서 관행에 따라 괄호를 붙임표로 감싼다 — `(가)` → ⠤가⠤ (translator._paren_repl).
# 역점역이 그걸 모르면 `-가-`로 되돌려 원문과 어긋난다. 실측 400요소에서 이 한 가지가
# 틀린 자리 545건 중 170건(31%)으로 최다였다.
#
# ★ **토큰 전체가 `-X-`일 때만** 되돌린다. 줄 안 어디서나 `-X-`를 바꾸면 진짜 붙임표가
#   깨진다 — 실측: `고복지-저부담` → `고복지(저부담`. 승패 대조에서
#   토큰 규칙 = 개선 29 · 악화 **0**, 줄 규칙 = 개선 45 · 악화 4였다. 악화 0만 채택한다.
_WRAP_PAREN_RE = re.compile(r"(?<![^\s])-([^\s-]{1,20})-(?![^\s])")

# 토큰 안쪽(말 중간)에 박힌 감쌈 붙임표 — `생쥐-따-의`, `로 -가-가`. 토큰 규칙이 못 잡는다.
# 감싼 것이 **한 글자(또는 두 자리 수)일 때만** 본다 — `고복지-저부담`은 양쪽이 여러 글자라
# 안 걸린다. 여기서 걸러 낸 악화 2건(실측 900요소):
#   · `‘-더-’` 국어 어미 표기 → 앞이 따옴표면 안 건다
#   · `x-5-2` 수식 → 앞이 영숫자거나 뒤가 숫자면 안 건다
# 승패: 개선 33 · 악화 **0**.
_WRAP_PAREN_INNER_RE = re.compile(
    r"(?<![A-Za-z0-9‘’'\"“”])-([가-힣A-Za-z]|\d{1,2})-(?![0-9])")


def _restore_wrap_parens(text: str) -> str:
    """감쌈 붙임표를 괄호로 되돌린다 — 도서 관행 `(가)` → ⠤가⠤ (translator._paren_repl)."""
    return _WRAP_PAREN_INNER_RE.sub(r"(\1)", _WRAP_PAREN_RE.sub(r"(\1)", text))


# ── 소괄호 짝짓기 (2026-08-06) ────────────────────────────────────────────────
# 여는 ⠦⠄는 여는 큰따옴표와, 닫는 ⠠⠴는 **닫는 큰따옴표와 같은 셀**이다. 셀만 보면
# 못 가른다 — `(SNS)` 가 `(SNS”`로, `생쥐(가)` 가 `생쥩'가)`로 나왔다.
# 짝이 맞을 때만 괄호로 본다: 여는 셀과 닫는 셀 사이에 다른 괄호 셀이 없고 길이가 짧을 때.
# 자리표시자는 유니코드 비문자(실문서에 나올 수 없다) — 음절 해독을 통과시키려고 쓴다.
_PAREN_OPEN_MARK, _PAREN_CLOSE_MARK = "\ufdd2", "\ufdd3"
_PAREN_PAIR_RE = re.compile(r"⠦⠄((?:(?!⠦⠄|⠠⠴)[\u2800-\u28ff]){1,40})⠠⠴")


def _mark_paren_pairs(line: str) -> str:
    """짝이 맞는 소괄호 셀만 자리표시자로 바꾼다(따옴표와의 충돌 회피)."""
    return _PAREN_PAIR_RE.sub(
        lambda m: _PAREN_OPEN_MARK + m.group(1) + _PAREN_CLOSE_MARK, line)


def _build_eng_function() -> frozenset[str]:
    """영어 기능어 집합 — 로마자표 없는 영어 줄을 가려낼 때 마지막 증거로 쓴다."""
    from app.ai.braille import eng_braille as _E

    return frozenset(w.lower() for w in (*_E.WORDSIGNS, *_E.SHORT_FORMS)) | {"a", "i", "of", "and", "the", "is", "are", "was", "for", "on", "at", "with"}


_ENG_FUNCTION = _build_eng_function()


def _english_line(line: str) -> str | None:
    """줄 전체가 로마자표 없는 영어면 그 텍스트, 아니면 None (제29항 [다만]).

    제29항 [다만]은 **문단 전체가 로마자일 때 로마자표와 종료표를 생략할 수 있다**고
    한다. 우리 정방향도 그 관행을 따르므로 순수 영어 문단에는 단서 셀이 하나도 없다.
    단서가 없으면 한글로 읽혀 통째로 깨진다(`such tactics` → `어연 얽널다너`).

    ★ 가르는 방법은 **정방향으로 되짚는 것**이다. 영어로 읽어 본 뒤 그 텍스트를
      `eng_braille`로 다시 점자로 만들어 원래 셀과 **똑같을 때만** 영어로 본다.
      한글은 이 왕복을 통과하지 못하므로 오탐이 구조적으로 막힌다.
      실측(외국어 10쪽에서 뽑은 영문 261구절): 일치 145건 55.6%, 한글 오탐 0.
      나머지 44%는 약자가 여러 낱말에 겹쳐 되짚기가 안 맞는 것이라 종전대로 둔다.
    """
    from app.ai.braille import eng_braille as _E

    words = line.split(_SPACE_CELL)
    if len(words) < 2:               # 한 낱말은 단서가 너무 약하다(⠎=so ↔ 한글)
        return None
    out: list[str] = []
    for w in words:
        if not w:
            out.append("")
            continue
        got = _decode_roman_run(_ROMAN_START + w, 0)
        if got is None or got[1] != len(w) + 1:     # 낱말을 끝까지 못 읽으면 영어가 아니다
            return None
        out.append(got[0])
    text = " ".join(out)
    if _E.translate(text).replace(" ", _SPACE_CELL) != line:
        return None
    # 왕복만으로는 모자란다 — 한글 두 낱말이 뜻 없는 알파벳으로 되짚기까지 통과한다
    # (실측 오탐: `우주 그물로` → `dujya Oiu`, 글상자 테두리 → `forggg…`).
    # 영어 문장이라면 기능어가 적어도 하나는 있다(the·to·do·in·so…). 그걸 요구한다.
    return text if any(w.lower() in _ENG_FUNCTION for w in text.split()) else None


def _merge_roman_tokens(tokens: list[str], seps: list[str]) -> tuple[list[str], list[str]]:
    """로마자표로 열린 구간이 공백에서 끊기지 않게 토큰을 합친다(제32항).

    라우터가 줄을 공백으로 쪼개므로 `⠴such tactics⠲`의 둘째 낱말이 문맥을 잃고
    한글로 오독됐다(`such 얽널다너`). 합치는 조건은 **종료표 ⠲가 실제로 앞에 있을 때**
    뿐이다 — `_roman_span_ahead`가 그 증거를 요구한다. 증거가 없으면 합치지 않는다.
    """
    out_t: list[str] = []
    out_s: list[str] = []
    i = 0
    while i < len(tokens):
        merged = tokens[i]
        # 로마자표는 **낱말 앞**에 온다(제29항). 낱말 중간의 ⠴는 닫는 낫표·따옴표다
        # (』=⠴⠆, ’=⠴⠄) — 그걸 구간 시작으로 보면 한글 문단을 통째로 삼킨다.
        # 실측: 이 조건이 없을 때 32,036요소에서 악화 988건이었다.
        st = 0 if merged.startswith(_ROMAN_START) else -1
        while (st >= 0 and _ROMAN_END not in merged[st:] and i < len(seps)
               and _roman_span_ahead("⠀".join(tokens[i + 1:]), 0)):
            merged += seps[i] + tokens[i + 1]
            i += 1
        out_t.append(merged)
        if i < len(seps):
            out_s.append(seps[i])
        i += 1
    return out_t, out_s


# 제17항 [다만] — 숫자와 혼동되는 'ㄴ ㄷ ㅁ ㅋ ㅌ ㅍ ㅎ'의 첫소리 글자와 '운'의 약자는
# 숫자 뒤에 **붙어 나오더라도 띄어 쓴다**(규정 예시 `1년` = ⠼⠁ ⠉⠡). 그래서 점자의 그 한 칸은
# 원문에 없던 것이다 — 되돌리지 않으면 `1년`이 `1 년`으로 나온다.
# 코퍼스 실측: 이 자리 4,995건 중 붙여 쓴 원문이 3,786건(75.8%)이라 붙이는 쪽을 택한다.
_NUM_CHO = frozenset((2, 3, 6, 15, 16, 17, 18))     # ㄴ ㄷ ㅁ ㅋ ㅌ ㅍ ㅎ


def _join_num_hangul(text: str) -> str:
    """숫자와 한글 사이의 **한 칸**을 되붙인다 (제17항 [다만])."""
    def _repl(m: "re.Match[str]") -> str:
        c = m.group(2)
        if c == "운" or (ord(c) - 0xAC00) // 588 in _NUM_CHO:
            return m.group(1) + c
        return m.group(0)

    # 앞이 로마자면 안 붙인다 — `MP3 파일`·`V1 단계`는 로마자+숫자가 한 덩이고
    # 그 뒤 한 칸은 [다만]의 구분 칸이 아니라 진짜 낱말 사이 공백이다.
    return re.sub(r"(?<![A-Za-z])(\d) ([가-힣])", _repl, text)


# 글상자 테두리 줄 — 시작캡 + 같은 채움 셀 반복 + 끝캡 (layout_braille._BOX_LEVELS).
# 글자가 아니라 도형이라 음절로 읽으면 `옹운운운운…옹`이 나온다. 실물 검수에서 이게
# 본문 사이에 섞여 나와 읽기 어려웠다. 줄 **전체**가 이 꼴일 때만 표시로 바꾼다 —
# ⠿는 약자 '옹'이기도 해서 줄 일부만 보고 판단하면 정상 한글을 깬다.
# 제목이 테두리 안에 들어가는 꼴도 있다(BBPG — 위 테두리 중간에 제목). 제목은 실제
# 내용이므로 살려서 【글상자 제목】으로 낸다.
# ⚠ 줄 **전체**가 테두리일 때만 잡으면 실물을 놓친다. 실제 데이터는 테두리 뒤에 줄바꿈
#   없이 본문이 같은 문자열로 이어진다(`⠿⠛…⠿⠀⠿⠁⠲⠀⠦⠄⠫…`). 그래서 **테두리 구간만**
#   찾아 바꾸고 나머지는 그대로 읽는다. 채움 셀을 4칸 이상 요구하므로 약자 '옹'(⠿ 한 칸)과
#   `⠿⠁⠲`(ㄱ.) 같은 한글은 안 걸린다.
_BOX_BORDER_RE = re.compile(
    r"[⠿⠖⠓](⠛|⠶|⠒|⠐)\1{3,}(?:[⠀ ](.+?)[⠀ ]\1{3,})?[⠿⠲⠚]")


def _decode_line_router(line: str, math: bool) -> str:
    """줄을 공백 단위로 나눠 수식 토큰은 수학 디코더로, 나머지는 한글 디코더로 라우팅."""
    if not line:
        return ""
    if _BOX_BORDER_RE.search(line):     # 글상자 테두리 — 글자가 아니라 도형이다
        out, last = [], 0
        for m in _BOX_BORDER_RE.finditer(line):
            if m.start() > last:
                out.append(_decode_line_router(line[last:m.start()], math))
            title = m.group(2)
            out.append(f"【글상자 {_decode_line(title)}】" if title else "【글상자】")
            last = m.end()
        if last < len(line):
            out.append(_decode_line_router(line[last:], math))
        return "".join(out)
    if not math:                     # 수식 줄에 영어 판정을 대면 안 된다 — `a √ b`가
        eng = _english_line(line)    # `a ar b`로 뒤집힌다(⠜=√ ↔ 영어 약자 ar)
        if eng is not None:          # 로마자표 없는 순수 영어 줄 (제29항 [다만])
            return eng
    line = _mark_paren_pairs(line)
    parts = re.split(r"([⠀ ]+)", line)              # 공백 런을 분리자로 보존
    tokens, seps = _merge_roman_tokens(parts[0::2], parts[1::2])
    if math:
        is_math = [True] * len(tokens)
    else:
        is_math = _resolve_math_context([_classify_token(t) for t in tokens])
    pieces = []
    for idx, tok in enumerate(tokens):
        if tok:
            pieces.append(_decode_math_token(tok) if is_math[idx] else _decode_line(tok))
        if idx < len(seps):
            pieces.append(" " * len(seps[idx]))
    return _join_num_hangul(_restore_wrap_parens("".join(pieces)))


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
        # 대문자 로마자 처리는 폐기(2026-07-18): ⠠는 한글 음절 구성요소(수=⠠⠍)이기도 해
        # ⠠+알파를 대문자로 보면 정상 한글을 깬다(국수→국M, 따님→I님). roundtrip 회귀.
        # 로마자 대문자는 ⠴…⠲ 로마자 런 안에서만 처리(맥락 있음).
        # 동그라미 숫자·문자·낱자(제64항) — 수표/온표보다 먼저(①=⠼⠂ 가 평문 숫자로,
        # ㉠=⠿⠁ 이 ∞로 오인되지 않게). 긴 셀 우선.
        _sp = 0
        for ln in range(min(_SPECIAL_MAX, n - i), 0, -1):
            if s[i:i + ln] in _SPECIAL_REV:
                _sp = ln
                break
        if _sp:
            out.append(_SPECIAL_REV[s[i:i + _sp]])
            i += _sp
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

        # ★ 로마자표 ⠴로 시작하는 기호는 로마자 런과 셀이 겹친다 (2026-08-06).
        #   `%`=⠴⠏ 인데 로마자표+p 도 ⠴⠏라, `pH`(⠴⠏⠠⠓⠲)가 `%`+미지셀로 깨졌다.
        #   **긴 쪽이 이긴다** — 로마자로 읽어서 더 많은 셀을 소비하면 그쪽이 맞다.
        #   길이가 같으면 기호가 이긴다: ℃(⠴⠙⠠⠉)·㎏(⠴⠅⠛⠲)은 로마자로 읽어도 같은
        #   4셀이므로 등록된 단위 기호로 남는다.
        if ch == _ROMAN_START and best_ln >= 2:
            _r = _decode_roman_run(s, i)
            if _r is not None and _r[1] - i > best_ln:
                out.append(_r[0])
                i = _r[1]
                continue

        if best_ln >= 2:
            seg = s[i:i + best_ln]
            # 마침표가 음절 뒤에 붙어 다른 음절로 오인된 경우 분리(다.=닾 → 다 + .).
            # ?·!(⠦·⠖)은 받침과 충돌(같=⠫⠦)하므로 **어말일 때만** 분리(요?=⠬⠦ → 요 + ?).
            # ★기호로 등록된 시퀀스(≥=⠲⠲, ⊃=⠐⠲, ㎏=…⠲ 등)는 분리하지 않는다(2026-07-19).
            if seg[-1] == "⠲" and seg in _SYMBOL_REV:
                out.append(_SYMBOL_REV[seg])
            elif (seg[-1] == "⠲" and seg[:-1] in _COMBINED
                  and _COMBINED.get(seg) not in _PIEUP_FINAL):
                # ⠲는 마침표이자 **받침 ㅍ**이라(높=⠉⠥⠲) 무조건 분리하면 받침 ㅍ이 든 말이
                # 전부 깨진다(높다→'노.다' · 앞으로→'아.으로'). 위치로 가르면 닫는 따옴표
                # 앞에서 또 틀리므로(`나타난다.’`→`나타난닾’`) **실제로 쓰이는 받침 ㅍ 음절**
                # 목록으로 가른다 — 닫힌 집합이라 안전하다. 승패: 개선 58 · 악화 0.
                out.append(_COMBINED[seg[:-1]])
                out.append(".")
            elif (seg in _SYLLABLE_REV and seg[-1] in _SENT_END
                  and seg[:-1] in _COMBINED and _final(i + best_ln)):
                # 한글 음절로 오인 흡수된 경우만 분리(요?=⠬⠦) — 기호(「=⠐⠦)는 그대로 둔다.
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
        # 어말 마침표 ⠲ — ∋ 기호와 같은 점형이라, 앞에 텍스트가 있고 어말(끝/공백 앞)일
        # 때만 마침표로 본다(곳.=…⠲ → 곳 + .). 단독 ⠲(앞이 비었거나 공백)는 기호(∋)로 둔다.
        if ch == _ROMAN_END and out and out[-1] != " " and _final(i + 1):
            out.append(".")
            i += 1
            continue
        # 단일 셀 매칭(따옴표·쉼표 등)
        if best_ln == 1:
            out.append(_COMBINED[ch])
            i += 1
            continue
        # 한글 표에 없으면 **수학 역표를 한 번 더 본다**. 인라인 수식으로 분류되지 못한
        # 자리에서 연산기호가 그대로 샜다(실측 13,121건: ⠢=+ 가 `8⟨2822⟩13` 꼴).
        # 긴 것부터 맞추고, 그래도 없으면 코드포인트로 정직하게 남긴다.
        _m = 0
        for _ln in range(min(_MATH_MAX, n - i), 1, -1):
            if s[i:i + _ln] in _MATH_REV_MULTI:
                _m = _ln
                break
        if _m:
            out.append(_MATH_REV_MULTI[s[i:i + _m]])
            i += _m
            continue
        if ch in _MATH_REV_SINGLE:
            out.append(_MATH_REV_SINGLE[ch])
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

    단, 나·다·마·바·자·카·타·파·하 등은 **약자**라 단독으론 초성만(다=⠊)이지만 단어
    속에선 full형(다=⠊⠣)으로 나온다. 단독형만 담으면 단어 속 ⠊⠣를 다+아로 오분해하므로,
    단독형과 '단어 속(full)' 형태를 **둘 다** 등록한다(디코더는 긴 셀 우선이라 full형 선택).
    충돌(서로 다른 음절이 같은 셀)은 먼저 나온 음절 유지.
    """
    from braillify import translate_to_unicode as _fwd
    suffix = _fwd("음")    # 뒤에 음절을 붙이면 앞 음절이 약자 없이 full형으로 나온다
    rev: dict[str, str] = {}
    for code in range(0xAC00, 0xD7A4):           # 가(AC00) ~ 힣(D7A3)
        syl = chr(code)
        solo = _fwd(syl)
        # 단어 속(full) 형태: syl+'음' 점역에서 '음' 셀을 떼어낸 앞부분
        ctx = _fwd(syl + "음")
        inword = ctx[: -len(suffix)] if suffix and ctx.endswith(suffix) else ""
        # full형(긴 셀)을 먼저 등록해 긴-셀 우선 매칭에서 선택되게 한다.
        for cells in (inword, solo):
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
    math = False
    if argv and argv[0] == "--math":              # 수식 구역으로 디코드
        math = True
        argv = argv[1:]
    if argv and argv[0] == "--file":
        text = Path(argv[1]).read_text(encoding="utf-8")
    else:
        text = " ".join(argv)
    print(decode(text, math=math))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
