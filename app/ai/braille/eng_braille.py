"""영어 점자 Grade 2(약자 점역) — 국어 문장 속 영어 구간 전담 모듈.

**권위**: 한국 점자 규정 [부록 1] 외국어 점자 제1항 — "외국어 점자는 해당 국가의 점자
규정에 따라 적는다". 부록의 영어 절(제2장 제1절)은 알파벳과 문장 부호만 정하고 약자는
정하지 않으므로, 약자는 영어권 표준(English Braille Grade 2)을 따른다. 즉 이 표의
정본은 한국 규정이 아니라 영어 점자 표준이며, 코퍼스와 독립이라 과적합 소지가 없다.

**왜 별도 모듈인가**: 종전에는 영어 구간도 braillify(한국 점자 엔진)가 처리했는데,
letter-group 약자(th·ed·st·er·ow·en·in·ch·gh·be)만 구현돼 단어 약자·어미 약자·단축형이
통째로 빠져 있었다(실측 2026-07-19: the → ⠹⠑ 출력, 정답 ⠮ / running → …⠔⠛, 정답 ⠬).
수식을 kor_math_rules가 소유하듯 영어는 이 모듈이 소유한다 — translator는 구간을 넘기고
결과만 받는다.

**셀 충돌 규칙**: 이 파일의 표들은 같은 점형을 여러 항목이 쓰는 일이 정상이다 — 알파벳
↔ 단독 단어 약자(⠃=b/but), 강약자 ↔ 단독 단어 약자(⠡=ch/child), 아래칸 약자 ↔ 첫머리
음절 약자(⠆=bb/be)는 **위치·단독 여부로 갈리므로** 영어 점자 표준 그대로다. 반면
**같은 dict·같은 위치 계층에서 셀이 겹치면 오류다** — ble/gg가 둘 다 ⠶였던 것이 그 예다
(2026-07-27 정정, 전수 점검 스크립트 `V2/temp/i2_cellaudit.py`).

**ble = 3456점(⠼) 근거**: EBAE(구 영어 점자)에서 ble은 3456점이다 — UEB 해설이
"the former 'ble' contraction, dots 3456, is defined as a prefix in UEB"라고 명시한다
(duxburysystems.com/js-adapting_UEB.asp). UEB는 이 약자를 폐지했으나 이 표는 ation·ally와
같은 이유로 **EBAE 관행을 따른다**(정답 코퍼스가 EBAE형이다). 코퍼스 실측도 같은 방향:
-ble 낱말의 gold 점형은 ⠼형 133건 : ⠶형 0건(val 116:0 · dev 17:0).

**적용 순서**(영어 점자 표준의 우선순위):
  1. 단독 단어 약자(alone)      — 앞뒤가 공백/문장부호일 때만
  2. 단축형(short form)          — 단어 전체가 일치할 때만
  3. 강약자(strong groups)       — 위치 무관, 긴 것 우선
  4. 첫글자 약자 / 끝글자 약자   — 위치 제약(첫/끝 음절 근처)
  5. 남은 글자 → 알파벳
"""
from __future__ import annotations

import re
from functools import lru_cache
from typing import Iterator

_CAPITAL = "⠠"          # 대문자 기호표 (규정 부록1 영어 절)

ALPHABET: dict[str, str] = {
    "a": "⠁", "b": "⠃", "c": "⠉", "d": "⠙", "e": "⠑", "f": "⠋", "g": "⠛",
    "h": "⠓", "i": "⠊", "j": "⠚", "k": "⠅", "l": "⠇", "m": "⠍", "n": "⠝",
    "o": "⠕", "p": "⠏", "q": "⠟", "r": "⠗", "s": "⠎", "t": "⠞", "u": "⠥",
    "v": "⠧", "w": "⠺", "x": "⠭", "y": "⠽", "z": "⠵",
}

