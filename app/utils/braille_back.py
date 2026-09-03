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
# 옛한글 점형표(규정 제19~25항)는 정방향이 정본이다 — 역방향은 그 표를 뒤집어 쓴다.
from app.ai.braille.translator import (
    _CHOSEONG as _T_CHO, _JONGSEONG as _T_JONG,
    _OLD_CHO as _T_OLD_CHO, _OLD_JUNG as _T_OLD_JUNG,
)

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
_PIEUP_FINAL = frozenset("갚겊깊높늪덮릎섶숲싶앞엎옆잎읊짚")
# 그중 **낱말 끝에 못 서는 어간**(갚다·깊다·싶다·엎다·짚다·읊다 / 땔섶). 어말·닫는 부호
# 앞이면 받침 ㅍ이 아니라 **온점**이다 — `있어.`→`있엎` · `밝혀야지.`→`밝혀야짚` 이 이것.
# 근거는 재추출 묵자 1,362쪽 실측(어말·닫는 부호 앞 자리에서만 셌다):
#   갚 0회 : `가.` 46   ·   깊 0 : `기.` 5   ·   섶 0 : `서.` 9   ·   싶 0 : `시.` 30
#   엎 0 : `어.` 174    ·   짚 1 : `지.` 46  ·   읊 0 : `을.` 2
# 반대로 어말에 실제로 서는 것들은 뺐다 — 앞 24 · 릎 12 · 잎 8 · 숲 7 · 옆 4 · 높 3.
# ★ `읊` 은 반대 방향 오류였다. 목록에 없어 `읊고`가 `을.고`로 깨졌다(어중 13회).
#   여기 같이 넣어 어중에서는 `읊`, 어말에서는 `을.` 로 갈리게 한다.
_PIEUP_STEM_ONLY = frozenset("갚깊섶싶엎읊짚")
# 받침 ㅋ 음절 — 국어에 `엌`(부엌)·`녘`(동녘) 둘뿐이라 나머지는 전부 느낌표 ⠖ 다.
_KIEUK_FINAL = frozenset("엌녘")

# 받침에 ㅎ이 든 음절(ㅎ·ㄶ·ㅀ) — ⠴가 **닫는 큰따옴표**인지 받침의 ㅎ인지 가른다
# (좋=⠨⠥⠴ · 끓 vs 조+”). 받침 ㅍ(_PIEUP_FINAL)과 같은 방식이고 근거도 같다.
# 목록은 코퍼스 묵자 원문 실측에서 뽑았다 — 재추출한 1,361쪽에 실제로 나온 전수(31종·
# 4,167회)에서 1회짜리 OCR 잡음 `셓`·`솧`만 뺐다.
# ★ 이걸 안 가르면 정답 도서의 가계도가 통째로 깨진다 — `남자”` 가 `남잫` 이 된다.
#   시각자료 설명 실측에서 `남잫` 135회 · `여잫` 121회 · `여잫언` 31회가 이 한 가지였다.
# ⚠ 한계: 음절 자체가 멀쩡한 것(`찮`·`않`)은 못 가른다. `만찬”` 은 `만찮` 으로 남는다.
#   받침 ㅍ 목록과 같은 한계이고, 위치로 가르면 더 크게 틀린다(그 함수 주석 참조).
_HIEUT_FINAL = frozenset(
    "갛겋곯꿇끊끓낳넣놓닳닿떻뚫랗렇많맣빻슳싫쌓않앓얗옳잃잖좋찮")

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
# ★ 수식 역맵의 빈칸 채우기(2026-09-03). 정답쌍 역방향에서 이것들이 한글·미해독으로
#   샜다 — `|x|` → `열옥열` · `‖x‖` → `열열옥열열`.
#   ⠳ 는 한글 `열` 과 같은 셀이라 수식 경로에서만 잡힌다.
#   ★ 정규부분군 ⠸⠜=▷ · ⠸⠣=◁ 는 **뺐다**(실측). 코퍼스 1,180쪽에서 ▷ 가 5쪽에 떴는데
#   묵자 정답에는 0건이고, 그중 넷이 영어책의 이미 깨진 자리였다. ⠸ 는 도형 접두
#   (⠸+도형셀xN+⠇)라 본문에 흔하다 — 근거 없이 두면 오검출만 는다.
_MATH_REV_SINGLE["⠳"] = "|"                       # 절댓값 (제21항)
_MATH_REV_MULTI.update({
    "⠳⠳": "‖",        # 노름 (제28항) — 단일 ⠳ 보다 먼저 잡히게 다중 셀에 둔다
    "⠈⠔⠒⠒": "≅",     # 물결 아래 등호 (제32항)
    "⠈⠔⠒": "≃",      # (제31항)
    "⠈⠔⠈⠔⠒": "≊",   # (제30항)
    "⠨⠳": "∤",        # 나누어떨어지지 않음 (제27항)
})

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
# 삼각함수(규정 제47항) — sin=⠖⠎ · cos=⠖⠉ · tan=⠖⠞ · sec=⠖⠤ · csc=⠖⠣ · cot=⠖⠳.
# 역맵이 통째로 없어서 `tan x` 가 `∈얼옥` 으로 깨졌다(규정 제11항 예시에서 바로 재현).
# ★ **정방향 표(kor_math_rules._TRIG)를 뒤집어 만든다** — 손으로 적으면 어긋난다.
def _build_trig_rev() -> dict[str, str]:
    try:
        from app.ai.braille.kor_math_rules import _TRIG
    except Exception:                                     # noqa: BLE001
        return {}
    # 긴 이름이 먼저 이기도록 셀이 긴 것부터 넣는다(arcsin 이 sin 보다 앞).
    return {cells: name for name, cells in
            sorted(_TRIG.items(), key=lambda kv: -len(kv[1]))}


_TRIG_CELLS = tuple(_build_trig_rev())
_MATH_REV_MULTI.update(_build_trig_rev())

