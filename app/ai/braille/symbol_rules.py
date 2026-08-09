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
import re

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
    # ★ 2026-07-29(대표 결정) — 소문자 그리스 접두를 **규정형 ⠨로 되돌린다.**
    #   판정 원칙: "규정이 명확한데 관행이 완전히 다르면 규정대로"(docs/analysis/규정-관행_대조원장.md §1).
    #   규정 제30항·수학 제13항이 ⠨로 명확하므로 관행 ⠈를 따르지 않는다.
    #   관행형이던 근거(gold 판정가능 265건 중 ⠈ 263)는 그대로 유효하나, 그건
    #   2012년 EBS 판본 하나의 관행이고 국가 표준이 아니다. 점수 손실은 감수한다.
    #   ⚠ 같은 계열로 남은 것 — 대문자 그리스(규정 ⠠⠨ vs 도서 ⠨)·≠(규정 ⠨⠒⠒ vs 도서 ⠨⠒).
    #     이번 결정 범위 밖이라 손대지 않았고 원장에 결정 대상으로 올려 뒀다.
    # ⚠ C-19(2026-08-09) — 이 표는 **기호 하나에 값 하나**다. 규정이 문맥마다 다른 점형을
    #   주는 넷은 담을 수 없어 한쪽 값만 들어가 있다:
    #     ′  수학 프라임 제17항 ⠤        ↔ 단위 분·피트 제69항 ⠴⠤   (표는 ⠴⠤)
    #     ·  가운뎃점 제49항 ⠐⠆          ↔ 곱셈 수학 제2항[붙임] ⠐   (표는 ⠐⠆)
    #     ’  닫는 작은따옴표 제49항 ⠴⠄   ↔ 아포스트로피 제61항 ⠄     (표는 ⠴⠄)
    #     ×  숨김표 제57항 ⠸⠭⠇          ↔ 곱셈표 수학 제2항 ⠡       (두 값 다 있음 — 조회 순서가 결정)
    #   분기 기준 제안은 원장 C-19(요소 type이 formula/inline_math면 수학 쪽). **미구현** —
    #   고치려면 여기가 아니라 translator._emit_mixed의 세그먼트 분기에 붙여야 한다.
    #   표 값을 한쪽으로 바꾸는 것만으로는 반대 문맥이 깨지므로 단독 수정 금지.
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


# 숨김표 래퍼 글리프 `_Xl` (⠸ + 점형 1칸 + ⠇). 제57항이 반복형을 정의하는 대상이다.
_HIDDEN_WRAP_RE = re.compile(r"^⠸(.)⠇$")


def _hidden_run_targets(
    source_text: str, targets: list[tuple[str, str, str]]
) -> list[tuple[str, str, str]]:
    """제57항 반복형(⠸XⁿⓁ) 탐색 타깃 — 낱개 ⠸X⠇ 타깃만으로는 못 찾기 때문.

    숨김표가 여러 개 붙으면 출력은 래퍼 하나로 합쳐진다(translator.merge_hidden_runs).
    그러면 낱개 글리프 ⠸X⠇는 출력 어디에도 없어서, 이 목록에 반복형을 넣지 않으면
    반복 숨김표의 rule_trail이 통째로 사라진다(rule_trail 필수 — 불변 규칙 2).
    원문에 있는 개수까지만 후보를 만든다(source-gated 원칙 유지).
    """
    out: list[tuple[str, str, str]] = []
    for symbol, glyph, rule_id in targets:
        m = _HIDDEN_WRAP_RE.match(glyph)
        if not m:
            continue
        for n in range(source_text.count(symbol), 1, -1):
            out.append((symbol * n, "⠸" + m.group(1) * n + "⠇", rule_id))
    return out