# ── 1. 강약자(strong contractions) — 단어 어디에 있어도 쓴다 ──────────────────
STRONG_GROUPS: dict[str, str] = {
    "and": "⠯", "for": "⠿", "of": "⠷", "the": "⠮", "with": "⠾",
    "ch": "⠡", "gh": "⠣", "sh": "⠩", "th": "⠹", "wh": "⠱",
    "ed": "⠫", "er": "⠻", "ou": "⠳", "ow": "⠪",
    "st": "⠌", "ing": "⠬", "ar": "⠜",
    "bb": "⠆", "cc": "⠒", "ff": "⠖", "gg": "⠶",
    "in": "⠔", "en": "⠢",
    "ea": "⠂",
}
# ble = 3456점(⠼) — EBAE 약자다. **UEB 가 폐지했다**(#946, 규정 제29항 예문 `Table of Contents` =
#   ⠠⠞⠁⠃⠇⠑…). 정방향은 쓰지 않고, 역점역이 옛 EBAE 책을 되짚을 때만(`ebae=True`) 쓴다 — ation·ally(#932)와 같은 처리.
#   2027 dev·val 묵자에 -ble 낱말은 0회다. ⠼는 한글 점자에서 수표(제40항)와 같은 점형이라 number_sign.py 가 가른다.
# dd(⠲)도 UEB 가 폐지했다(#1167) — gold 영어책은 `middle` 을 ⠍⠊⠙⠙⠇⠑ 로 풀어 쓴다.
EBAE_ONLY_GROUPS: dict[str, str] = {"ble": "⠼", "dd": "⠲"}
# 아래칸 약자(ea·bb·cc·dd·ff·gg)는 **낱말 첫머리·끝에 못 쓴다**(영어 점자 표준).
# 위아래 칸이 비어 다른 셀과 혼동되기 때문이다.
_LOWER_CELL = {"ea", "bb", "cc", "dd", "ff", "gg"}
# 낱말 첫머리 전용 음절 약자 — 같은 셀이 낱말 중간에서는 겹자음(bb·cc·dd) 뜻이라
# 위치로 갈린다(영어 점자 표준). be/con/dis 는 첫머리에서만 쓴다.
WORD_INITIAL_SYLLABLE: dict[str, str] = {"be": "⠆", "con": "⠒", "dis": "⠲"}
# com(⠤)은 UEB 가 폐지했다(#1167) — gold 영어책 `company` = ⠉⠕⠍⠏⠁⠝⠽. 역점역(`ebae=True`)만 쓴다.
EBAE_ONLY_INITIAL: dict[str, str] = {"com": "⠤"}
# 위치 제약: 낱말 첫머리에는 쓰지 않는 약자(영어 점자 표준).
_NOT_WORD_INITIAL = {"ing", "ble"} | _LOWER_CELL

# ── 2. 단독 단어 약자(alone) — 그 낱말 하나로 설 때만 ────────────────────────
WORDSIGNS: dict[str, str] = {
    "but": "⠃", "can": "⠉", "do": "⠙", "every": "⠑", "from": "⠋", "go": "⠛",
    "have": "⠓", "just": "⠚", "knowledge": "⠅", "like": "⠇", "more": "⠍",
    "not": "⠝", "people": "⠏", "quite": "⠟", "rather": "⠗", "so": "⠎",
    "that": "⠞", "us": "⠥", "very": "⠧", "will": "⠺", "it": "⠭",
    "you": "⠽", "as": "⠵", "child": "⠡", "shall": "⠩", "this": "⠹",
    "which": "⠱", "out": "⠳", "still": "⠌", "enough": "⠢", "were": "⠶",
    "his": "⠦", "in": "⠔", "was": "⠴", "be": "⠆",
}
# 아래칸 단어기호 to·by·into — EBAE 는 뒤 낱말에 붙여 적었다. **UEB 가 폐지했다**(#1167).
#   「한국 점자 규정」 제7항(99행)·제28항(1329행)이 로마자를 「통일영어점자 규정」에 맡긴다.
#   gold 영어책 12권 영어 줄: `to` 풀어씀 ⠞⠕ 6,777 : ⠖ 0 · `by` ⠃⠽ 929 : 0(holdout 제외, 2026-10-07).
#   정방향은 쓰지 않고, 역점역이 옛 EBAE 책을 되짚을 때만(`ebae=True`·역맵) 쓴다 — ble·ation 과 같은 처리.
EBAE_ONLY_WORDSIGNS: dict[str, str] = {"to": "⠖", "by": "⠴", "into": "⠔⠖"}

