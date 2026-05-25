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
import pathlib

_TABLE_PATH = pathlib.Path(__file__).parent / "symbol_table.json"

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
    # 긴 키 우선 → '……'가 '…'보다 먼저 치환되도록
    return dict(sorted(flat.items(), key=lambda x: len(x[0]), reverse=True))


SYMBOL_TABLE: dict[str, str] = _load_flat_table()


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