# ── rule_trail을 달 '판단이 갈리는' 기호 (Step17, 2026-08-08) ──────────────────
# 근거는 전부 docs/analysis/규정-관행_대조원장.md 항목 번호. 없는 것은 넣지 않는다.
_DISCRETIONARY: frozenset[str] = frozenset(
    "…"          # B-01 말줄임표 — 규정 ⠐⠐⠐ vs 도서 ⠠⠠⠠. gold 33:201로 갈린다
    "○□△◇☆◆◎▣"   # C-07·B-03 숨김표↔글머리 — 같은 묵자가 문맥에 따라 제49·57·72항으로 갈린다
    "㉠㉡㉢㉣㉤㉥㉦㉧㉨㉩"   # R-03 원문자 — 제8·64항 감쌈형 ⠶…⠶(2026-08-06 재판정)
    # ⚠ ①②③…은 일부러 뺐다. 제64항이 "동그라미 숫자는 수표 뒤에 숫자의 점형을 한 단 내려
    #   적는다"로 답을 하나로 못박아 고를 여지가 없고, 선지 번호라 쪽마다 열 개씩 나온다.
    #   R-03의 재판정 대상은 '그 밖의 동그라미 문자'(㉠류 감쌈)였지 숫자가 아니다.
    #   넣었을 때 실측: dev 400쪽에서 이 한 항목이 남은 근거의 59%(4,228건)를 먹었다.
    "≠×±"        # §4 미결(≠ 규정 ⠨⠒⠒ vs 도서 ⠨⠒) · C-12 한글 사이 띄어쓰기 · B-04 ×××
    "∽ː"         # 점역자 주 마커 ⠠⠄와 **같은 점형**이라 점역사가 실제로 헷갈리는 자리(B1)
    "→←↔↑↓⇒⇐⇔"   # 제70항 — 앞뒤 한 칸 띔이 C-12(제46항)와 갈리는 자리
    "%‰°℃℉′″"     # 제69항 로마자 단위 — 로마자표·종료표 삽입이 코퍼스에서 비일관
    "αβγδεζηθικλμνξοπρστυφχψωΑΒΓΔΕΖΗΘΙΚΛΜΝΞΟΠΡΣΤΥΦΧΨΩ"  # R-02 지시자 ⠨(규정) vs ⠈(도서)
)


def symbol_rule_spans(source_text: str, braille: str) -> list[tuple[int, int, str]]:
    """원본에 등장하는 **판단이 갈리는** 특수기호의 출력 점자 좌표 → (start, end, rule_id).

    rule_trail emit용. source-gated — 원본(점역 전)에 실제로 있는 기호만 대상으로 하여
    출력 스캔 오탐(B1식)을 방지한다. 출력 점자에서 해당 글리프 위치를 찾아 span을 부여하되,
    긴 글리프 우선 + 점유 마스킹으로 부분일치(예: ⠤ ⊂ ⠤⠤)와 중복 계수를 막는다.
    (점자 좌표는 best-effort — 줄분리/공백정리 통과 후 정밀 보정은 추후.)

    ★ Step17(2026-08-08 대표 지시) — `_DISCRETIONARY`에 있는 기호만 emit한다.
      종전에는 매핑이 있는 260여 기호 전부를 달았고 dev 400쪽에서 24,000건 넘게 나왔다.
      그 대부분이 ( ) / - ‘ ’ : ; = < > $ * 같은 **고를 여지가 없는 1:1 표 조회**여서,
      "점역사도 헷갈리거나 주관이 갈리는 것"만 남긴다는 새 기준에 어긋난다.
      남긴 것은 전부 `docs/analysis/규정-관행_대조원장.md`에 오른 자리이거나(R-02·R-03·
      B-01·B-04·C-07·C-12) 규정끼리 갈리는 자리(글머리↔숨김표, 제46항↔제70항)다.
      기호를 더하거나 뺄 때는 반드시 원장 항목 번호를 근거로 적을 것.
    """
    targets = [
        (symbol, SYMBOL_TABLE[symbol], rule_id)
        for symbol, rule_id in SYMBOL_RULE_IDS.items()
        if symbol in _DISCRETIONARY and symbol in source_text and symbol in SYMBOL_TABLE
    ]
    targets = _hidden_run_targets(source_text, targets) + targets
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