# ── 3. 첫글자 약자 — 기호표 + 첫 글자 ────────────────────────────────────────
INITIAL_5: dict[str, str] = {          # 점5(⠐) + 글자
    "day": "⠙", "ever": "⠑", "father": "⠋", "here": "⠓", "know": "⠅",
    "lord": "⠇", "mother": "⠍", "name": "⠝", "one": "⠕", "part": "⠏",
    "question": "⠟", "right": "⠗", "some": "⠎", "time": "⠞", "under": "⠥",
    "work": "⠺", "young": "⠽", "there": "⠮", "character": "⠡", "through": "⠹",
    "where": "⠱", "ought": "⠳",
}
INITIAL_45: dict[str, str] = {         # 점45(⠘) + 글자
    "upon": "⠥", "word": "⠺", "these": "⠮", "those": "⠹", "whose": "⠱",
}
INITIAL_456: dict[str, str] = {        # 점456(⠸) + 글자
    "cannot": "⠉", "had": "⠓", "many": "⠍", "spirit": "⠎", "world": "⠺",
    "their": "⠮",
}

# ── 4. 끝글자 약자 — 기호표 + 글자 (낱말 끝·중간) ────────────────────────────
FINAL_46: dict[str, str] = {           # 점46(⠨) + 글자
    "ound": "⠙", "ance": "⠑", "sion": "⠝", "less": "⠎", "ount": "⠞",
}
FINAL_56: dict[str, str] = {           # 점56(⠰) + 글자
    "ence": "⠑", "ong": "⠛", "ful": "⠇", "tion": "⠝", "ness": "⠎",
    "ment": "⠞", "ity": "⠽",
}
# ⚠ ation·ally 는 EBAE에 있고 UEB에서 폐지됐다. **정방향 점역에는 쓰지 않는다**(#932 · 원장 R-79).
#   「한국 점자 규정」 제28항이 로마자를 「통일영어점자 규정」(UEB)에 맡긴다. 종전엔 쓰고 있었는데
#   근거('코퍼스가 구 EBAE 관행')가 구판(2012) 실측이었다. 2027 gold 는 ation/ally 낱말 7개 중
#   EBAE꼴 0 · UEB꼴 6(`globalization` = …⠵⠁⠰⠝). 사전은 남긴다 — 역점역(`braille_back`)이
#   옛 EBAE 책을 읽을 때 쓴다.
FINAL_EBAE_ONLY: dict[str, str] = {"ation": "⠠⠝", "ally": "⠠⠽"}

# ── 5. 단축형(short form) — 낱말 전체가 일치할 때만 ──────────────────────────
SHORT_FORMS: dict[str, str] = {
    "about": "⠁⠃", "above": "⠁⠃⠧", "according": "⠁⠉", "across": "⠁⠉⠗",
    "after": "⠁⠋", "afternoon": "⠁⠋⠝", "afterward": "⠁⠋⠺", "again": "⠁⠛",
    "against": "⠁⠛⠌", "almost": "⠁⠇⠍", "already": "⠁⠇⠗", "also": "⠁⠇",
    "although": "⠁⠇⠹", "altogether": "⠁⠇⠞", "always": "⠁⠇⠺",
    # before = bef(⠆⠋) — 통일영어점자 단축형. 종전 ⠆⠿(be+for 를 이어 붙인 꼴)는 단축형이 아니다(#1184).
    #   gold 영어책(holdout 제외) 홀로 선 ⠆⠋ 343 : ⠆⠿ 0. beforehand 도 bef 를 그대로 쓴다(gold ⠆⠋⠓⠯).
    "because": "⠆⠉", "before": "⠆⠋", "beforehand": "⠆⠋⠓⠯", "behind": "⠆⠓", "below": "⠆⠇",
    "beneath": "⠆⠝", "beside": "⠆⠎", "between": "⠆⠞", "beyond": "⠆⠽",
    "blind": "⠃⠇", "braille": "⠃⠗⠇", "children": "⠡⠝", "conceive": "⠒⠉⠧",
    "could": "⠉⠙", "deceive": "⠙⠉⠧", "declare": "⠙⠉⠇", "either": "⠑⠊",
    "first": "⠋⠌", "friend": "⠋⠗", "good": "⠛⠙", "great": "⠛⠗⠞",
    "herself": "⠓⠻⠋", "him": "⠓⠍", "himself": "⠓⠍⠋", "immediate": "⠊⠍⠍",
    "its": "⠭⠎", "itself": "⠭⠋", "letter": "⠇⠗", "little": "⠇⠇",
    "much": "⠍⠡", "must": "⠍⠌", "myself": "⠍⠽⠋", "necessary": "⠝⠑⠉",
    "neither": "⠝⠑⠊", "oneself": "⠐⠕⠋", "ourselves": "⠳⠗⠧⠎",
    "paid": "⠏⠙", "perceive": "⠏⠻⠉⠧", "perhaps": "⠏⠻⠓", "quick": "⠟⠅",
    "receive": "⠗⠉⠧", "rejoice": "⠗⠚⠉", "said": "⠎⠙", "should": "⠩⠙",
    "such": "⠎⠡", "themselves": "⠮⠍⠧⠎", "thyself": "⠹⠽⠋", "today": "⠞⠙",
    "together": "⠞⠛⠗", "tomorrow": "⠞⠍", "tonight": "⠞⠝", "would": "⠺⠙",
    "your": "⠽⠗", "yourself": "⠽⠗⠋", "yourselves": "⠽⠗⠧⠎",
}

