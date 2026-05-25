"""단어 수준 점자 정확성 테스트.

테스트 데이터: test_data/word_pairs.json
gold 값 출처: 규정_텍스트.txt → extract_regulation_pairs.py → BRF ASCII → Unicode 점자
번역기 출력을 정답으로 쓰지 않음 — 순환 검증 방지.

커버리지:
  - 제1절: 첫소리 자음자 (초성) — 기존 test_regulation_examples.py 12개 외 추가
  - 제2절: 받침 자음자 — 겹받침 포함
  - 제6절: 약자 — 된소리, 이중모음, 겹받침 복합 단어
  - 제7절: 약어 — 그리고(⠁) 기반 축약어
  - 제11절: 숫자+단위 조합
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from app.ai.braille.translator import translate_tagged_text

_DATA_PATH = Path(__file__).parent.parent.parent / "test_data" / "word_pairs.json"


def _load() -> list[dict[str, Any]]:
    if not _DATA_PATH.exists():
        return []
    return [p for p in json.loads(_DATA_PATH.read_text(encoding="utf-8"))["pairs"]
            if "id" in p]


_ALL_PAIRS = _load()


def test_word_pairs_file_exists() -> None:
    assert _DATA_PATH.exists(), f"word_pairs.json 없음: {_DATA_PATH}"


def test_word_pairs_nonempty() -> None:
    assert len(_ALL_PAIRS) >= 20, f"테스트 쌍 부족: {len(_ALL_PAIRS)}개"


@pytest.mark.parametrize(
    "case_id,rule,korean,expected",
    [(p["id"], p.get("rule", ""), p["korean"], p["expected"]) for p in _ALL_PAIRS],
    ids=[p["id"] for p in _ALL_PAIRS],
)
def test_word_exact(case_id: str, rule: str, korean: str, expected: str) -> None:
    """규정 기반 expected 와 번역기 출력이 일치해야 함."""
    result = translate_tagged_text(korean)
    assert result == expected, (
        f"[{case_id}] {rule}\n"
        f"  입력:     {korean!r}\n"
        f"  expected: {expected!r}\n"
        f"  got:      {result!r}"
    )
