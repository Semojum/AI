"""특수기호 점자 매핑 (PART 4-3 점역 전처리).

symbol_table.json을 단일 소스로 로드하여 특수기호 → 점자 BRF 치환.
긴 키 우선 정렬로 '……'이 '…' 세 개로 오분리되는 문제를 방지.

braillify 설치 환경에서는 preprocess/postprocess 플레이스홀더 방식을 사용한다.
  preprocess()  : 특수기호 → \x00SYM_{idx}\x00 플레이스홀더 치환 (braillify가 건드리지 않음)
  postprocess() : 플레이스홀더 → 점자 기호 복원
braillify 미설치 폴백에서는 substitute_symbols()로 직접 치환한다.
  (폴백 _braillify_fallback은 점자 Unicode를 그대로 통과시키므로 안전)
"""

from __future__ import annotations

import json
import os
import pathlib

_TABLE_PATH = pathlib.Path(__file__).parent / "symbol_table.json"

# 그리스 소문자 접두 관행(2026-07-21 실측): 규정 제30항·수학 제13항은 `.x`(⠨)이나
# 코퍼스 도서는 `@x`(⠈)를 쓴다 — gold 수학2 원문 실측 val 263회 vs ⠨ 0회(판정가능
# 265건 중), dev 24회 vs 0회. output_수학2_page028.brl 원시 BRF에서 θ=`@?`,
# 같은 줄의 ≠=`.3`으로 두 접두를 **구분해** 쓰는 것이 확인된다(대문자는 ⠨ 유지).
# regulation 모드는 규정형 ⠨를 유지한다.
_IS_BOOK_STYLE = os.environ.get("BRAILLE_STYLE", "book") != "regulation"
_LC_GREEK_CHARS = "αβγδεζηθικλμνξοπρστυφχψω"

# \x00 은 braillify가 변환하지 않는 제어문자 → 플레이스홀더로 안전
_PH_FMT = "\x00SYM_{idx}\x00"


def _load_flat_table() -> dict[str, str]:
    with _TABLE_PATH.open(encoding="utf-8") as f:
        raw = json.load(f)
    flat: dict[str, str] = {}
    for category, entries in raw.items():
        if category.startswith("_"):
            continue
        if not isinstance(entries, dict):
            continue
        for symbol, braille in entries.items():
            if not symbol.startswith("_") and isinstance(braille, str):
                flat[symbol] = braille
    # 그리스 소문자 접두 관행 전환(book 모드 한정) — 대문자(⠠⠨x)는 건드리지 않는다.
    if _IS_BOOK_STYLE:
        for ch in _LC_GREEK_CHARS:
            b = flat.get(ch)
            if b and b.startswith("⠨") and len(b) == 2:
                flat[ch] = "⠈" + b[1]
    # 긴 키 우선 → '……'가 '…'보다 먼저 치환되도록
    return dict(sorted(flat.items(), key=lambda x: len(x[0]), reverse=True))


SYMBOL_TABLE: dict[str, str] = _load_flat_table()


def _load_rule_ids() -> dict[str, str]:
    """기호 → rule_id 매핑 (rule_trail emit용, Phase B).

    각 카테고리의 `_rule`(기본 rule_id) + `_rule_overrides`(세분 예외)에서 구성한다.
    매핑이 없는 기호(미검증·확신 부족)는 제외 — 변환은 되지만 trail은 emit하지 않는다
    (환각 0: 확신 없는 rule_id를 만들지 않음).
    """
    with _TABLE_PATH.open(encoding="utf-8") as f:
        raw = json.load(f)
    rules: dict[str, str] = {}
    for category, entries in raw.items():
        if category.startswith("_") or not isinstance(entries, dict):
            continue
        default = entries.get("_rule")
        overrides = entries.get("_rule_overrides", {})
        for symbol, braille in entries.items():
            if symbol.startswith("_") or not isinstance(braille, str):
                continue
            rule_id = overrides.get(symbol, default)
            if rule_id is not None:
                rules[symbol] = rule_id
    return rules


SYMBOL_RULE_IDS: dict[str, str] = _load_rule_ids()


def symbol_rule_spans(source_text: str, braille: str) -> list[tuple[int, int, str]]:
    """원본에 등장하는 특수기호의 출력 점자 좌표 → (start, end, rule_id) 목록.

    rule_trail '내용 변환' emit용(Phase B). source-gated — 원본(점역 전)에 실제로 있는
    기호만 대상으로 하여 출력 스캔 오탐(B1식)을 방지한다. 출력 점자에서 해당 글리프
    위치를 찾아 span을 부여하되, 긴 글리프 우선 + 점유 마스킹으로 부분일치(예: ⠤ ⊂ ⠤⠤)
    와 중복 계수를 막는다. (점자 좌표는 best-effort — 줄분리/공백정리 통과 후 정밀 보정은 추후.)
    """
    targets = [
        (symbol, SYMBOL_TABLE[symbol], rule_id)
        for symbol, rule_id in SYMBOL_RULE_IDS.items()
        if symbol in source_text and symbol in SYMBOL_TABLE
    ]
    targets.sort(key=lambda t: len(t[1]), reverse=True)  # 긴 글리프 우선

    consumed = [False] * len(braille)
    spans: list[tuple[int, int, str]] = []
    for symbol, glyph, rule_id in targets:
        if not glyph:
            continue
        max_n = source_text.count(symbol)
        width = len(glyph)
        found = 0
        start = 0
        while found < max_n:
            i = braille.find(glyph, start)
            if i == -1:
                break
            if any(consumed[i:i + width]):  # 더 긴 글리프가 이미 점유
                start = i + 1
                continue
            for k in range(i, i + width):
                consumed[k] = True
            spans.append((i, i + width, rule_id))
            found += 1
            start = i + width
    spans.sort(key=lambda s: s[0])
    return spans


def preprocess(text: str) -> tuple[str, dict[str, str]]:
    """특수기호를 플레이스홀더로 치환한다 (braillify 모드 Step A).

    Returns:
        processed: 플레이스홀더가 삽입된 텍스트
        symbol_map: {플레이스홀더: 점자기호} — postprocess()에 전달
    """
    symbol_map: dict[str, str] = {}
    idx = 0
    for symbol, braille in SYMBOL_TABLE.items():
        if symbol in text:
            placeholder = _PH_FMT.format(idx=idx)
            text = text.replace(symbol, placeholder)
            symbol_map[placeholder] = braille
            idx += 1
    return text, symbol_map


def postprocess(text: str, symbol_map: dict[str, str]) -> str:
    """플레이스홀더를 점자 기호로 복원한다 (braillify 모드 Step C)."""
    for placeholder, braille in symbol_map.items():
        text = text.replace(placeholder, braille)
    return text


def substitute_symbols(text: str) -> str:
    """SYMBOL_TABLE 기반 특수기호 점자 직접 치환 (폴백 전용).

    braillify 미설치 폴백(_braillify_fallback)은 점자 Unicode를 pass-through하므로
    직접 치환해도 이중 변환이 발생하지 않는다.
    braillify 설치 환경에서는 preprocess/postprocess를 사용할 것.
    """
    for symbol, braille in SYMBOL_TABLE.items():
        text = text.replace(symbol, braille)
    return text