_WORD_RE = re.compile(r"[A-Za-z']+")
# 낱말 **안**의 아포스트로피 — 양옆이 로마자일 때만(제61항 ⠄). 홀로 선 `'` 는 제49항
# 작은따옴표일 수 있어 여기 안 걸린다.
_INNER_APOS_RE = re.compile(r"(?<=[A-Za-z])'(?=[A-Za-z])")
_APOS_CELL = "⠄"


def iter_words(text: str) -> Iterator[str]:
    """text 안의 영어 낱말 토큰 — 이 모듈이 약자를 적용하는 단위 그대로.

    number_sign.py가 '영어 약자가 만든 ⠼'를 세는 데 쓴다(수표와 같은 점형이라 구분 필요).
    """
    return (m.group() for m in _WORD_RE.finditer(text))


# UEB — be(⠆)도 첫 음절을 이룰 때만 쓴다(#1180). gold 영어책(holdout 제외) 낱말 머리 be:
#   ⠆ — because 263 · being 114 · become 81 · became 73 · believe 58 · began 49 · below 48 · behind 40 …
#   풀어씀 — been 246 · better 184 · best 122 · beard 79 · beautiful 55 · beach 50 · benefits 32 · beauty 30 …
# 소리 마디를 철자로만 가르는 근사다: be 뒤가 홑 자음 + 모음(be-ca · be-li · be-ga · be-ne)이면 음절,
#   겹자음(bett · bell · begg)·모음(bea · bee)·낱말 끝 자음(bed · best)이면 아니다. being 은 음절이다.
#   철자로 안 갈리는 benefit(BEN-e-fit)은 목록으로 뺀다.
# ponytail: 철자 근사 — 발음 사전이 없어 be-n-e 꼴(benefit·beneath)은 목록으로만 가른다. 틀린 낱말이 보이면 목록에 더한다.
_BE_NOT_SYLLABLE = frozenset({"benefit", "benefits", "beneficial", "benefited", "benefiting", "benefactor"})
_VOWELS_Y = frozenset("aeiouy")


def _be_is_syllable(word: str) -> bool:
    if word.startswith("being"):
        return True
    if word in _BE_NOT_SYLLABLE:
        return False
    c, v = word[2:3], word[3:4]
    return bool(c) and c not in _VOWELS_Y and v in _VOWELS_Y and c != v


