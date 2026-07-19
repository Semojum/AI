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

**적용 순서**(영어 점자 표준의 우선순위):
  1. 단독 단어 약자(alone)      — 앞뒤가 공백/문장부호일 때만
  2. 단축형(short form)          — 단어 전체가 일치할 때만
  3. 강약자(strong groups)       — 위치 무관, 긴 것 우선
  4. 첫글자 약자 / 끝글자 약자   — 위치 제약(첫/끝 음절 근처)
  5. 남은 글자 → 알파벳
"""
from __future__ import annotations

import re

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
    "st": "⠌", "ing": "⠬", "ar": "⠜", "ble": "⠶",
    "bb": "⠆", "cc": "⠒", "dd": "⠲", "ff": "⠖", "gg": "⠶",
    "in": "⠔", "en": "⠢",
}
# 낱말 첫머리 전용 음절 약자 — 같은 셀이 낱말 중간에서는 겹자음(bb·cc·dd) 뜻이라
# 위치로 갈린다(영어 점자 표준). be/con/dis 는 첫머리에서만 쓴다.
WORD_INITIAL_SYLLABLE: dict[str, str] = {"be": "⠆", "con": "⠒", "dis": "⠲"}
# 위치 제약: 낱말 첫머리에는 쓰지 않는 약자(영어 점자 표준).
_NOT_WORD_INITIAL = {"ing", "ble", "bb", "cc", "dd", "ff", "gg"}

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
# ⚠ ation·ally 는 EBAE에 있고 UEB에서 폐지됐다. 코퍼스 실측으로 채택 여부를 정한다
#   (temp/eng_variant_ab.py) — 기본은 사용(코퍼스가 구 EBAE 관행으로 확인됨).
FINAL_EBAE_ONLY: dict[str, str] = {"ation": "⠠⠝", "ally": "⠠⠽"}

# ── 5. 단축형(short form) — 낱말 전체가 일치할 때만 ──────────────────────────
SHORT_FORMS: dict[str, str] = {
    "about": "⠁⠃", "above": "⠁⠃⠧", "according": "⠁⠉", "across": "⠁⠉⠗",
    "after": "⠁⠋", "afternoon": "⠁⠋⠝", "afterward": "⠁⠋⠺", "again": "⠁⠛",
    "against": "⠁⠛⠌", "almost": "⠁⠇⠍", "already": "⠁⠇⠗", "also": "⠁⠇",
    "although": "⠁⠇⠹", "altogether": "⠁⠇⠞", "always": "⠁⠇⠺",
    "because": "⠆⠉", "before": "⠆⠿", "behind": "⠆⠓", "below": "⠆⠇",
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


def _apply_groups(word: str) -> str:
    """소문자 낱말 → 약자 적용 셀열. 긴 약자 우선, 위치 제약 준수."""
    keys = sorted(set(STRONG_GROUPS) | set(FINAL_EBAE_ONLY) | set(WORD_INITIAL_SYLLABLE)
                  | set(FINAL_46) | set(FINAL_56)
                  | set(INITIAL_5) | set(INITIAL_45) | set(INITIAL_456),
                  key=len, reverse=True)
    out: list[str] = []
    i = 0
    while i < len(word):
        for k in keys:
            if not word.startswith(k, i):
                continue
            if k in WORD_INITIAL_SYLLABLE:
                # 첫머리 음절 약자는 뒤에 글자가 더 있어야 한다(be/con/dis 단독 아님)
                if i != 0 or len(word) <= len(k):
                    continue
                out.append(WORD_INITIAL_SYLLABLE[k])
            elif k in STRONG_GROUPS:
                if i == 0 and k in _NOT_WORD_INITIAL:
                    continue
                out.append(STRONG_GROUPS[k])
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


def translate_word(word: str) -> str:
    """영어 낱말 하나 → Grade 2 점자. 대문자표는 원 낱말의 대소문자로 판단."""
    if not word:
        return ""
    low = word.lower()
    caps = _CAPITAL if word[0].isupper() else ""
    if low in WORDSIGNS:
        return caps + WORDSIGNS[low]
    if low in SHORT_FORMS:
        return caps + SHORT_FORMS[low]
    return caps + _apply_groups(low)


def translate(text: str) -> str:
    """영어 구간 문자열 → Grade 2 점자(낱말 단위 적용, 그 외 문자는 그대로)."""
    return _WORD_RE.sub(lambda m: translate_word(m.group()), text)