_MATH_REV_SINGLE.update({
    # ★ 단독 ⠸ 는 log 가 아니다(2026-09-03 정정). 규정 제46항은 로그를 **두 칸**으로 적는다 —
    #   밑이 숫자면 `⠸⠠`, 문자·괄호면 `⠸⠰`(예 `_,5#b` = log₅2). 둘 다 위 MULTI 에 있다.
    #   홑 ⠸ 를 log 로 두니 지시부호 자리마다 터져 **코퍼스 전수에서 105,453자**가 샜다
    #   (강 제목 `⠸⠦…⠴⠇` 가 `log"1l` 로 나온 것도 이것). 묵자 실측 log 795회 대 그 손해다.
    #   짝이 없는 홑 ⠸ 는 정직하게 미지셀로 남긴다.
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
_MATH_PAREN_OPEN = "⠷"                                   # 분류 신호는 **여는 쪽만** 본다
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
# ★ book 모드에서는 **규정 판본(⠨+자음)을 역맵에서 뺀다.** 정방향이 ⠈ 판본만 내므로
#   ⠨ 판본은 읽을 일이 없는데, 그 셀들이 전부 흔한 한글 음절이다(⠨⠍=자우 · ⠨⠹=자억
#   · ⠨⠝=자에 …). 실측(전 코퍼스 1,131쪽): ⠨⠍ **10,183건** · ⠨⠹ 8,539 · ⠨⠝ 8,283
#   출현인데 그 쪽 묵자에 해당 그리스 문자가 있는 것은 **전부 0건**이다.
#   대문자(⠠⠨x)는 앞서 A/B 로 기각된 이력이 있어(쪽 1,555회 파괴) 손대지 않는다.
# ★ **수식 경로(_MATH_REV_MULTI)에는 남긴다.** 수식 토큰 안에서는 ⠨ 판본이 실제로
#   쓰이고, 왕복 데이터셋도 그걸 지킨다. 아래에서 **본문 경로(_SYMBOL_REV/_COMBINED)에서만**
#   뺀다 — 본문에서 그리스로 읽히는 것이 전부 오검출이기 때문이다.

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
    # 겸용 점형은 **실측 우세 쪽**으로 편다. 표 등록 순서가 정하게 두면 조용히 뒤집힌다.
    #   규정 제60항 — 별표(*)와 참고표(※)는 **같은 점형** ⠐⠔ 로 적는다(구별할 때만 ※=⠸⠔).
    #   재추출 묵자 1,361쪽 실측: `*` 630회 : `※` 105회 → 별표로 편다.
    rev["⠐⠔"] = "*"
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


def _special_at(s: str, i: int) -> tuple[str, int] | None:
    """s[i] 에서 동그라미 숫자·낱자(제64항)가 시작하면 (글자, 다음 위치).

    ⚠ ⠼+아랫셀은 **로그 밑**(「수학 점자」 제46항 log₂ = ⠸⠼⠆)과 셀이 같다. 앞 칸이
      ⠸ 면 로그라 펴지 않는다 — 이 가드가 없으면 `log ②` 가 나간다.
    """
    if s[i] == _NUMBER_SIGN and i and s[i - 1] == "⠸":
        return None
    for ln in range(min(_SPECIAL_MAX, len(s) - i), 0, -1):
        if s[i:i + ln] in _SPECIAL_REV:
            return _SPECIAL_REV[s[i:i + ln]], i + ln
    return None


# ── 옛한글 역조립 (「한국 점자 규정」 제19~25항) ─────────────────────────────
# 정방향 translator._old_syllable_cells 의 역이다 — 점형 표를 그쪽에서 그대로 들여와
# 두 방향이 갈라지지 않게 한다.
#
# ★ 어디까지 펴나 — **묵자 실측이 있는 넉 자만**(2026-09-04). 옛 글자표 ⠐ 는 쉼표·
#   점 곱셈기호·초성 ㄹ 과 같은 셀이라 표를 통째로 뒤집어 쓰면 본문을 먹는다.
#   재추출 묵자 1,180쪽 대조(그 셀이 나온 점자 쪽 / 그 쪽 묵자에 그 옛 글자가 있는 쪽):
#   | 자모 | 셀 | 점자쪽 | 묵자에도 | 판정 |
#   |---|---|---|---|---|
#   | ㆍ ᆞ | ⠐⠼   |  28 | **23** | 넣는다 |
#   | ㆎ ᆡ | ⠐⠼⠗  |  16 |    7   | 넣는다(아래아의 긴 꼴) |
#   | ㅸ ᄫ | ⠐⠘⠶ |   7 | **6**  | 넣는다 |
#   | ㅿ ᅀ | ⠐⠨   |  15 | **10** | 넣는다 |
#   | ㆁ ᅌ | ⠐⠙   |  26 |    1   | **뺀다** — 115건이 쉼표·약자다 |
#   | ㆆ ᅙ | ⠐⠚   |   3 |    0   | **뺀다** |
#   | 무음 ㅇ 받침 | ⠐⠶ | 238 | **0** | **뺀다** — 688건 전부 오검출 |
#   | 방점 거성 ⠸⠂ · 상성 ⠸⠅ | | 2 · 1 | | **뺀다** — 아래 참조 |
#   | ㆇ~ㆌ(⠸⠬⠜ 등) |  |  0 |  0 | **뺀다** — 전 코퍼스 0건 |
# ⚠ 아래아 ⠐⠼ 는 **수식 쉼표 + 다음 수의 수표**와 셀이 같다(`4, 1` = ⠼⠙⠐⠼⠁).
#   전 코퍼스 18,892쪽에 ⠐⠼ 862건 중 **395건이 그 수(120쪽)** 다 — 앞이 수 런이면 뺀다.
# ⚠ 방점(제27항 거성 ⠸⠂ · 상성 ⠸⠅)은 **넣으면 안 된다.** ⠸⠂ 는 전 코퍼스 5,474건인데
#   67.9% 가 바로 뒤에 로마자 셀 3개 이상이 붙는다 — `⠸⠂⠎⠁⠙`(sad)·`⠸⠂⠋⠗⠑⠑`(free) 처럼
#   **UEB 밑줄 낱말표**이지 방점이 아니다. 상성 ⠸⠅ 는 전 코퍼스 7건뿐이다.
# ⚠ 한계: 옛 받침(ᇫ=⠐⠅ 등)과 겹받침은 안 편다. 실측이 1,180쪽에 1쪽뿐이고, 겹받침
#   두 칸을 먹으면 닫는 따옴표(⠴⠄)를 삼킨다. 음절 역맵으로 푸는 자리(옛 자음자 + 현대
#   모음)는 탐욕 매칭이라 드물게 닫는 따옴표를 받침 ㅎ 으로 먹는다(전 코퍼스 282줄에 1건).
_OLD_CHO_REV = {_T_OLD_CHO[j]: j for j in ("ᄫ", "ᅀ")}
_OLD_JUNG_REV = {_T_OLD_JUNG[j]: j for j in ("ᆞ", "ᆡ")}
_OLD_COMPAT = {"ᄫ": "ㅸ", "ᅀ": "ㅿ", "ᆞ": "ㆍ", "ᆡ": "ㆎ"}   # 낱자로 홀로 쓰일 때
_CHO_CELL_REV = {c: chr(0x1100 + i) for i, c in enumerate(_T_CHO) if c}
# ★ 옛한글에서는 첫소리 ㅇ 을 ⠛ 로 적는 관행이 있다 — 규정 제21항 쌍이응 ㆀ = ⠐⠛⠛ 이
#   ⠛=ㅇ 임을 보이고, 정답 도서가 `‘ᄋᆞᆯ’`(⠠⠦⠛⠐⠼⠂⠴⠄)·`‘ᄋᆡ’`·`‘ᄋᆞ로’` 로 그렇게 적는다.
#   (규정 제25항 예시 `애매한`=⠐⠼⠗⠑⠐⠼⠗⠚⠐⠼⠒ 은 ⠛ 없이 적어 규정↔관행이 갈린다 —
#    역방향은 둘 다 읽어야 하므로 둘 다 받는다.) 전 코퍼스 ⠛+아래아 21건.
_CHO_CELL_REV["⠛"] = "ᄋ"
# 초성 없는 아래아(ᄋᆞ)를 펴도 되는 자리 — **낱말 경계뿐이다.**
# ⠐⠼ 는 `쉼표/수식 쉼표 + 다음 수의 수표`와 셀이 같아서(각주 번호 `,41` · 수식 `”,2=`)
# 음절 한복판에서 펴면 수학·문학 책 본문이 깨진다. 전 코퍼스 실측: 초성 없는 자리 221건 중
# 경계 밖 110건이 전부 수식·각주였고, 경계 안 49건은 전부 중세국어 인용이다.
_ARAEA_BOUND = frozenset("⠀ \n⠦⠤")
_JONG_CELL_REV = {c: chr(0x11A7 + i) for i, c in enumerate(_T_JONG) if len(c) == 1}
_ARAEA = _T_OLD_JUNG["ᆞ"]
_DIGIT_CELLS = frozenset("⠁⠃⠉⠙⠑⠋⠛⠓⠊⠚")
_SYL_MAX = max((len(k) for k in _SYLLABLE_REV), default=0)
_JAMO_V0, _JAMO_T0 = 0x1161, 0x11A7


def _in_number_run(s: str, i: int) -> bool:
    """s[i] 앞이 수표+숫자 런인가 — 그러면 이 ⠐⠼ 는 아래아가 아니라 `쉼표+수표`다."""
    j = i - 1
    while j >= 0 and s[j] in _DIGIT_CELLS:
        j -= 1
    return 0 <= j < i - 1 and s[j] == _NUMBER_SIGN


def _old_jung_at(s: str, i: int) -> tuple[str, int] | None:
    if s[i:i + 2] == _ARAEA and _in_number_run(s, i):
        return None
    for ln in (3, 2):
        j = _OLD_JUNG_REV.get(s[i:i + ln])
        if j:
            return j, i + ln
    return None


def _old_cho_at(s: str, i: int) -> tuple[str, int] | None:
    for ln in (3, 2):
        c = _OLD_CHO_REV.get(s[i:i + ln])
        if c:
            return c, i + ln
    return None


def _old_tail(s: str, cho: str, at: int) -> tuple[str, int] | None:
    """초성이 정해진 뒤 — 중성(+받침)을 붙여 첫가끝 음절을 만든다."""
    jung = _old_jung_at(s, at)
    if jung:
        at = jung[1]
        t = _JONG_CELL_REV.get(s[at:at + 1])
        if t and not (s[at] == "⠴" and s[at + 1:at + 2] == "⠄"):   # 닫는 작은따옴표
            return cho + jung[0] + t, at + 1
        return cho + jung[0], at
    if cho == "ᄋ":                       # 초성이 없는데 중성도 없으면 옛한글이 아니다
        return None
    # 옛 자음자 + 현대 모음 — 정방향이 약자로 적으므로(ᄫᅳᆫ = ⠐⠘⠶⠵) 음절 역맵으로 푼다.
    for ln in range(min(_SYL_MAX, len(s) - at), 0, -1):
        syl = _SYLLABLE_REV.get(s[at:at + ln])
        if syl and len(syl) == 1 and 0xAC00 <= ord(syl) <= 0xD7A3:
            code = ord(syl) - 0xAC00
            if code // 588 != 11:        # 정방향이 붙인 ㅇ 초성이 아니면 남의 음절이다
                break
            jong = code % 28
            return (cho + chr(_JAMO_V0 + (code % 588) // 28)
                    + (chr(_JAMO_T0 + jong) if jong else ""), at + ln)
    return None


def _old_hangul_at(s: str, i: int) -> tuple[str, int] | None:
    """s[i] 에서 옛한글이 시작하면 (첫가끝 문자열, 다음 위치).

    옛 글자표 ⠐ 가 쉼표·초성 ㄹ 과 같은 셀이라 **양쪽에 조건을 건다** — 옛 자음자는
    뒤에 모음이 붙어야 하고, 아래아는 수 런 안이면 안 되며, 초성 없는 아래아는
    낱말 경계에서만 편다.
    """
    if s[i] == "⠿":                                  # 자모 단독 표시(제9항 온표) + 옛 글자
        got = _old_cho_at(s, i + 1) or _old_jung_at(s, i + 1)
        return (_OLD_COMPAT[got[0]], got[1]) if got else None
    cho = _old_cho_at(s, i)
    if cho:
        return _old_tail(s, cho[0], cho[1])
    for ln in (2, 1):                                # 현대 초성 + 옛 모음자
        c = _CHO_CELL_REV.get(s[i:i + ln])
        if c and _old_jung_at(s, i + ln):
            return _old_tail(s, c, i + ln)
    if _old_jung_at(s, i) and (i == 0 or s[i - 1] in _ARAEA_BOUND):
        return _old_tail(s, "ᄋ", i)                 # 초성 없는 ᄋᆞ — 낱말 경계에서만
    return None

# 모음 낱자(제7항) — 온표 ⠿ 뒤 모음. **_SPECIAL_REV 에 넣으면 안 된다**: ⠿는 약자 '옹'
# 이기도 해서 무조건 펴면 `옹알이`(⠿⠣⠂⠕)가 `ㅏㄹ이`로 깨진다. 자음 낱자(㉠=⠿⠁)는
# 뒤 셀이 음절 첫소리와 안 겹쳐 무조건 펴도 되지만, 모음은 겹친다.
# 그래서 **양옆이 경계일 때만** 편다. 전 코퍼스 실측(1,131쪽): 경계로 둘러싸인 출현
# 227건 중 224건이 묵자에 그 모음 낱자가 있고 '옹X'는 **0건**이다(나머지 3건은 짝 미확인).
# 붙어 나오는 6,988건은 손대지 않는다.
_VOWEL_JAMO_REV = {
    "⠿⠣": "ㅏ", "⠿⠗": "ㅐ", "⠿⠜": "ㅑ", "⠿⠜⠗": "ㅒ", "⠿⠎": "ㅓ", "⠿⠝": "ㅔ",
    "⠿⠱": "ㅕ", "⠿⠌": "ㅖ", "⠿⠥": "ㅗ", "⠿⠧": "ㅘ", "⠿⠧⠗": "ㅙ", "⠿⠽": "ㅚ",
    "⠿⠬": "ㅛ", "⠿⠍": "ㅜ", "⠿⠏": "ㅝ", "⠿⠏⠗": "ㅞ", "⠿⠍⠗": "ㅟ", "⠿⠩": "ㅠ",
    "⠿⠪": "ㅡ", "⠿⠺": "ㅢ", "⠿⠕": "ㅣ",
}
_VOWEL_JAMO_MAX = max(len(k) for k in _VOWEL_JAMO_REV)
# 낱자 양옆에 올 수 있는 경계 — 칸·줄끝과, 낱자를 나열할 때 쓰는 문장부호들.
_JAMO_BOUND = frozenset("⠀ \n⠐⠲⠆⠦⠴⠄⠶⠔⠒")
# 통합 역맵(약어 + 음절 + 기호). 긴 셀 우선 매칭을 위해 최대 길이 기록.
if _LC_GREEK_REV != "⠨":
    for _k in [k for k, v in _SYMBOL_REV.items()
               if len(k) == 2 and k[0] == "⠨" and v in "αβγδεζηθικλμνξοπρστυφχψω"]:
        _SYMBOL_REV.pop(_k, None)
# ★ 본문에서 한글·문장부호를 먹는 기호 열 종을 **본문 경로에서 뺀다**(2026-09-03).
#   ⇄(⠪⠶⠕)·그리스 규정 판본과 같은 계열이다 — 정방향은 그대로 두고 역방향 본문만.
#   실측(전 코퍼스 1,180쪽, LaTeX·ASCII 대체꼴까지 찾아 정밀화한 값):
#   | 기호 | 셀 | 출력 쪽 | 그 쪽 묵자에 그 기호 | 빼면 무엇이 되나 |
#   |---|---|---|---|---|
#   | ∋ | ⠲ | 171 | **0** | 온점 `.` |
#   | ∌ | ⠨⠲ | 145 | **0** | 음절 |
#   | ∘ | ⠸⠴ | 115 | **0** | 도형 틀 · 미지셀 |
#   | ∈ | ⠖ | 97 | **0**(대체꼴 `\in` 6쪽) | 느낌표 `!` |
#   | ⊕ | ⠸⠢ | 74 | **0** | 도형 틀 |
#   | ≡ | ⠶⠶ | 51 | **0** | 도형 틀(⠸⠶⠶⠇) |
#   | ↓ | ⠘⠒⠕ | 34 | **0** | 음절 |
#   | © | ⠘⠉ | 31 | **0** | 음절('바' 계열) |
#   | Å | ⠴⠡ | 25 | **0** | 음절 |
#   | ◎ | ⠸⠴⠴ | 94 | — | 도형 틀(⠸⠴⠴⠇=○○) |
#   ι(⠈⠊, 131쪽)도 같은 자리다 — '자들'과 겹친다.
#   ★ **수식 경로(_MATH_REV_MULTI)에는 남긴다.** ∘·⊕·≡·ι 는 수식 토큰 안에서 쓰이고
#     왕복 데이터셋이 그걸 지킨다. 여기서 빼는 것은 본문 경로뿐이다.
#   ⚠ 1차 측정은 절반이 오보였다 — 묵자 정답이 수식을 LaTeX 로 담아(`\leq`·`\sqrt`)
#     글자로 세면 무조건 0 이 나온다. 대체꼴까지 찾으니 ≤·√·≥·≠·Σ·σ·× 는 전부 정상으로
#     갈렸다(측정 타당성 먼저). 위 열 종만 진짜다.
for _cells in ("⠲", "⠨⠲", "⠸⠴", "⠖", "⠸⠢", "⠶⠶", "⠘⠒⠕", "⠘⠉", "⠴⠡", "⠸⠴⠴", "⠈⠊"):
    _SYMBOL_REV.pop(_cells, None)
_COMBINED: dict[str, str] = {**_SYMBOL_REV, **_SYLLABLE_REV, **_WORD_ABBR}
# 단독 문장부호(마침표·쉼표·느낌표)도 풀리도록 — 기존 기호 매핑은 덮지 않는다.
# (⠲는 symbol_table에서 ∋로 먼저 잡힘 → 단독 ∋은 그대로, 어말 마침표는 _decode_line의
#  위치 규칙이 별도 처리한다.)
for _c, _t in (("⠲", "."), ("⠐", ","), ("⠖", "!")):
    _COMBINED.setdefault(_c, _t)
# ★ 가역 화살표 ⇄(⠪⠶⠕, 제61항)는 **한글 `응이`와 같은 셀**이다. 역맵에 두면 본문이
#   깨진다 — 실측(전 코퍼스 1,131쪽): 이 셀 **404건 · 230쪽** 중 묵자에 `⇄` 가 있는 쪽
#   **0**, `응이` 가 있는 쪽 **29**. 코퍼스에 화학 가역 반응식이 아예 없다.
#   정방향은 그대로 두고(규정형이 맞다) 역방향에서만 뺀다.
del _COMBINED["⠪⠶⠕"]

# 변이체 정본화 — 같은 점형이 여러 유니코드(붙임표/하이픈/대시)로 매핑될 때 ASCII 정본 우선.
# 물결표 ⠈⠔ 도 같다 — 재추출 묵자 전수에서 `~` 832회 · `∼` 1회다. ASCII 쪽으로 편다.
for _c, _t in (("⠤", "-"), ("⠈⠔", "~")):
    _COMBINED[_c] = _t
# ── 밑줄 빈칸 `_-` = ⠸⠤ (규정 제73항 · 「점자 도서 제작 지침」 2장 2절 3) ──────────
# "밑줄 빈칸은 길이와 관계 없이 _-을 1개 적는다." 정방향은 이미 낸다
# (translator._TAGS.BLANK_RULE · layout_braille._UNDERLINE_BLANK_MARKER · symbol_table `_`).
# 역맵에만 없어 ⠸ 가 미지셀로 새고 ⠤ 가 붙임표로 읽혔다 — `(2n=6+X⟨2838⟩-)` 꼴.
# 실측(전 코퍼스 18,892쪽): ⠸⠤ **5,175건 중 5,135건(99.2%)**이 그대로 샜다.
# ★ **밑줄 하나로 편다.** 점자는 길이를 안 담으므로 원래 길이를 복원할 수 없고,
#   재추출 묵자도 `$2n=6+X\_$` 처럼 밑줄 **한 개**로 적는다(전수 9,229건이 전부 길이 1).
_COMBINED["⠸⠤"] = "_"
# ── UEB 밑줄 표시 `_1`·`_'` = ⠸⠂·⠸⠄ (통일영어점자 타입폼 — 규정 제28항이 준용) ──
# 국어 교재 안 영어 지문에서 밑줄 친 낱말 앞에 ⠸⠂(밑줄 낱말표), 구간 끝에 ⠸⠄(종료표)를
# 적는다. 묵자에 대응 문자가 없는 **서식 표시**라 굵은 글자체표(_strip_bold_marks)처럼 뗀다.
# 역맵에 없어 ⠸ 가 미지셀로 새고 ⠂ 가 쉼표로 읽혔다 — `⟨2838⟩,sad` 꼴.
# 실측(gold 전권 18,892쪽): ⠸⠂ **5,474건**(뒤 6셀에 로마자 3개 이상이 67.9%, 나머지도
#   대부분 EBAE 약자 should·check·through) · ⠸⠄ 1,495건. 같은 쪽에 ⠘⠂ 1,022 · ⠨⠂ 600.
# ★ **밑줄 계열 두 셀만 건드린다.** ⠘⠂·⠨⠂(굵게·이탤릭 낱말표)는 한글 음절 '발'·'잘'과,
#   ⠘⠄·⠨⠄는 '밧'·'잣'과 점형이 같아 맥락 없이 떼면 본문을 먹는다. ⠸⠂·⠸⠄ 는 어느 표에도
#   겹치는 항목이 없어 단독으로 안전하다. ⠸⠶(밑줄 구간표)은 제58항 빠짐표와 겹쳐 별건이다.
for _tf in ("⠸⠂", "⠸⠄"):
    _COMBINED[_tf] = ""
# 소괄호 자리표시자(_mark_paren_pairs가 붙인다) → 실제 괄호
_COMBINED["\ufdd2"] = "("
_COMBINED["\ufdd3"] = ")"
# 자음+ㅖ 음절 — ⠌(ㅖ)가 **받침 ㅆ과 같은 점형**이라(규정 제7항 ㅖ / 제4항 받침 ㅆ)
# 역맵이 받침 쪽으로 기운다. 어느 쪽으로 펼지는 실측으로 정한다 — 재추출 묵자 1,361쪽:
#     혜 206회 : 핬 0회   ·   뎨 1회 : 닸 0회      → ㅖ 로 편다
#     났 241회 : 녜 2회   ·   맜 1회 : 몌 0회      → 현행(받침)이 옳다
# 둘 다 0인 음절(볘·졔·톄 등)은 근거가 없어 건드리지 않는다.
# 실제 피해: `윤혜정` → `윤핬정` · `혜산` → `핬산`.
_YE_OVERRIDE = {"⠚⠌": "혜", "⠊⠌": "뎨"}
_COMBINED.update(_YE_OVERRIDE)
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


# 하단 약자(EBAE lower signs) 중 **낱말의 처음이나 끝에 올 수 없는 것들**.
# 그 조건을 안 걸면 뒤따르는 문장부호가 약자로 새어 나간다: `Ⅲ, Ⅳ`(⠴⠠⠠⠊⠊⠊⠂ ⠠⠠⠊⠧⠲)
# 의 쉼표 ⠂ 가 'ea' 로 읽혀 `IIIEA IV` 가 나왔다. 뒤 칸이 글자가 아니면 약자가 아니다.
# ⚠ `in`(⠔)·`en`(⠢)은 **뺀다** — EBAE에서 낱말 끝에 올 수 있다(`main`). 넣었더니
#   로마자표 없는 영어 줄 판정이 깨졌다(`the main reason` 단위 테스트).
_ENG_LOWER_SIGNS = frozenset("⠂⠆⠒⠲⠖⠶")


def _eng_group_at(s: str, j: int, at_word_start: bool) -> tuple[str, int] | None:
    """s[j]에서 시작하는 영어 약자 → (글자, 소비한 셀 수). 없으면 None."""
    for ln in range(min(_ENG_MAX, len(s) - j), 0, -1):
        seg = s[j:j + ln]
        # 하단 약자는 뒤에 글자가 이어질 때만 약자다(위 주석). ⠲(dd/dis)는 종료표와
        # 같은 셀이라 호출부가 먼저 소비하므로 여기까지 오지 않는다.
        if len(seg) == 1 and seg in _ENG_LOWER_SIGNS:
            nxt = s[j + 1] if j + 1 < len(s) else ""
            if nxt not in _ALPHA_REV and nxt not in _ENG_ANY and nxt != _CAPITAL:
                continue
        if at_word_start and seg in _ENG_INIT:
            return _ENG_INIT[seg], ln
        if not at_word_start and seg in _ENG_FINAL:
            return _ENG_FINAL[seg], ln
        if seg in _ENG_ANY:
            return _ENG_ANY[seg], ln
    return None


_COMMA_CELL = "⠂"
_SUPERSCRIPT = "⠘"      # 위첨자표(수학 제18항)
# 로마 숫자 — 대문자 단어표로 적힌 것만 되돌린다(Ⅰ 은 변수 I 와 셀이 같아 제외).
# 동그라미 낱자 여는 두 칸(㉠=⠶⠿⠁⠶). ⠶ 는 받침 ㅇ 이라 한글 낱말의 **첫 칸**으로
# 오지 않고, 뒤 ⠿ 가 온표라 이 두 칸이면 동그라미 문자가 확실하다.
_CIRCLED_JAMO_OPEN = "⠶⠿"
_ROMAN_NUM_UNI = {"II": "Ⅱ", "III": "Ⅲ", "IV": "Ⅳ", "VI": "Ⅵ", "VII": "Ⅶ",
                  "VIII": "Ⅷ", "IX": "Ⅸ", "XI": "Ⅺ", "XII": "Ⅻ"}


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


def _decode_roman_run(s: str, i: int, *, span_ok: bool = False) -> tuple[str, int] | None:
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
    caps_next = False          # 단일 대문자표 ⠠ 를 만난 직후

    def _emit(t: str) -> None:
        nonlocal caps_next
        if caps_word:
            t = t.upper()
        elif caps_next:
            t = t[:1].upper() + t[1:]
        caps_next = False
        out.append(t)

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
                if span_ok or (s[i] == _ROMAN_START and _roman_span_ahead(s, j + 2)):
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
            # ★ 다음 셀이 **낱자일 때만** 대문자로 만들던 것을 고쳤다. 통일영어점자는
            #   낱말을 약자로 줄이므로(제32항) 대문자표 뒤가 약자인 자리가 흔한데
            #   (`,:5`=When · `,/RUCTURE`=Structure · `,_!`=Their), 그 자리에서 ⠠ 가
            #   통째로 버려져 소문자로 나갔다. 표시를 들고 있다가 **다음에 내보내는
            #   조각**에 씌운다 — 낱자든 약자든 같다.
            caps_next = True
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
                _emit(_w)
                j = _end
                continue
        _g = _eng_group_at(s, j, _word_start)
        if _g is not None:
            txt, ln = _g
            _emit(txt)
            j += ln
            continue
        if c in _ALPHA_REV:
            _emit(_ALPHA_REV[c])
            j += 1
            continue
        if c == _SUPERSCRIPT and s[i] == _ROMAN_START:
            # 화학 이온·거듭제곱 — 로마자 런 안의 위첨자표(수학 제18항).
            # `Na^+`(⠴⠠⠝⠁⠘⠢) 의 ⠘⠢ 가 한글 `밤` 과 같은 셀이라 `Na밤` 으로 나갔다.
            # 명시적 로마자표로 열린 런 안에서만 본다 — 한글 초성 ㅂ 과 안 겹치게.
            # 실측(전 코퍼스 1,131쪽): 로마자 런 뒤 위첨자 **321건**
            # (⠘⠢ 154 · ⠘⠼⠃ 140 · ⠘⠼⠉ 14 · ⠘⠔ 5 …).
            nxt = s[j + 1:j + 2]
            if nxt == _NUMBER_SIGN:
                num, j = _decode_number(s, j + 1)
                # `Ca^2+`(⠘⠼⠃⠢) — 숫자 뒤에 부호가 이어진다. 안 읽으면 남은 ⠢ 가
                # 영어 약자 `en` 으로 새어 `Ca^2en` 이 된다.
                sign = ""
                if s[j:j + 1] in ("⠢", "⠔"):
                    sign = "+" if s[j] == "⠢" else "-"
                    j += 1
                out.append("^" + num + sign)
                continue
            if nxt in ("⠢", "⠔"):
                out.append("^" + ("+" if nxt == "⠢" else "-"))
                j += 2
                continue
            break                                    # 모르는 위첨자 → 런 종료
        if c == _SUBSCRIPT:                          # 첨자표 등 → 근사로 건너뜀
            # ★ 다만 **닫는 대괄호 ⠰⠴** 는 건너뛰면 안 된다 — ⠰ 만 먹고 남은 ⠴ 가
            #   닫는 큰따옴표로 떨어져 `[A]` 가 `[A”` 로 나갔다. 진짜 첨자는 뒤에
            #   수표·글자가 오므로(`A_1`=⠴⠠⠁⠰⠼⠁) 이 조건에 안 걸린다.
            if s[j + 1:j + 2] == _ROMAN_START:
                break
            j += 1
            continue
        if c == _COMMA_CELL:
            # 제32항 구간은 **종료표까지**다. `A, B, C`(⠴⠠⠁⠂ ⠠⠃⠂ ⠠⠉⠲)의 쉼표에서
            # 끊으면 둘째·셋째 글자가 문맥을 잃고 한글로 읽힌다(`A, b, 나.`).
            # 공백 처리와 같은 조건 — 명시적 로마자표로 열렸고 종료표가 앞에 있을 때만.
            # ★ **약자 판정보다 뒤**여야 한다. 앞에 두면 낱말 안의 'ea'(같은 셀)를 먹어
            #   `reason` 이 `r,son` 이 된다(실측: 영어 줄 단위 테스트 2건이 깨졌다).
            if s[i] == _ROMAN_START and _roman_span_ahead(s, j + 1):
                out.append(",")
                caps_word = False              # 대문자 단어표는 낱말 하나까지다
                j += 1
                continue
        break                                       # 비로마자 셀 → 런 종료
    if not out:
        return None
    txt = "".join(out)
    # ★ 대문자 **단어표**(⠠⠠)로 적힌 로마 숫자는 유니코드로 되돌린다.
    #   `Ⅱ` 이상은 ⠠⠠ 로 적히고(⠴⠠⠠⠊⠊), 변수 `I` 와 같은 셀인 `Ⅰ`(⠴⠠⠊, 단일
    #   대문자표)은 구분이 안 되므로 **건드리지 않는다**.
    if caps_word and txt in _ROMAN_NUM_UNI:
        return _ROMAN_NUM_UNI[txt], j
    return txt, j


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


# 수식 토큰 꼬리가 순수 한글인가 — 맞으면 그 부분은 한글 디코더 몫이다.
# 한 음절 이상이고, 한글·마침표·쉼표 말고는 아무것도 안 나와야 한다(미지셀 ⟨…⟩ 포함 금지).
_KOR_TAIL_OK = re.compile(r"^[가-힣]+[.,]?$")


# 이 셀 **바로 뒤**는 변수 자리다 — 한글 꼬리로 넘기지 않는다.
# 「수학 점자」 제12항이 수식 속 변수를 **로마자표 없이** 쓰게 해서, 역방향에서는 그 자리가
# 한글 음절로도 깨끗이 풀린다. `_korean_tail` 이 먼저 걸려 `a^(2-x)` 가 `a^(2-옥언` 이 됐다.
#
# ★ 어디까지 넣나 — **셀별로 갈랐다.** 묶음으로 재면 어느 셀이 이득인지 안 보인다
#   (묶음 판 셋은 12:11 · 12:5 · 8:4 로 전부 기준 미달이었다).
#   규정 정답쌍 312건 셀별 귀속:
#   | 셀 | 좋아짐:나빠짐 | 판정 |
#   |---|---|---|
#   | ⠳ 절댓값(제21항) | **4 : 0** | 넣는다 |
#   | ⠷ 여는 괄호(제6항) | **5 : 1** | 넣는다(아래 한글표 가드) |
#   | ⠔ 뺄셈(제2항) | **1 : 0** | 넣는다 |
#   | ⠌ 분수 | 2 : 3 | **뺀다** — `분의이다.` 처럼 뒤에 한글이 실재한다 |
#   | ⠦ · ⠐ | 0:2 · 1:3 | **뺀다** |
#   | ⠴⠾ 닫는 괄호 | — | **뺀다** — `(2^3)종류의` 처럼 뒤가 한글이다 |
#   실물 1,180쪽 A/B: **좋아짐 27 · 나빠짐 4**(Δ +1.102).
#   ⚠ 나빠짐 4건은 **눈으로 보면 전부 개선**이다 — `2분의(그러므로넌` → `2분의(a+넌` ·
#     `2분의(2·a-펀에` → `2분의(2·a-d)n`. 묵자 정답이 수식을 LaTeX 원문으로 담아
#     (`\frac{a+c}{2}`) 우리가 옳게 풀수록 문자열 유사도가 내려간다. 이 축은 그 지표가
#     못 재는 자리라 눈검사로 판정했다.
_MATH_VAR_PREV = frozenset("⠳⠷⠔")


def _var_follows(tok: str, i: int) -> bool:
    """tok[i] 자리가 변수 자리인가 — 직전 셀로 판정한다.

    ⚠ ⠷ 는 **수식 여는 괄호이자 한글표 ⠸⠷(제39항)의 뒷 셀**이다. ⠸ 가 앞에 붙어 있으면
      한글표라 뒤도 한글이다(`1_(이라도` 가 `1_(o·아도` 로 깨지던 자리).
    """
    if not i or tok[i - 1] not in _MATH_VAR_PREV:
        return False
    if tok[i - 1] == "⠷" and i >= 2 and tok[i - 2] == "⠸":
        return False                                   # 한글표 ⠸⠷ — 뒤는 한글
    return True


def _korean_tail(tok: str, at: int) -> str | None:
    """tok[at:] 가 통째로 한글로 풀리면 그 문자열, 아니면 None."""
    rest = tok[at:]
    if len(rest) < 2:
        return None
    try:
        d = _decode_line(rest)
    except Exception:                                # noqa: BLE001
        return None
    return d if _KOR_TAIL_OK.match(d) else None


def _decode_math_token(tok: str) -> str:
    """수식 토큰을 수학 의미로 디코드 — 구조·연산자 셀을 ^ _ √ × + 등으로 복원.

    수·로마자(변수)·그리스는 그대로 풀고, \\text 한글 등은 _COMBINED로 폴백한다.
    한글 음절과 겹치는 셀(⠘⠜⠌⠡)도 여기서는 수학 기호로 본다(토큰이 이미 수식 판정).
    """
    out: list[str] = []
    i, n = 0, len(tok)
    while i < n:
        c = tok[i]
        if c in (_SPACE_CELL, " "):                 # 빈칸 — 로마자 구간 병합으로 토큰
            out.append(" ")                         # 안에 들어올 수 있다(⟨2800⟩로 샜다)
            i += 1
            continue
        if c == "⠸" and tok[i + 1:i + 2] in _LOG_NEXT:      # 로그(제46항) — 위 주석 참조
            out.append("log ")
            i += 1
            continue
        if c == _NUMBER_SIGN:                       # 수표 → 숫자
            # ★ 동그라미 숫자(제64항 ①=⠼⠂)는 **토큰 첫 칸일 때만** 편다(2026-09-04).
            #   선택지 번호가 옆 수식에 딸려 MATH 로 분류되면 여기로 오는데, 종전에는
            #   ⠂ 를 자릿점 쉼표로 읽어 ①이 `,` 로, ②~⑤가 맨숫자로 떨어졌다
            #   (`① 8/3 ② 3 ③ 10/3` → `, 3분의8  2 3  3 3분의10`).
            #   첫 칸으로 한정해 로그 밑(⠸⠼⠆ = log₂)·자릿점 쉼표는 종전대로 둔다.
            if i == 0:
                _sp = _special_at(tok, 0)
                if _sp:
                    out.append(_sp[0])
                    i = _sp[1]
                    continue
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
        # ★ 수식 토큰의 **꼬리가 한글**이면 거기서 한글 디코더에 넘긴다(2026-09-03).
        #   gold 는 `2분의1이다.` 를 공백 없이 한 토큰으로 적는데, 종전에는 뒤 한글까지
        #   로마자로 읽어 `2분의1oi∋` 가 됐다(⠕⠊=이다 → o,i · ⠲=마침표 → ∋).
        #   꼬리 전체가 한글 음절로 깨끗이 풀릴 때만 넘긴다 — 변수 o·i 를 잃지 않는다.
        if (i and not _var_follows(tok, i) and (tail := _korean_tail(tok, i))):
            out.append(tail)
            break
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
    # 삼각함수 접두 ⠖(규정 제47항)로 시작하고 뒤가 등록된 함수면 수식이다.
    # ⠖ 는 한글에서 낱말 첫 칸으로 안 오므로 오탐이 없다 — 이걸 안 보면
    # `tan x`(⠖⠞⠭)가 TEXT 로 떨어져 `∈얼옥` 이 된다.
    if tok[:1] == "⠖" and any(tok.startswith(k) for k in _TRIG_CELLS):
        return "MATH"
    # ★ 로마자표로 **시작하는** 토큰은 로마자 런이다(제29항 — 로마자표는 낱말 앞).
    #   수식으로 분류하면 수식 디코더가 ⠴ 를 닫는 괄호로 읽어 `A^2`(⠴⠠⠁⠘⠼⠃)가
    #   `)a^2` 로 나간다. 대문자표가 뒤따를 때만 본다 — 숫자 뒤 단위표(50%=⠼⠑⠚⠴⠏)와
    #   닫는 괄호는 토큰 **첫 칸**에 안 온다.
    if tok[:1] == _ROMAN_START and tok[1:2] == _CAPITAL:
        return "TEXT"
    # ★ 동그라미 문자·낱자(제64항)로 **시작하는** 토큰도 본문이다. 문항 번호·선택지
    #   표시라 수식이 아니다. `㉠(G_1` (⠶⠿⠁⠶⠦⠄⠠⠛⠰⠼⠁) 이 첨자 신호(⠰⠼) 때문에
    #   수식으로 분류돼 수식 디코더가 ⠶ 를 `{`, ⠿ 를 `∞` 로 읽었다 — `{∞a{('g_1`.
    if tok[:2] == _CIRCLED_JAMO_OPEN:
        return "TEXT"
    # ★ 아래아 ㆍ(⠐⠼, 제25항)의 ⠼ 는 수표가 아니다 — 수식 판정에서 뺀다. 안 빼면
    #   `ᄒᆞᆫ` 이 든 토큰이 옆 수식에 딸려 수식 디코더로 가 옛한글 분기를 못 만난다.
    has_num = _NUMBER_SIGN in tok.replace(_ARAEA, "")
    # ★ 닫는 묶음 괄호 ⠾ 만으로는 수식 신호가 아니다 — 한글 `전`(⠨⠾)·`언`(⠶)처럼
    #   흔한 음절과 겹친다. `전쟁(1840)`(⠨⠾⠨⠗⠶⠦⠄⠼⠁⠓⠙⠚⠠⠴) 이 수표+⠾ 로 MATH 가 돼
    #   `전ρ{(1840)` 으로 깨졌다. 묶음 괄호는 짝으로 오므로 **여는 ⠷ 를 요구한다.**
    if has_num and (_MATH_SIGNAL_RE.search(tok) or _MATH_PAREN_OPEN in tok):
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
#
# ★ 2026-08-24 재측정으로 **0.40 → 0.70 으로 올렸다.** 0.40 은 순수 수식까지 잡아먹는다 —
#   점자 셀은 한글로 읽으면 대부분 한글이 되므로 "한글 비율이 높다"가 "한글이다"의 증거가
#   못 된다. 실측 formula 218건(문턱별 발동 수 · 그중 한글경로가 실제로 나은 수 · 평균 유사도):
#     0.40  발동 22 · 맞은 것  9(41%) · 0.6815   ← 종전. 13건이 손해였다
#     0.55  발동 10 · 맞은 것  7(70%) · 0.6983
#     0.70  발동  6 · 맞은 것  6(100%) · **0.7030**   ← 채택
#     끔    발동  0 ·            · 0.6881
#   실물: `S_n = a + (a+d) + …` 가 `서첸=그러므로"그러므로팧+…` 로 깨지던 것이 이것이다.
_MATH_KOR_RATIO = 0.70
# 이보다 짧은 수식은 통째로 수식으로 읽는다 — 설명 문장이 섞일 길이가 아니다.
_MATH_KOR_MIN_CELLS = 24


# 마침표 뒤에 올 수 있는 닫는 부호들 — 이게 오면 그 ⠲ 는 어말이다(∋ 아님).
#   ⠠⠄ 점역자 주표 · ⠠⠴ 닫는 소괄호 · ⠴ 닫는 큰따옴표 · ⠐⠶ 닫는 홑화살괄호 · ⠶ 닫는 괄호
_PERIOD_CLOSERS = ("⠠⠄", "⠠⠴", "⠐⠶", "⠴", "⠶")

# 홑 곱셈표 — 앞뒤가 모두 공백 셀인 ⠡ 만. 붙은 ⠡ 는 한글 약자 '연'이라 안 건드린다.
_LONE_TIMES_RE = re.compile(r"(?<=⠀)⠡(?=⠀)")


def _closing_follows(s: str, at: int) -> bool:
    """위치 at 에서 닫는 부호가 시작하는가(긴 것부터 본다)."""
    return any(s.startswith(c, at) for c in _PERIOD_CLOSERS)


def decode(braille: str, *, math: bool = False) -> str:
    """점자 BRF 문자열 → 한국어 텍스트(근사). 줄바꿈은 보존.

    math=True면 전체를 수식 구역으로 보고 디코드한다(요소 type이 formula일 때 호출자가 지정).
    기본(False)은 공백 단위 토큰별로 수식/한글을 자동 판별한다(인라인 수식).
    """
    # 줄을 넘는 짝(굵은 글자체표·한글표)을 먼저 벗긴다 — 아래 줄 분리보다 앞서야 한다.
    braille = _mark_paren_pairs(
        _strip_emph_marks(_strip_hangul_indicator(_strip_bold_marks(braille))))
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
# ★ 짝이 **줄을 넘는다.** 32칸 조판이라 괄호 안이 두 줄에 걸친다. 줄 단위로만 보면 여는
#   ⠦⠄ 가 짝을 못 찾고 **받침 ㅌ**(제3항)으로 붙는다 — `개최(1919. 1.)` 가 `개쵵'1919. 1.):` 로.
#   실측(gold 18,892쪽): 괄호 셀이 든 줄 117,909 중 **여는 쪽이 남는 줄 13,459**(닫는 쪽 14,994).
#   닫는 표까지 거리는 **1줄 뒤 10,794(80.2%) · 2줄 뒤 1,680** 으로 **1~2줄이 92.7%** 다.
#   그래서 개행을 허용하되 **길이 80셀**(32칸 조판에서 두세 줄)로 묶는다 — 굵은 글자체표(240)보다
#   훨씬 좁다. ⚠ `⠦` 는 받침 ㅌ·물음표·큰따옴표·수식 괄호와, `⠴` 는 로마자표·닫는 큰따옴표와
#   겹친다(원장 C-100 에서 세 판 다 기각한 셀들이다). **넓히면 오검출도 같이 넓어진다.**
#   ⚠ 내용 문자류에 `\ufdd4`(드러냄표를 벗긴 자리)도 넣는다 — 안 넣으면 강조가 낌
#     괄호가 짝을 못 찾는다.
_PAREN_PAIR_RE = re.compile(r"⠦⠄((?:(?!⠦⠄|⠠⠴)[\u2800-\u28ff\n \ufdd4]){1,80})⠠⠴")


def _mark_paren_pairs(line: str) -> str:
    """짝이 맞는 소괄호 셀만 자리표시자로 바꾼다(따옴표와의 충돌 회피)."""
    return _PAREN_PAIR_RE.sub(
        lambda m: _PAREN_OPEN_MARK + m.group(1) + _PAREN_CLOSE_MARK, line)


# ── 굵은 글자체표 (규정 제56항) ──────────────────────────────────────────────
# 규정 제56항은 강조를 두 갈래로 적는다.
#   · 드러냄표·밑줄 → `,-` … `-'` (⠠⠤ … ⠤⠄)
#   · **굵은 글자**  → `;-` … `-2` (⠰⠤ … ⠤⠆)
# 역맵에 굵은 쪽이 없어 뜻 없는 ASCII 가 새어 나갔다 — `_-어제도-;`.
# 실측(전 코퍼스 1,131쪽): ⠰⠤ **992** · ⠤⠆ **993** 으로 완전한 짝이다
# (드러냄표 쪽은 ⠠⠤ 2,819 · ⠤⠄ 2,657).
#
# ★ **표시를 벗기고 내용만 낸다.** 태그로 되살리는 쪽은 이미 기각했다(원장 C-102) —
#   묵자 쪽 `<!강조>` 1,074건과 점자 쪽 드러냄표 394건이 서로 다른 자리를 가리켜
#   실물 A/B 가 나빠졌다. 여기서는 이물질을 없애는 것까지만 한다.
# ★ 짝이 **줄을 넘는다.** 점자책은 32칸 조판이라 강조 구간이 두세 줄에 걸친다.
#   줄 단위로만 벗기면 여는 표와 닫는 표가 갈려 둘 다 이물질로 남는다(실측: 60쪽
#   표본에서 `_-` 45건 · `-;` 41건이 그 잔여였다). 그래서 줄을 쪼개기 **전에** 벗긴다.
_BOLD_PAIR_RE = re.compile(r"⠰⠤((?:(?!⠰⠤|⠤⠆)[\u2800-\u28ff\n ]){1,240})⠤⠆")


def _strip_bold_marks(line: str) -> str:
    """짝이 맞는 굵은 글자체표를 벗긴다(제56항)."""
    return _BOLD_PAIR_RE.sub(lambda m: m.group(1), line)


# 드러냄표·밑줄 강조(제56항 앞갈래) — 굵은 글자체표와 **같은 처방**이다.
# 역맵에 없어 `옳지 -않은-' 것은?` 처럼 이물질이 본문에 남았다(수능 부정 문항이라
# 뜻이 뒤집히는 자리다). 여는 ⠠⠤ 는 붙임표 `-`, 닫는 ⠤⠄ 는 `-'` 로 낱개 분해됐다.
#
# ★ **짝이 맞을 때만** 벗긴다 — ⠠⠤ 는 「수학 점자」 제23항 2호의 밑줄(`,x,-`)과
#   UEB 줄표로도 쓰이는데, 그 둘은 **닫는 표가 없다.** 짝을 요구하면 저절로 갈린다.
#   실측(전 코퍼스 18,892쪽): ⠠⠤ 11,242 · ⠤⠄ 10,912 · 짝 **10,864**(짝 없는 여는 표
#   378건·닫는 표 48건은 종전대로 붙임표로 둔다). 짝은 3,769쪽에 나온다.
#   ⚠ UEB 타입폼 표시(⠸⠂ 밑줄 낱말 5,474 · ⠸⠄ 밑줄 종료 1,904 · ⠘⠂ 굵게 · ⠨⠂ 이탤릭)와는
#     셀이 겹치지 않는다 — 짝 안에서 ⠸⠂·⠸⠄ 는 **0건**이다.
# ★ 굵은 쪽과 같이 줄을 넘는다(짝 10,864 중 3,234건이 줄바꿈을 낀다). 그래서 여기서도
#   줄을 쪼개기 **전에** 벗긴다.
# ★ 내용 없는 짝 `⠠⠤⠤⠄` 도 벗긴다({0,240}) — 종전 출력 `(—')` 가 `()` 가 된다.
# ★ 표를 **그냥 지우면 안 된다.** 표는 토큰 경계이기도 해서, 지우면 뒤 셀이 앞 음절의
#   받침으로 먹힌다 — `⠠⠤아시아⠤⠄⠦⠄(…` 가 `아시앝'세계` 로 깨졌다(발동 4,196쪽
#   전수에서 그냥 지우는 쪽이 센티넬보다 나쁜 줄 **325줄·209쪽**). 그래서 **자리에 센티넬을 남기고** 라우터가 그걸 폭 0인 분리자로
#   쓴다. 유니코드 비문자라 실문서에 나올 수 없다(_mark_paren_pairs 와 같은 수법).
_EMPH_PAIR_RE = re.compile(r"⠠⠤((?:(?!⠠⠤|⠤⠄)[\u2800-\u28ff\n ]){0,240})⠤⠄")
_EMPH_MARK = "\ufdd4"      # 표를 벗긴 자리 — 토큰 경계로만 남고 글자는 안 낸다


def _strip_emph_marks(line: str) -> str:
    """짝이 맞는 드러냄표·밑줄표를 벗긴다(제56항)."""
    return _EMPH_PAIR_RE.sub(lambda m: _EMPH_MARK + m.group(1) + _EMPH_MARK, line)


# ── 한글표·한글 종료표 (규정 제39항) ─────────────────────────────────────────
# 로마자가 주된 문장 안, 수식의 일부, 화학 반응식 안에 한글이 나올 때 한글표 `_(`
# (⠸⠷)과 한글 종료표 `_)`(⠸⠾)으로 묶는다. 역맵에 없어 쓰레기가 나갔다 —
# `(㉠)+(㉢)=` 가 `⟨2838⟩온㉠⟨2838⟩언+⟨2838⟩온㉢⟨2838⟩언=` 로 풀렸다
# (⠸ 가 미해독으로 남고 ⠷ 가 뒤 셀과 붙어 엉뚱한 음절이 됐다).
# 실측(전 코퍼스 1,131쪽): ⠸⠷ **397** · ⠸⠾ **383**.
# 감싼 것이 곧 한글 본문이므로 **표만 벗기고 내용을 그대로 낸다.**
_HANGUL_IND_RE = re.compile(r"⠸⠷((?:(?!⠸⠷|⠸⠾)[\u2800-\u28ff\n ]){0,240})⠸⠾")


def _strip_hangul_indicator(line: str) -> str:
    """짝이 맞는 한글표·한글 종료표를 벗긴다(제39항)."""
    return _HANGUL_IND_RE.sub(lambda m: m.group(1), line)


def _build_eng_function() -> frozenset[str]:
    """영어 기능어 집합 — 로마자표 없는 영어 줄을 가려낼 때 마지막 증거로 쓴다."""
    from app.ai.braille import eng_braille as _E

    return frozenset(w.lower() for w in (*_E.WORDSIGNS, *_E.SHORT_FORMS)) | {"a", "i", "of", "and", "the", "is", "are", "was", "for", "on", "at", "with"}


_ENG_FUNCTION = _build_eng_function()

# 낱말 끝에 오는 문장 부호 — 로마자표 없는 영문 줄에서만 뗀다. ⠲ 는 로마자 종료표와
# 같은 셀이라 런이 통째로 먹어 버려 마침표가 사라졌고(`home.` → `home`), 나머지는
# 런을 끊어 낱말 판정을 실패시켰다.
_ENG_TAIL_PUNCT = {"⠲": ".", "⠂": ",", "⠦": "?", "⠖": "!", "⠆": ";", "⠒": ":"}

# ── UEB 밑줄 글자체표 (UEB 9.5) ──────────────────────────────────────────────
# 「점자 자료 제작 지침」에는 영문 강조 점형이 없다. 점역사 회신이 그 자리를 메운다 —
# "영어 원서 등 영문 표현의 강조나 발음/변음 부호는 UEB 규정을 참고해야 합니다"
# (braille-source/text/점역사_qna.txt A13). UEB 글자체표는 접두 셀 + 기호표 ⠆ ·
# 낱말표 ⠂ · 구간표 ⠶ · 종료표 ⠄ 넷이고, 밑줄의 접두는 ⠸(4-5-6)다.
# ★ **코퍼스 스스로가 이 표를 싣는다.** ES-TXT-KA0010 body/p0155 의 점자 기호
#   일람표가 제67항 점형표로 여섯 계열을 나란히 보인다 —
#   ⠠(대문자)·⠰(1종)·⠨(이탤릭)·⠘(굵게)·⠸(밑줄)·⠈(스크립트) × 기호/낱말/구간/종료.
#   실물도 그대로다: `⠸⠶⠠⠊ ⠠⠇⠊⠅⠑ ⠠⠁⠏⠏⠇⠑⠎⠲⠸⠄` = 구간표 + "I Like Apples." + 종료표.
# 역맵에 없어 ⠸ 가 미해독으로 샜고, 그 이물질이 낱말 런을 끊어 **영어 줄 판정
# (_english_line, #482)까지 막았다.** 그래서 표를 벗겨 다시 판정한다.
#
# ★ **낱말표 ⠸⠂ 도 넣는다**(#490, 2026-09-04). 접두 ⠸ 뒤의 ⠂ 는 한글 어디와도 안 겹친다 —
#   역맵 전 표(_COMBINED·_SYMBOL_REV·_SYLLABLE_REV·_ENG_*) 대조에서 ⠸⠂ 는 항목이 없다.
#   (반면 ⠘⠂·⠨⠂ 는 한글 음절 '발'·'잘'이라 굵게·이탤릭 쪽은 못 넣는다.)
#   실측(gold 전권 18,892쪽): ⠸⠂ 든 줄 4,197 중 _english_line 통과가
#   그대로 0 · 이 정규식(⠂ 없이) 0 · **⠂ 를 더하면 724**. 이 줄들은 이 셀 하나에만 막혔다.
# ★ 구간표 ⠸⠶ 는 도형 □(제40항)·빠짐표(제58항)·글머리(제72항)와 **점형이 같다.**
#   그래서 벗긴 줄이 `_english_line` 을 통과할 때만 벗긴다. 한글 줄은 그 판정을
#   구조적으로 통과하지 못하므로(왕복 대조 + 서로 다른 기능어 둘) □ 쪽은 못 건드린다.
#   도형 반복 틀 `⠸⠶ⁿ⠇`(_SHAPE_RUN_RE)과 제72항 글머리(뒤가 빈칸·줄끝)는 내다보고 뺀다.
_UEB_UNDERLINE_RE = re.compile(r"⠸(?:[⠆⠄⠂]|⠶(?!⠶*⠇)(?=[^⠀ ]))")


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
    if sum(1 for w in words if w) < 2:   # 한 낱말은 단서가 너무 약하다(⠎=so ↔ 한글)
        return None
    out: list[str] = []
    mid_cap = False
    for w in words:
        if not w:
            out.append("")
            continue
        # 낱말 끝 문장 부호를 떼고 읽는다. 로마자표가 없는 문단이라 ⠲ 는 종료표가
        # 아니라 **마침표**이고, 나머지는 런을 끊어 낱말을 못 읽게 만든다.
        core, tail = w, ""
        while core and core[-1] in _ENG_TAIL_PUNCT:
            tail = _ENG_TAIL_PUNCT[core[-1]] + tail
            core = core[:-1]
        if not core:
            return None
        got = _decode_roman_run(_ROMAN_START + core, 0, span_ok=True)
        if got is None or got[1] != len(core) + 1:  # 낱말을 끝까지 못 읽으면 영어가 아니다
            return None
        if _CAPITAL in core[1:] and core[0] != _CAPITAL:
            mid_cap = True           # 낱말 **중간**의 대문자표 — 영어 표기에 거의 없다
        out.append(got[0] + tail)
    text = " ".join(out)
    funcs = {w.strip(".,;:?!'").lower() for w in text.split()} & _ENG_FUNCTION
    if _E.translate(text).replace(" ", _SPACE_CELL) == line:
        # 왕복만으로는 모자란다 — 한글 두 낱말이 뜻 없는 알파벳으로 되짚기까지 통과한다
        # (실측 오탐: `우주 그물로` → `dujya Oiu`, 글상자 테두리 → `forggg…`).
        # 영어 문장이라면 기능어가 적어도 하나는 있다(the·to·do·in·so…). 그걸 요구한다.
        return text if funcs else None
    # ── 제29항 [다만] 영문 **문단** — 왕복이 구조적으로 안 맞는 자리 ──────────
    # 정방향 `eng_braille` 는 숫자를 점자로 안 바꾸고(`1940s`), 낱말표를 도서와 다르게
    # 쓴다(`to` → ⠖ 인데 도서는 ⠞⠕). 그래서 영어 지문 줄은 아무리 옳게 읽어도 왕복을
    # 통과하지 못한다 — 영어 교재 한 쪽이 통째로 뜻 없는 한글로 나가던 뿌리다.
    # 왕복 대신 **기능어 두 개**를 증거로 쓴다. 전 코퍼스 18,892쪽 실측:
    #   기능어 0개 25,754줄 · 1개 9,697줄 · 2개 이상 10,788줄.
    #
    # ★ **서로 다른** 기능어 둘을 요구한다. 같은 기호가 되풀이되는 줄(자모 보기 `ㄴ ㄷ ㄹ`
    #   = ⠿ 가 여러 번 → `for, forin for:`, 표 구분선 → `for … for`)이 기능어 개수만으로는
    #   통과한다. 전 코퍼스 실측으로 갈랐다 — 개수 기준이면 영어책 밖에서 81줄이 뒤집히고
    #   그중 20줄이 한글 손해인데, **서로 다른** 둘을 요구하면 뒤집히는 줄이 63줄로 줄고
    #   그중 한글 손해는 **7줄**이다. 이득은 11,616 → 11,323줄만 준다.
    #   낱말 **중간**의 대문자표(`mid_cap`)도 뺀다 — 영어 표기에 거의 없고, 한글 오탐
    #   `⠁⠉ ⠚⠻⠙⠻ … ⠕⠝`(→ `according jerder … on`)이 그 꼴이었다.
    return text if len(funcs) >= 2 and not mid_cap else None


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


# ── 화학식 대소문자 (과학 점자 제2항) ────────────────────────────────────────
# 규정은 화학식을 **원소마다 대문자표**(`,h` = ⠠⠓)로 적는데, 수식 디코더가 ⠠ 를 흘려
# 소문자로 낸다 — `H₂O` → `h_2o` · `SO₄` → `so_4`.
# ⚠ 무조건 대문자로 바꾸면 안 된다. 한 글자 꼴(`z_1`·`t_1`)은 수학 변수가 대부분이다
#   — 실측 3,332건 중 묵자가 소문자인 것이 1,707 로 더 많다.
# **두 글자 이상 + 원소 기호**로 좁히면 52건이고 그중 묵자가 대문자인 것이 38(73%),
# 소문자는 3(6%)이다(상위 꼴 nh·co·no·hco·ca — 전부 원소 조합).
_ELEMENTS = frozenset("""
h he li be b c n o f ne na mg al si p s cl ar k ca sc ti v cr mn fe co ni cu zn
ga ge as se br kr rb sr y zr nb mo tc ru rh pd ag cd in sn sb te i xe cs ba
hg pb bi po at rn fr ra u np pu
""".split())
_CHEM_RE = re.compile(r"(?<![A-Za-z])([a-z]{2,3})(?=_\d)")


def _fix_chemical_case(text: str) -> str:
    """두 글자 이상 원소 기호 꼴을 대문자로 되돌린다(과학 점자 제2항)."""
    def _rep(m: "re.Match[str]") -> str:
        w = m.group(1)
        # `nh`→N+H, `hco`→H+C+O 처럼 원소로 쪼개지는 것만 본다.
        for cut in ((1, 1), (1, 2), (2, 1), (1, 1, 1)):
            if sum(cut) != len(w):
                continue
            parts, i = [], 0
            for n in cut:
                parts.append(w[i:i + n])
                i += n
            if all(x in _ELEMENTS for x in parts):
                return "".join(x.capitalize() for x in parts)
        return w

    return _CHEM_RE.sub(_rep, text)


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
# 제목이 테두리 안에 들어가는 꼴도 있다(NLD — 위 테두리 중간에 제목). 제목은 실제
# 내용이므로 살려서 【글상자 제목】으로 낸다.
# ⚠ 줄 **전체**가 테두리일 때만 잡으면 실물을 놓친다. 실제 데이터는 테두리 뒤에 줄바꿈
#   없이 본문이 같은 문자열로 이어진다(`⠿⠛…⠿⠀⠿⠁⠲⠀⠦⠄⠫…`). 그래서 **테두리 구간만**
#   찾아 바꾸고 나머지는 그대로 읽는다. 채움 셀을 4칸 이상 요구하므로 약자 '옹'(⠿ 한 칸)과
#   `⠿⠁⠲`(ㄱ.) 같은 한글은 안 걸린다.
# 표 칸 구분선 — 같은 셀만 길게 반복한다(NLD 표 조판). 글자가 아니라 도형이라 음절로
# 읽으면 `,,,,,,,,,,,,`가 본문 사이에 섞인다(재점역 5차 69쪽에서 65요소). ⠂ 단독은 쉼표라
# **6칸 이상 연속**일 때만 본다.
_TABLE_RULE_RE = re.compile(r"^[⠀ ]*([⠐⠂⠤⠒⠶])\1{5,}[⠀ ]*$")

_BOX_BORDER_RE = re.compile(
    r"[⠿⠖⠓](⠛|⠶|⠒|⠐)\1{3,}(?:[⠀ ](.+?)[⠀ ]\1{3,})?[⠿⠲⠚]")


def _decode_line_router(line: str, math: bool) -> str:
    """줄을 공백 단위로 나눠 수식 토큰은 수학 디코더로, 나머지는 한글 디코더로 라우팅."""
    if not line:
        return ""
    if _TABLE_RULE_RE.match(line):      # 표 칸 구분선 — 글자가 아니라 도형이다
        return "【표 구분선】"
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
        if eng is None and _UEB_UNDERLINE_RE.search(line):
            # UEB 밑줄 글자체표를 벗겨야 영어로 읽힌다 — 표가 낱말 런을 끊는다.
            eng = _english_line(_UEB_UNDERLINE_RE.sub("", line))
        if eng is not None:          # 로마자표 없는 순수 영어 줄 (제29항 [다만])
            return eng
    # 네모 빈칸 ⠸⠦␣⠴⠇ — 규정 제73항. 가운데가 **공백 셀**이라 아래 토큰 분리가
    # 여는 쪽과 닫는 쪽을 갈라 놓는다(layout_braille._ATOMIC_SEQS 와 같은 이유).
    # 줄을 쪼개기 전에 통째로 치운다.
    line = line.replace(_BOX_CHAR_OPEN + _SPACE_CELL + _BOX_CHAR_CLOSE, "▯▯")
    line = _TABLE_BLANK_RE.sub("", line)          # 표의 빈칸 ⠿⠿ — 제73항
    # 도형 반복 틀 — 토큰을 쪼개기 전에 편다(⠸ 와 ⠇ 가 갈려 나가면 못 맞춘다).
    line = _SHAPE_RUN_RE.sub(_shape_run_repl, line)
    # 글머리 네모 □ — 규정 제72항. 홀로 선 것만이다(붙은 ⠸⠶ 는 위에서 갈랐다).
    line = _BULLET_RE.sub("□", line)
    # 홑 곱셈표 ⠡ — 「수학 점자」 제2항. 한글 약자 '연'과 점형이 같지만 **앞뒤가 모두
    # 공백일 때만** 곱셈표다(제11항 "수식은 앞뒤를 두 칸씩 띄어 쓴다").
    # 실측(코퍼스 2,500쪽): 홑 ⠡ 110건이 전부 가계도 교배 기호이고, 약자 '연'으로 쓰인
    # 붙은 ⠡ 는 18,316건으로 공백 조건에서 완전히 갈린다.
    line = _LONE_TIMES_RE.sub("×", line)
    line = _mark_paren_pairs(line)
    # 드러냄표 센티넬도 분리자다 — 폭이 0이라 아래에서 공백을 안 낸다.
    parts = re.split(r"([⠀ ]+|" + _EMPH_MARK + ")", line)
    tokens, seps = _merge_roman_tokens(parts[0::2], parts[1::2])
    tokens = [t.replace(_EMPH_MARK, "") for t in tokens]    # 로마자 병합이 되삼킨 것
    if math:
        is_math = [True] * len(tokens)
    else:
        is_math = _resolve_math_context([_classify_token(t) for t in tokens])
    pieces = []
    for idx, tok in enumerate(tokens):
        if tok:
            pieces.append(_decode_math_token(tok) if is_math[idx] else _decode_line(tok))
        if idx < len(seps):
            pieces.append("" if seps[idx] == _EMPH_MARK else " " * len(seps[idx]))
    return _fix_chemical_case(_join_num_hangul(_restore_wrap_parens("".join(pieces))))


# 네모 문자 쌍(규정 제64항) — 정방향 translator._TAGS.BOX_CHAR 와 같은 점형이다.
_BOX_CHAR_OPEN, _BOX_CHAR_CLOSE = "⠸⠦", "⠴⠇"

# 표의 빈칸(제73항) — `==`(⠿⠿). 정방향 translator._TAGS.BLANK_TABLE 과 같은 점형이다.
# 묵자 쪽은 그냥 빈 칸이므로 **아무것도 내지 않는다**(네모 빈칸 ▯▯ 와 다르다 — 저쪽은
# 묵자에 □ 가 보인다). 역맵에 없어 `옹옹`(약자 '옹' 두 번)으로 읽혀 5×4 표가 통째로
# 무의미해졌다.
# ★ **양옆이 경계일 때만.** ⠿ 는 약자 '옹'이자 온표(제8·9항)라 셀만 보면 못 가른다.
#   실측(전 코퍼스 18,892쪽) ⠿ 런 분포:
#     len=1 붙음 281,559 · len=1 단독 4,085 · len=2 **단독 4,286(514쪽)** · len=2 붙음 596
#   단독 ⠿⠿ 표본은 전부 표 안(앞뒤가 표 구분선·글상자 테두리)이었다. 붙은 596건은
#   `옹`+온표+자모 꼴이 섞여 있어 손대지 않는다.
_TABLE_BLANK_RE = re.compile(r"(?<![^⠀ ])⠿⠿(?![^⠀ ])")

# 단독으로 쓴 문장 부호 — 규정 제49항 [붙임].
#   "빈칸 뒤에 문장 부호가 단독으로 쓰여 다른 기호와 혼동될 때에는 그 앞에 _ 을 적고,
#    문장 부호 뒤에 한 칸을 띈 후 문장 부호의 명칭을 점역자 주표로 묶어 나타낸다."
#   규정 예문: `? 대신 .를 쓸 수 있다.` → `_8 ,'e&[5d+,'` (⠸⠦ + 점역자주 '물음표')
# ★ **물음표 하나만 넣는다.** ⠸ 뒤에 오는 다른 부호 셀은 이미 다른 뜻이 있다 —
#   ⠸⠲ 는 ▲ 글머리(31,629회) · ⠸⠌ 는 빗금(14,635회) · ⠸⠤ 는 밑줄(5,159회).
#   네모 문자 쌍을 걷어 낸 뒤 ⠸⠦ 는 **207회·76쪽**이고, 짝이 없어 여기까지 온다.
# ⚠ 네모 문자 `⠸⠦ … ⠴⠇` 가 **먼저** 잡혀야 한다 — 아래 분기 순서가 그것이다.
_LONE_PUNCT_REV = {"⠸⠦": "?"}
# ⠸ 바로 뒤가 이 셀이면 로그다(「수학 점자」 제46항) — 아래 두 경로가 같이 본다.
_LOG_NEXT = frozenset("⠼")

# ── 도형 반복 틀 `⠸ + 같은 셀 xN + ⠇` (제57항 숨김표 · 제58항 빠짐표) ──────────
# 정방향은 이미 낸다(translator._box_blank_repl · _HIDDEN_X_RUN_RE). 역맵에 **반복 규칙만**
# 없어 `⠸⠶⠶⠇` 가 `⟨2838⟩≡사`(미지셀 ⠸ + ⠶⠶=≡ + ⠇=사)로 깨졌다.
# 미해독 잔여물 전수(1,180쪽)에서 미지셀은 **⠸ 하나뿐**이고 127쪽·545건이 이 틀이다.
#
# ★ 어느 글자로 펴나 — **규정이 셀을 정하고 실측이 글자를 정한다.** 다대일이라 빈도로 편다.
#   쪽 안 등장 순서로 짝지어 센 값이다(도형 런 개수가 gold·묵자 양쪽에서 같은 쪽만).
#   ⚠ 쪽 단위로 세면 노이즈가 이긴다 — 그렇게 재면 ⠶ 가 ○537:□406 으로 뒤집혀 보인다.
#   | 셀 | 묵자 | 규정 |
#   |---|---|---|
#   | ⠴ | ○ **117/123** | 제57항 숨김표 `_00l` (김○○ 씨) |
#   | ⠶ | □ **36/39**  | 제58항 빠짐표 `_777l` (아음은 □□□의 석 자다) |
#   | ⠬ | △ **24/27**  | 제57항 숨김표 `_++l` (△△도서관) |
#   | ⠭ | × **15/15**  | 제57항 숨김표 `_xxxl` (이 ×××야!) |
#   | ⠢ | ◇ **17/17**  | 제57항 [붙임] **제2 점역자 정의** `_5l` (2016년 ◇월) |
#   ⚠ 제1·제3 점역자 정의(⠔ `_9l` ☆ · ⠕ `_ol` ◆)는 **넣지 않는다.** 실측이 각각 2건·3건
#     뿐이고 ⠕ 는 규정 예시(◆)와 어긋난다(◎2·◇1). 종전대로 미지셀로 남긴다.
#   ⚠ 한계 — [붙임]의 "점역자 정의"는 **책마다 뜻이 다를 수 있다.** 규정 예시와 이 코퍼스
#     실측이 맞아떨어져 ⠢=◇ 만 넣었다. 다른 책에서 어긋나면 원장에 올려 다시 본다.
_SHAPE_RUN_CHAR = {"⠴": "○", "⠶": "□", "⠬": "△", "⠢": "◇", "⠭": "×"}
_SHAPE_RUN_RE = re.compile(r"⠸([⠴⠶⠬⠢⠭])\1*⠇")


def _shape_run_repl(m: re.Match) -> str:
    return _SHAPE_RUN_CHAR[m.group(1)] * (len(m.group()) - 2)


# ── 글머리 기호 (규정 제72항) ────────────────────────────────────────────────
# 제72항은 ○ □ △ • 를 `_0 _7 _+ _4`(⠸⠴ ⠸⠶ ⠸⠬ ⠸⠲)로 적는다. 규정 예문:
#   `□ 2021 세계한국어한마당` → `_7 #bjba …`
# 가운뎃점 글머리 ⠸⠲(•)는 이미 역맵에 있다. **네모 ⠸⠶ 만 더 넣는다** — ○(⠸⠴)과
# △(⠸⠬)는 「수학 점자」의 합성 ∘(제15항 5호)·증분 ∆(제40항)과 점형이 같아서,
# 넣으면 그 둘이 깨진다(회귀 테스트 `test_역점역_정확도_floor[symbols]` 가 잡았다).
# 정방향도 이 셀을 낸다(layout_braille `⠸⠶⠇`→`⠸⠶` · kor_math_rules `□`→`⠸⠶`) —
# 역맵에만 뚫린 한쪽짜리 구멍이다.
# ★ **뒤가 빈칸이거나 줄끝일 때만** 본다. 붙어 나오는 ⠸⠶ 는 UEB 밑줄 구간표이고,
#   틀 꼴 `⠸⠶ⁿ⠇` 는 위 _SHAPE_RUN_RE 가 앞서 편다.
_BULLET_RE = re.compile(r"⠸⠶(?=[⠀ ]|$)")


# ── 점형표 (규정 제67항) ─────────────────────────────────────────────────────
# 제67항: "묵자에 표기된 점형은 해당 점형 앞에 점형표 _=을 적어 나타내며, 뒤는 한 칸
# 띄어 쓴다." 규정 예문 그대로 `마침표는 _=4으로 적는다`(⠸⠿⠲) 꼴이다. 뒤따르는 셀은
# **글이 아니라 점형 그 자체**이므로 한글로 풀면 안 된다 — 그대로 내보낸다.
# 역맵에 없어 ⠸ 가 미해독으로 새고 ⠿ 가 약자 '옹'으로 읽혔다(`⠸⠿⠲` → `⟨2838⟩ㅍ`).
# 실측(전권 18,892쪽): 미해독 ⠸ 배출 중 ⠸⠿ 가 4,655건인데 **쪽은 45쪽뿐**이다 —
# 교과서 부록의 '점자 기호 일람표' 쪽에 몰려 있다(예: ES-TXT-KA0010 body/p0155).
_CELLFORM_IND = "⠸⠿"

# 페이지행 걸침 접두 토큰 — 낱자 하나 + 수표 + 숫자로 **토큰이 끝나야** 한다.
# ⚠ 숫자 셀은 유니코드에서 **연속 범위가 아니다**(1=⠁ 2=⠃ 3=⠉ 4=⠙ 5=⠑ 6=⠋ 7=⠛
#   8=⠓ 9=⠊ 0=⠚). `[⠁-⠚]` 로 쓰면 ⠈·⠕ 같은 한글 자모까지 들어와 `운6기`가 `g6기`로 깨진다.
_CONT_PREFIX_RE = re.compile(r".⠼[⠁⠃⠉⠙⠑⠋⠛⠓⠊⠚]+")


def _decode_line(s: str) -> str:
    out: list[str] = []
    i, n = 0, len(s)
    _after_number = -1        # 수표 숫자가 방금 끝난 자리(아래 단위표 가드용)
    while i < n:
        ch = s[i]
        # 공백(점자/일반)
        if ch == _SPACE_CELL or ch == " ":
            out.append(" ")
            i += 1
            continue
        # 페이지행 걸침 접두 알파벳 — 지침 1장2절2-2(3). 원본 한 쪽이 여러 점자 면에
        # 걸치면 두 번째 면부터 원본 쪽 번호 **앞에** 로마자표 없이 a·b·c… 를 적는다
        # (braille-assist `_alpha` 와 대칭). 종전에는 이 낱자가 어느 표에도 없어
        # `⟨2803⟩4` 로 샜다 — 실측 1,500쪽에 2,467건으로 미지셀 1위였다.
        # ★ **토큰 전체가 `낱자 + 수표 + 숫자`일 때만** 본다. 줄머리+수표만 보면
        #   `운6기`(⠛⠼⠋⠈⠕)의 ⠛ 를 g 로 읽어 한글이 깨진다(회귀 테스트가 잡았다).
        if i == 0 and ch in _ALPHA_REV and _CONT_PREFIX_RE.fullmatch(s):
            out.append(_ALPHA_REV[ch])
            i += 1
            continue
        # 줄 단위 선처리가 넣어 둔 글자(네모 빈칸 ▯ · 곱셈표 × · 도형 틀 ○□△◇)는
        # 그대로 흘린다. _mark_paren_pairs 의 센티넬까지 통과시키면 괄호 복원이
        # 깨지므로 좁게 잡는다.
        if ch in "▯×○□△◇":
            out.append(ch)
            i += 1
            continue
        # 점형표 — 규정 제67항. 표 뒤 한 칸까지가 묵자에 실린 **점형 그 자체**다.
        if s[i:i + 2] == _CELLFORM_IND:
            j = i + 2
            while j < n and s[j] not in (" ", _SPACE_CELL):
                j += 1
            out.append(s[i + 2:j])
            i = j
            continue
        # 네모 문자 — 규정 제64항 "네모 문자는 _8 0l으로 묶어 나타낸다"(⠸⠦ … ⠴⠇).
        # 정방향은 translator._TAGS.BOX_CHAR 가 이 쌍을 낸다. 역방향에 짝이 없어
        # ⠸ 가 수학표의 log 로 새고 ⠴ 가 로마자표로 읽혀 `log"1l` 이 됐다 —
        # 코퍼스 전수에서 '그림 마커 미복원' 1만 건대의 주범이다.
        if s[i:i + 2] == _BOX_CHAR_OPEN:
            j = s.find(_BOX_CHAR_CLOSE, i + 2)
            if j > 0:
                out.append("▯" + _decode_line(s[i + 2:j]) + "▯")
                i = j + 2
                continue
        # 짝이 없는 ⠸⠦ 는 네모 문자가 아니라 **단독 물음표**다(제49항 [붙임]).
        # ★ **뒤가 빈칸이나 줄끝일 때만** 편다. 규정이 "문장 부호 뒤에 한 칸을 띈 후
        #   명칭을 점역자 주표로 묶는다"고 정한 그 자리다. 뒤에 글자가 바로 붙으면
        #   그건 **줄을 넘는 네모 문자의 여는 쪽**이다 — 닫는 `⠴⠇` 가 다음 줄에 있어
        #   위 분기가 못 잡는다. 실측: 짝 없는 ⠸⠦ 207회 중 빈칸/줄끝 앞이 105회다.
        #   구분을 안 하면 `⠸⠦조직 세포` 가 `?조직 세포` 로 깨진다(001 p0031).
        if (s[i:i + 2] in _LONE_PUNCT_REV
                and s[i + 2:i + 3] in ("", _SPACE_CELL, " ", "\n")):
            out.append(_LONE_PUNCT_REV[s[i:i + 2]])
            i += 2
            continue
        # 로그 — 「수학 점자」 제46항. ⠸ 뒤가 **수표**면 밑 없는 상용로그다.
        # ★ 홑 ⠸ 를 log 로 두는 안은 **기각된 이력이 있다**(코퍼스 전수 105,453자 유출).
        #   ⠸ 가 도형 접두·약어·지시부호로 흔하기 때문이다. 그래서 **수표 앞으로 한정**한다 —
        #   ⠸⠼ 는 도형(⠸+도형셀)·네모 문자(⠸⠦)·한글표(⠸⠷) 어느 것도 아니다.
        #   실측: 네모 문자 쌍을 걷은 뒤 ⠸⠼ **78회·9쪽**이고 전부 수학I 이다.
        if ch == "⠸" and s[i + 1:i + 2] in _LOG_NEXT:
            out.append("log ")
            i += 1
            continue
        # 점역자 주 마커
        if s[i:i + 2] == _TN_MARKER:
            out.append("【점역자주】")
            i += 2
            continue
        # 옛한글(제19~25항) — 아래아·ㅸ·ㅿ. ⠐⠼ 를 쉼표+수표로 쪼개던 자리다
        # (`ᄋᆞᆯ` → `,①` · `ᄒᆞ` → `하,⟨⠼⟩` · `ㅸ` → `옹,방`).
        _old = _old_hangul_at(s, i)
        if _old:
            out.append(_old[0])
            i = _old[1]
            continue
        # 대문자 로마자 처리는 폐기(2026-07-18): ⠠는 한글 음절 구성요소(수=⠠⠍)이기도 해
        # ⠠+알파를 대문자로 보면 정상 한글을 깬다(국수→국M, 따님→I님). roundtrip 회귀.
        # 로마자 대문자는 ⠴…⠲ 로마자 런 안에서만 처리(맥락 있음).
        # 동그라미 숫자·문자·낱자(제64항) — 수표/온표보다 먼저(①=⠼⠂ 가 평문 숫자로,
        # ㉠=⠿⠁ 이 ∞로 오인되지 않게). 긴 셀 우선.
        # 모음 낱자(제7항) — 양옆이 경계일 때만. ⠿는 약자 '옹'이기도 해 무조건 펴면
        # `옹알이`가 깨진다(위 _VOWEL_JAMO_REV 주석의 실측 근거).
        if ch == "⠿" and (i == 0 or s[i - 1] in _JAMO_BOUND):
            for ln in range(min(_VOWEL_JAMO_MAX, n - i), 1, -1):
                tok = s[i:i + ln]
                if tok in _VOWEL_JAMO_REV and (i + ln >= n or s[i + ln] in _JAMO_BOUND):
                    out.append(_VOWEL_JAMO_REV[tok])
                    i += ln
                    break
            else:
                ln = 0
            if ln:
                continue
        _sp = _special_at(s, i)
        if _sp:
            out.append(_sp[0])
            i = _sp[1]
            continue
        # 수표 숫자 — 동그라미숫자 기호(①=⠼⠉ 등)보다 먼저(평문 숫자가 흔함).
        if ch == _NUMBER_SIGN:
            txt, j = _decode_number(s, i)
            out.append(txt)
            _after_number = j          # 이 자리 바로 뒤는 단위가 올 수 있다(아래 참조)
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
        # ★ **숫자 바로 뒤의 ⠴ 는 단위표다. 로마자표가 아니다.**(2026-08-25)
        #   규정 [붙임2]가 비로마자 단위를 `숫자 + 단위표 0 + …` 로 적는다(50%=⠼⠑⠚⠴⠏).
        #   로마자표는 반대로 **런 앞**에 온다(제35항 A4=⠴⠠⠁⠼⠙ · MP3) — 숫자 뒤에 붙는
        #   ⠴ 를 로마자표로 읽을 자리가 규정에 없다.
        #   이 가드가 없으면 종료표 ⠲ 가 마침표와 같은 셀이라 로마자 런이 **뒤 한글까지
        #   통째로 삼킨다**. 실측(코퍼스 900쪽 표본): `%` 뒤가 한글인 줄 118건 중
        #   **69건(58%)에서 `%` 가 사라지고 뒤 한글이 깨졌다**
        #   (`25%이다.` → `25poi` · `5%이므로` → `5poeow로`).
        if ch == _ROMAN_START and best_ln >= 2 and i == _after_number:
            pass                       # 단위로 읽는다(아래 기호 분기로 떨어진다)
        elif (ch == _ROMAN_START and best_ln >= 2
              and (i == 0 or s[i - 1] in (_SPACE_CELL, " "))):
            # ★ 로마자표는 **낱말 앞**에 온다(제29항). 낱말 중간의 ⠴ 는 닫는 낫표·
            #   따옴표다 — `_merge_roman_tokens`·단축형 판정이 이미 쓰는 원칙이다.
            #   이 조건이 없으면 "긴 쪽이 이긴다"가 뒤집힌다: `『황명세법』을`
            #   (…⠴⠆⠮)에서 ⠆=be·⠮=the 로 3셀을 먹어 `『황명세법bethe` 가 나갔다.
            _r = _decode_roman_run(s, i)
            if _r is not None and _r[1] - i > best_ln:
                out.append(_r[0])
                i = _r[1]
                continue

        # 닫는 홑화살괄호 ⠶⠂ — 규정 문장부호표(규정_텍스트.txt 2191~2192).
        # ⠶ 는 **받침 ㅇ과 같은 셀**이라 탐욕 매칭이 앞 음절에 붙여 먹는다(보기〉 → 보깅,).
        # 다만 `강,`(받침 ㅇ + 쉼표)와 셀이 겹치므로 **앞에 닫히지 않은 〈 가 있을 때만** 부호로 본다.
        # 실측 dev-2027 900쪽: gold 가 〈보기〉를 702회 쓴다(작은따옴표꼴 0회).
        if (best_ln >= 2 and s[i + best_ln:i + best_ln + 1] == "⠂"
                and s[i + best_ln - 1] == "⠶" and s[i:i + best_ln - 1] in _COMBINED
                and s.count("⠐⠶", 0, i) > "".join(out).count("〉")):
            out.append(_COMBINED[s[i:i + best_ln - 1]])
            out.append("〉")
            i += best_ln + 1
            continue

        # 닫는 작은따옴표 ⠴⠄ — 규정 문장부호표의 `0'`(규정_텍스트.txt 2147~2154).
        # ⠴는 **받침 ㅎ과 같은 셀**이라 탐욕 매칭이 앞 음절에 붙여 먹는다(기’ → 깋').
        # 뒤 셀이 ⠄면 부호가 맞다 — 홀로 선 ⠄는 한국어 음절에 없다.
        # 실측 dev-2027 900쪽: gold 1,933줄 · 우리 출력 2,305줄이 이 한 가지로 깨졌다.
        if (best_ln >= 2 and s[i + best_ln:i + best_ln + 1] == "⠄"
                and s[i + best_ln - 1] == "⠴" and s[i:i + best_ln - 1] in _COMBINED):
            out.append(_COMBINED[s[i:i + best_ln - 1]])
            out.append("’")
            i += best_ln + 1
            continue

        if best_ln >= 2:
            seg = s[i:i + best_ln]
            # 마침표가 음절 뒤에 붙어 다른 음절로 오인된 경우 분리(다.=닾 → 다 + .).
            # ?·!(⠦·⠖)은 받침과 충돌(같=⠫⠦)하므로 **어말일 때만** 분리(요?=⠬⠦ → 요 + ?).
            # ★기호로 등록된 시퀀스(≥=⠲⠲, ⊃=⠐⠲, ㎏=…⠲ 등)는 분리하지 않는다(2026-07-19).
            if seg[-1] == "⠲" and seg in _SYMBOL_REV:
                out.append(_SYMBOL_REV[seg])
            elif (seg[-1] == "⠲" and seg[:-1] in _COMBINED
                  and (_COMBINED.get(seg) not in _PIEUP_FINAL
                       # ★ 받침 ㅍ 음절이라도 **낱말 끝에 못 서는 어간**이면 온점이다.
                       #   `있어.` 가 `있엎` 으로, `밝혀야지.` 가 `밝혀야짚` 으로 나갔다.
                       or (_COMBINED.get(seg) in _PIEUP_STEM_ONLY
                           and (_final(i + best_ln)
                                or _closing_follows(s, i + best_ln))))):
                # ⠲는 마침표이자 **받침 ㅍ**이라(높=⠉⠥⠲) 무조건 분리하면 받침 ㅍ이 든 말이
                # 전부 깨진다(높다→'노.다' · 앞으로→'아.으로'). 위치로 가르면 닫는 따옴표
                # 앞에서 또 틀리므로(`나타난다.’`→`나타난닾’`) **실제로 쓰이는 받침 ㅍ 음절**
                # 목록으로 가른다 — 닫힌 집합이라 안전하다. 승패: 개선 58 · 악화 0.
                out.append(_COMBINED[seg[:-1]])
                out.append(".")
            elif (seg[-1] == "⠴" and seg[:-1] in _COMBINED
                  and seg not in _SYMBOL_REV
                  and (_COMBINED.get(seg) not in _HIEUT_FINAL
                       # ★ 받침 ㅎ 음절이 목록에 있어도, 뒤 셀이 ⠂ 면 닫는 홑낫표
                       #   `」`(⠴⠂)가 맞다. `국가」라는` 이 `국갛,라는` 으로 나갔다.
                       #   실측(전 코퍼스 1,131쪽): 점자 ⠴⠂ **187건** · 묵자 `」`
                       #   **189건** 으로 사실상 1:1 이다. 받침 ㅎ + 쉼표는 그 사이에
                       #   묻힐 만큼 드물다.
                       or s[i + best_ln:i + best_ln + 1] == "⠂")):
                # ⠴는 닫는 큰따옴표이자 **받침 ㅎ**이라(좋=⠨⠥⠴) 탐욕 매칭이 앞 음절에
                # 붙여 먹는다. 받침 ㅍ과 같이 **실제로 쓰이는 음절 목록**으로 가른다.
                out.append(_COMBINED[seg[:-1]])
                # ★ 떼어낸 ⠴ 가 **뒤 셀과 함께 등록된 기호**를 이루면(』=⠴⠆ · ’=⠴⠄)
                #   여기서 닫는 큰따옴표로 굳히면 안 된다. 한 칸 물러나 다음 바퀴가
                #   두 셀로 읽게 둔다 — `『천연론』` 이 `『천연론”;` 로 나가던 자리다.
                if ("⠴" + s[i + best_ln:i + best_ln + 1]) in _COMBINED:
                    i += best_ln - 1
                    continue
                out.append("”")
            elif (seg[-1] == "⠦" and seg[:-1] in _COMBINED
                  and s[i + best_ln:i + best_ln + 1] in ("⠄", "⠆")):
                # ⠦ 는 **받침 ㅌ**(제3항)이자 여는 소괄호 `⠦⠄`·여는 대괄호 `⠦⠆` 의 첫
                # 셀이다. 짝을 못 찾으면 탐욕 매칭이 앞 음절에 받침으로 붙여 먹는다 —
                # `구체(` → `구쳍'` · `중도[중]` → `중돝;중]`. 남은 ⠄·⠆ 는 `'`·`;` 로 샜다.
                # 홀로 선 ⠄·⠆ 는 한국어 음절에 없으므로(닫는 작은따옴표 ⠴⠄ 가드와 같은
                # 근거) 뒤 셀이 ⠄·⠆ 면 부호가 맞다.
                out.append(_COMBINED[seg[:-1]])
                i += best_ln - 1     # 한 칸 물러나 다음 바퀴가 두 셀 부호로 읽게 둔다
                continue
            elif (seg in _SYLLABLE_REV and seg[-1] in _SENT_END
                  and seg[:-1] in _COMBINED
                  and (_final(i + best_ln)
                       # ★ 느낌표 ⠖ 는 받침 ㅋ 과 같은 셀인데 받침 ㅋ 음절은 국어에
                       #   `엌·녘` 둘뿐이다. 닫는 부호 앞이면 부호로 본다 —
                       #   `하라!”` 가 `랔”`, `…뭐!)` 가 `…뭌)` 로 나갔다.
                       or (seg[-1] == "⠖" and _COMBINED[seg] not in _KIEUK_FINAL
                           and _closing_follows(s, i + best_ln)))):
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
        # 어말 마침표 ⠲ — ∋ 기호와 같은 점형이라, 앞에 텍스트가 있고 어말일 때만
        # 마침표로 본다(곳.=…⠲ → 곳 + .). 단독 ⠲(앞이 비었거나 공백)는 기호(∋)로 둔다.
        # ★ '어말'에 **뒤따르는 닫는 부호**를 넣는다(2026-09-03). 종전에는 끝·공백만 봐서,
        #   마침표 바로 뒤에 점역자 주표나 닫는 괄호가 오면 ∋ 로 샜다 —
        #   `열을 바꾸었음∋【점역자주】`. 실측(gold 시각자료): ⠠⠄ 78 · ⠠⠴ 22 자리.
        #   근거: 재추출 묵자 1,361쪽에 마침표 29,887회 · ∋ **0회**. 이 코퍼스에 집합
        #   기호는 없다. 수식 토큰은 앞단(_MATH_REV)에서 갈리므로 여기 안 온다.
        if ch == _ROMAN_END and out and out[-1] != " " and (
                _final(i + 1) or _closing_follows(s, i + 1)):
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
        # 낱자 폴백 — 여기까지 왔다는 건 **한글로도 기호로도 안 풀렸다**는 뜻이다.
        # 그 자리가 로마자 낱자 점형이면 낱자로 낸다. 수식 속 변수(`b=2`·`k=1`)가
        # 미지셀로 나가던 자리다 — 한글은 이미 실패했으므로 잃을 것이 없다.
        # ⚠ 토큰을 통째로 수식으로 올리는 안은 **기각했다**(실측 이득 723 · 손해 1,199).
        #   `수컷(2n=12+XY)의` 같은 한글 섞인 줄이 통째로 로마자로 뒤집혔다.
        if os.environ.get("BRAILLE_ALPHA_FALLBACK", "1") == "1" and ch in _ALPHA_REV:
            out.append(_ALPHA_REV[ch])
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