def _apply_groups(word: str, ebae: bool = False) -> str:
    """소문자 낱말 → 약자 적용 셀열. 긴 약자 우선, 위치 제약 준수.

    `ebae=True` 는 역점역 왕복 검사 전용이다 — 옛 EBAE 책 줄(`DON,N` = donation)을 되짚는다.
    """
    # 긴 약자 우선, 길이가 같으면 **윗칸 약자가 아래칸 약자보다 우선**한다.
    # year·near·clear에서 ar(⠜)이 ea(⠂)를 이겨야 한다(실측 12건: 우리 ⠂⠗ vs 정답 ⠑⠜).
    initial_syl = {**WORD_INITIAL_SYLLABLE, **EBAE_ONLY_INITIAL} if ebae else WORD_INITIAL_SYLLABLE
    keys = sorted(set(STRONG_GROUPS) | (set(FINAL_EBAE_ONLY) | set(EBAE_ONLY_GROUPS) if ebae else set())
                  | set(initial_syl)
                  | set(FINAL_46) | set(FINAL_56)
                  | set(INITIAL_5) | set(INITIAL_45) | set(INITIAL_456),
                  key=lambda k: (-len(k), k in _LOWER_CELL))
    out: list[str] = []
    i = 0
    while i < len(word):
        for k in keys:
            if not word.startswith(k, i):
                continue
            if k in initial_syl:
                # 첫머리 음절 약자는 뒤에 글자가 더 있어야 한다(be/con/dis 단독 아님)
                if i != 0 or len(word) <= len(k):
                    continue
                # UEB — 첫 음절을 이룰 때만 쓴다. `dish` 는 d-i-sh 라 dis 가 음절이 아니다
                #   (규정 제39항 예문 `dishes` = di%es, #950)
                if k == "dis" and word[3:4] == "h":
                    continue
                if k == "be" and not ebae and not _be_is_syllable(word):
                    continue
                out.append(initial_syl[k])
            elif k in STRONG_GROUPS or k in EBAE_ONLY_GROUPS:
                if i == 0 and k in _NOT_WORD_INITIAL:
                    continue
                if k in _LOWER_CELL:
                    if i + len(k) >= len(word):
                        continue    # 아래칸 약자는 낱말 끝에도 못 온다
                    # 한 칸 물러서면 윗칸 약자가 시작되는 자리면 그쪽을 쓴다.
                    # year는 y+ea+r(⠽⠂⠗)이 아니라 y+e+ar(⠽⠑⠜)이다(실측 12건).
                    if any(word.startswith(k2, i + 1)
                           for k2 in STRONG_GROUPS if k2 not in _LOWER_CELL):
                        continue
                out.append(STRONG_GROUPS.get(k) or EBAE_ONLY_GROUPS[k])
            elif k in FINAL_EBAE_ONLY:
                if i == 0:          # 끝글자 약자는 낱말 첫머리에 못 온다
                    continue
                out.append(FINAL_EBAE_ONLY[k])
            elif k in FINAL_46 or k in FINAL_56:
                if i == 0:
                    continue
                out.append(("⠨" + FINAL_46[k]) if k in FINAL_46 else ("⠰" + FINAL_56[k]))
            else:                    # 첫글자 약자 — 낱말 첫머리에서만
                if i != 0:
                    continue
                if k in INITIAL_5:
                    out.append("⠐" + INITIAL_5[k])
                elif k in INITIAL_45:
                    out.append("⠘" + INITIAL_45[k])
                else:
                    out.append("⠸" + INITIAL_456[k])
            i += len(k)
            break
        else:
            out.append(ALPHABET.get(word[i], word[i]))
            i += 1
    return "".join(out)


# 대문자 런 / 대문자 아닌 런 — 혼합 낱말의 대문자 표기 단위(#934)
_CASE_RUN_RE = re.compile(r"[A-Z]+|[^A-Z]+")


def _is_element_seq(word: str) -> bool:
    """낱말 전체가 원소 기호(대문자 + 소문자 0~1자)의 이음인가 — HCl·NaCl 은 예, ABd·SDGs 는 아니오."""
    from app.ai.braille.kor_math_rules import _ELEMENTS   # 순환 import 회피(지연)
    return bool(word) and all(t in _ELEMENTS for t in re.findall(r"[A-Z][a-z]?|.", word))


def _is_abbrev(word: str) -> bool:
    """약어·단위인가 — 전부 대문자(ATP·DNA)이거나 대소문자가 섞인 형태(mV·pH·mmHg).

    영어 점자에서 약어·기호는 약자로 줄이지 않는다. 첫 글자만 대문자인 보통 낱말
    (The·Korea)은 약어가 아니므로 제외한다.
    """
    letters = [c for c in word if c.isalpha()]
    if len(letters) < 2:
        return False
    if all(c.isupper() for c in letters):
        return True
    return any(c.isupper() for c in letters[1:])


def translate_word(word: str, ebae: bool = False) -> str:
    """영어 낱말 하나 → Grade 2 점자.

    약어·단위는 축약하지 않고 글자 그대로 적는다 — 축약하면 ATP·mV·pH·mmHg 같은
    과학 표기가 깨진다(표 축 실측 2026-07-19: 악화 셀이 전부 이 계열이었다).
    전부 대문자인 낱말은 대문자 단어표 ⠠⠠를 앞세운다(규정 제35항 [붙임]과 동형).
    """
    if not word:
        return ""
    # ── 낱말 안 아포스트로피 (#513 · 원장 R-26) ────────────────────────────────
    # 「한국 점자 규정」 제61항 — 아포스트로피(’)는 `'`(⠄) 한 칸이다. 종전에는 ASCII
    # 작은따옴표가 표에 없어 `ALPHABET.get(c, c)` 를 그대로 빠져나가 **점자 출력에
    # 점자가 아닌 글자**가 실렸다(`don't` -> ⠙⠕⠝'⠞).
    # ★ 자리마다 잘라 각각 점역하고 ⠄ 로 잇는다. 그러면 본문 경로(`translator`)가
    #   이미 내던 답과 **한 글자도 안 달라진다** — 그쪽은 라틴 런을 아포스트로피에서
    #   끊고 `_span_gap` 이 ⠄ 를 내므로 결과가 같은 꼴이다(실측 11낱말 전부 일치:
    #   don't · It's · we've · patient's · I'll · they're · world's · can't · isn't ·
    #   you're · O'Brien). 곧 이 수정은 **두 경로를 같게 맞추는 것**이지 본문 출력을
    #   바꾸는 것이 아니다.
    # ⚠ 낱말 **안**(양옆이 로마자)일 때만이다. 홀로 선 `'` 는 제49항 작은따옴표일 수
    #   있어 건드리지 않는다.
    if _INNER_APOS_RE.search(word):
        return _APOS_CELL.join(translate_word(p, ebae) for p in _INNER_APOS_RE.split(word))
    letters = [c for c in word if c.isalpha()]
    if _is_abbrev(word):
        if all(c.isupper() for c in letters):
            return "⠠⠠" + "".join(ALPHABET.get(c.lower(), c) for c in word)
        # 대소문자 혼합(mV·mmHg·ABd) — 약자는 쓰지 않는다. 대문자 표기는 통일영어점자대로(#934):
        #   홑 대문자는 ⠠ 하나(mV·AaBb), 둘 이상 이어지면 대문자 단어표 ⠠⠠ 를 쓰고
        #   같은 낱말에 소문자가 이어지면 대문자 종료표 ⠠⠄ 로 닫는다.
        #   2027 gold: `ABd` = ⠠⠠⠁⠃⠠⠄⠙ · `HFCs` = ⠠⠠⠓⠋⠉⠠⠄⠎ · `SDGs` = ⠠⠠⠎⠙⠛⠠⠄⠎.
        #   ⚠ 원소 기호로 끊기는 낱말(HCl · NaCl · CaCO)은 종전대로 원소마다 ⠠ 다 — 「과학 점자」
        #   제1항이 원소 기호를 제29항 로마자로 적게 하고 gold 도 `HCl` = ⠠⠓⠠⠉⠇ 로 쓴다.
        if _is_element_seq(word):
            return "".join((_CAPITAL + ALPHABET.get(c.lower(), c)) if c.isupper()
                           else ALPHABET.get(c, c) for c in word)
        out = []
        for m in _CASE_RUN_RE.finditer(word):
            run = m.group()
            cells = "".join(ALPHABET.get(c.lower(), c) for c in run)
            if not run[0].isupper():
                out.append(cells)
            elif len(run) == 1:
                out.append(_CAPITAL + cells)
            else:
                out.append(_CAPITAL * 2 + cells + ("⠠⠄" if m.end() < len(word) else ""))
        return "".join(out)
    low = word.lower()
    caps = _CAPITAL if word[0].isupper() else ""
    if low in WORDSIGNS:
        return caps + WORDSIGNS[low]
    if ebae and low in EBAE_ONLY_WORDSIGNS:
        return caps + EBAE_ONLY_WORDSIGNS[low]
    if low in SHORT_FORMS:
        return caps + SHORT_FORMS[low]
    return caps + _apply_groups(low, ebae)


# 1종 지시자 ⠰ (「한글 점자」 제32항 → 통일영어점자 위임 · 원장 C-99) ─────────────────────
# 홀로 선 낱자·낱자열이 약자와 셀이 같으면 약자로 읽힌다(V = very · CD = could · AB = about).
# 그 앞에 ⠰ 를 적어 "글자 그대로" 임을 밝힌다. 표에서 뽑으므로 a·i·o(약자 아님)는 저절로 빠진다.
_GRADE1 = "⠰"
_WORDSIGN_CELLS = frozenset(v for v in WORDSIGNS.values() if len(v) == 1 and v in ALPHABET.values())
_SHORTFORM_CELLS = frozenset(v for v in SHORT_FORMS.values() if all(c in ALPHABET.values() for c in v))
# 10.9.3 — 긴 낱말 안에서도 쓰는 단축형(글자로만 된 것). (셀, 어디서나 쓰는가)
_SHORTFORM_HEADS = tuple((SHORT_FORMS[w], w in ("braille", "great"))
                         for w in ("braille", "great", "blind", "friend", "good", "letter", "little", "quick"))
_VOWEL_Y_CELLS = frozenset(ALPHABET[c] for c in "aeiouy")


def _looks_contracted(word: str) -> bool:
    """글자 그대로 적은 낱말이 약자와 셀이 같은가 — 홑 낱자는 단어 약자, 둘 이상은 단축형."""
    if not (word.isascii() and word.isalpha()):
        return False
    # 낱말 안쪽 대문자는 대문자표 ⠠ 가 셀 사이에 끼어 약자 모양이 깨진다 — `aB` = ⠁⠠⠃ 는 about(⠁⠃)로
    #   안 읽힌다. gold 001 p0115 유전자형 `AB, Ab, aB, ab` 도 aB 만 ⠰ 가 없다.
    if len(word) > 1 and not (word.isupper() or word[1:].islower()):
        return False
    cells = "".join(ALPHABET[c] for c in word.lower())
    if cells in (_WORDSIGN_CELLS if len(word) == 1 else _SHORTFORM_CELLS):
        return True
    # 통일영어점자 10.9.5 — 단축형으로 **시작하는** 긴 낱자열도 적는다(`BLCUP` = ;,,blcup). 긴 낱말
    #   안에서 단축형으로 읽히는 것은 10.9.3 의 열 개뿐이라 그 앞머리만 본다: braille·great 는 늘,
    #   blind·friend·good·letter·little·quick 은 뒤가 모음·y 가 아닐 때. 2027 gold `GDP` ⠰ 12/12 ·
    #   10.9.3 밖(ABC·ABO·ABD) 0/257(재현 `V2/temp/n14-acc/g1_prefix_measure.py`). 구판은 GDP 0/21(판본 역전).
    # ponytail: 실물이 전부 대문자 약어라 대문자 낱말만 본다 — 소문자 낱말은 약자 적용 경로가 따로다.
    return word.isupper() and any(cells.startswith(h) and (any_pos or cells[len(h):][:1] not in _VOWEL_Y_CELLS)
                                  for h, any_pos in _SHORTFORM_HEADS)


# 「한글 점자」 제37항(재추출 1795~1851행) — 로마자표 **바로 뒤** 영어 낱말은 단어 약자를 쓰지 않고
#   알파벳과 묶음 약자로 풀어 적는다(`Can you` = `0,can`y` · rather = `ra!r` · in = `in`).
#   [붙임](1847~1848행) be·enough·his·in·was·were 는 로마자 종료표 앞에서도 풀어 적는다 — 예문
#   `be, his, was, were의` = `0be1`his1`was1`w]e4w`. 쉼표에 붙은 자리도 풀었으므로 문장 부호에
#   닿은 자리 전부로 읽는다(통일영어점자의 아래칸 단어 약자 규칙과 같은 방향).
_LOWER_WORDSIGNS = frozenset({"be", "enough", "his", "in", "was", "were"})


def _spell_out(w: str, text: str, m: re.Match, lead: bool) -> bool:
    low = w.lower()
    if low not in WORDSIGNS or _is_abbrev(w):
        return False
    if lead and m.start() == 0:
        return True
    if low not in _LOWER_WORDSIGNS:
        return False
    before, after = text[m.start() - 1:m.start()], text[m.end():m.end() + 1]
    return m.end() == len(text) or (after and not after.isspace()) or (before and not before.isspace())


@lru_cache(maxsize=4096)
def translate(text: str, ebae: bool = False, grade1: str = "") -> str:
    """영어 구간 문자열 → Grade 2 점자(낱말 단위 적용, 그 외 문자는 그대로).

    캐시가 붙은 이유 — `_break_offsets`가 줄바꿈 지점을 찾으려고 문자 위치마다 접두를
    통째로 재점역한다(O(n²)). 접두는 매번 다르지만 그 안의 **영어 구간은 같은 것이
    반복**된다. 실측(표 요소 1,662자): 호출 69,853회 중 서로 다른 입력은 8개.
    캐시로 그 요소 점역이 2,056ms → 664ms(3.1배), 출력은 바이트 동일이다.

    순수 함수라 캐시가 안전하다 — 입력 문자열만 보고 모듈 전역 표(WORDSIGNS·SHORT_FORMS)로
    변환한다. 표가 런타임에 바뀌지 않으므로 무효화할 일이 없다.

    grade1 — 한국어 문장 속 로마자 구간에서만 켠다(`translator._split_english`). "lead" 는 이
    문자열이 로마자표 ⠴ 바로 뒤에서 시작한다는 뜻이고 "cont" 는 구간 안에서 이어진다는 뜻이다.
    규정 예문 여섯 곳과 2027 gold 가 같은 세 갈래다(재현 `V2/temp/n14-acc/g1_measure.py`):
      로마자표 바로 뒤 첫 홑 낱자는 안 적는다(`v-x` 의 v · 제36항 표 V)     gold 0/4,896
      이어지는 약자꼴 홑 낱자는 적는다(`a, b, c` 의 b·c · `George V`)       gold 347/347
      두 글자 이상 약자꼴은 로마자표 바로 뒤라도 적는다(`CD 1장`)           gold 100/102
    ⚠ 구판 gold 는 셋 다 안 적는다(판본 역전). 구판 수치로 판정하지 말 것.
    """
    words = list(_WORD_RE.finditer(text))
    passage: dict[int, str] = {}
    # 대문자 구절표(UEB, #946) — 대문자로만 된 낱말이 빈칸만 사이에 두고 셋 이상 이어지면 ⠠⠠⠠ 로 열고
    #   ⠠⠄ 로 닫는다. 규정 제28항 예문 `WELCOME TO KOREA` = ⠠⠠⠠⠺⠑⠇⠉⠕⠍⠑⠀⠞⠕⠀⠅⠕⠗⠑⠁⠠⠄.
    #   낱말마다 ⠠⠠ 를 붙이던 종전 꼴은 UEB 가 아니다. 쉼표 등이 끼면(`DNA, RNA, ATP`) 구절로 안 본다.
    #   두 글자 이상 낱말만 센다 — 홑 대문자 나열(`A B C D` 표 머리·라벨)은 종전대로 둔다.
    run: list[int] = []

    def _flush() -> None:
        if len(run) >= 3:
            for j, k in enumerate(run):
                cells = "".join(ALPHABET.get(c.lower(), c) for c in words[k].group())
                passage[k] = ("⠠⠠⠠" if j == 0 else "") + cells + ("⠠⠄" if j == len(run) - 1 else "")
        run.clear()

    for k, m in enumerate(words):
        w = m.group()
        # EBAE(옛 책 되짚기)는 낱말마다 ⠠⠠ 다. 홑 대문자 나열(`A B C D` 라벨)은 구절이 아니다(2027 실물 001 p0156).
        caps = not ebae and len(w) >= 2 and w.isalpha() and w.isupper()
        if caps and run and text[words[run[-1]].end():m.start()].strip(" ") == "":
            run.append(k)
            continue
        _flush()
        if caps:
            run.append(k)
    _flush()
    out: list[str] = []
    last = 0
    for k, m in enumerate(words):
        out.append(text[last:m.start()])
        w = m.group()
        mark = (grade1 and not ebae and k not in passage and _looks_contracted(w)
                and not (grade1 == "lead" and k == 0 and m.start() == 0 and len(w) == 1))
        if grade1 and not ebae and k not in passage and _spell_out(w, text, m, grade1 == "lead" and k == 0):
            low = w.lower()
            body = "".join(ALPHABET[c] for c in low) if low == "in" else _apply_groups(low)
            out.append((_CAPITAL if w[0].isupper() else "") + body)
            last = m.end()
            continue
        out.append((_GRADE1 if mark else "") + (passage.get(k) or translate_word(w, ebae)))
        last = m.end()
    out.append(text[last:])
    return "".join(out)
