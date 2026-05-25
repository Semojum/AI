"""규정_텍스트.txt 예시 쌍 기반 braillify 회귀 테스트.

각 절에서 decode_ok=True인 쌍을 로드해 translate_tagged_text() 결과를 검증.
규정 원문 → BRF ASCII → Unicode 점자 경로로 추출된 gold 값과 비교.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from app.ai.braille.translator import translate_tagged_text

_PAIRS_DIR = Path(__file__).parent.parent.parent / "test_data" / "regulation_pairs"


def _load_testable(filename: str, max_korean_len: int = 15) -> list[dict[str, Any]]:
    """decode_ok이고 단어 수준인 쌍만 반환."""
    path = _PAIRS_DIR / filename
    if not path.exists():
        return []
    data = json.loads(path.read_text(encoding="utf-8"))
    return [
        p for p in data["pairs"]
        if p["decode_ok"]
        and p["brf_ascii"] != "."          # 설명 줄 마침표 제거
        and len(p["korean"]) <= max_korean_len
        and not p["korean"].startswith("[") # [다만] 등 설명 항목 제거
        and "⠀" not in p["braille_unicode"] # 공백 포함 쌍 제거 (braillify는 공백 미삽입)
    ]


def _pairs_to_params(filename: str, max_n: int = 12) -> list[tuple[str, str, str]]:
    pairs = _load_testable(filename)[:max_n]
    return [(p["korean"], p["braille_unicode"], p["item"]) for p in pairs]


# ── 제1절: 첫소리 자음자 ─────────────────────────────────────────────────────

_SEC01 = _pairs_to_params("section_01_choseong.json")


@pytest.mark.parametrize("korean,expected,item", _SEC01)
def test_sec01_choseong(korean: str, expected: str, item: str) -> None:
    """제1절 첫소리 자음자 예시 쌍."""
    result = translate_tagged_text(korean)
    assert result == expected, (
        f"[{item}] {korean!r}\n"
        f"  got:      {result!r}\n"
        f"  expected: {expected!r}"
    )


# ── 제2절: 받침 ──────────────────────────────────────────────────────────────

_SEC02 = _pairs_to_params("section_02_jongseong.json")


@pytest.mark.parametrize("korean,expected,item", _SEC02)
def test_sec02_jongseong(korean: str, expected: str, item: str) -> None:
    """제2절 받침 예시 쌍."""
    result = translate_tagged_text(korean)
    assert result == expected, (
        f"[{item}] {korean!r}\n"
        f"  got:      {result!r}\n"
        f"  expected: {expected!r}"
    )


# ── 제3절: 모음자 ─────────────────────────────────────────────────────────────

_SEC03 = _pairs_to_params("section_03_vowels.json")


@pytest.mark.parametrize("korean,expected,item", _SEC03)
def test_sec03_vowels(korean: str, expected: str, item: str) -> None:
    """제3절 모음자 예시 쌍."""
    result = translate_tagged_text(korean)
    assert result == expected, (
        f"[{item}] {korean!r}\n"
        f"  got:      {result!r}\n"
        f"  expected: {expected!r}"
    )


# ── 제6절: 숫자 (decode_ok 쌍) ───────────────────────────────────────────────

_SEC06 = _pairs_to_params("section_06_numbers.json")


@pytest.mark.parametrize("korean,expected,item", _SEC06)
def test_sec06_numbers(korean: str, expected: str, item: str) -> None:
    """제6절 숫자 예시 쌍."""
    result = translate_tagged_text(korean)
    assert result == expected, (
        f"[{item}] {korean!r}\n"
        f"  got:      {result!r}\n"
        f"  expected: {expected!r}"
    )


# ── 스모크 테스트: 섹션별 파일 존재 확인 ──────────────────────────────────────

_EXPECTED_FILES = [
    "section_01_choseong.json",
    "section_02_jongseong.json",
    "section_03_vowels.json",
    "section_04_abbreviations.json",
    "section_05_abbreviated_words.json",
    "section_06_numbers.json",
    "section_07_punctuation.json",
    "section_08_foreign.json",
    "section_09_special.json",
    "section_10_marks.json",
    "section_11_english.json",
    "section_12_numbers2.json",
    "section_13_misc.json",
    "section_14_layout.json",
]


@pytest.mark.parametrize("filename", _EXPECTED_FILES)
def test_regulation_pairs_file_exists(filename: str) -> None:
    assert (_PAIRS_DIR / filename).exists(), f"규정 쌍 파일 없음: {filename}"


@pytest.mark.parametrize("filename", _EXPECTED_FILES)
def test_regulation_pairs_has_decode_ok(filename: str) -> None:
    """각 섹션에 decode_ok 쌍이 하나 이상 있어야 함."""
    path = _PAIRS_DIR / filename
    if not path.exists():
        pytest.skip("파일 없음")
    data = json.loads(path.read_text(encoding="utf-8"))
    ok = [p for p in data["pairs"] if p["decode_ok"]]
    assert len(ok) >= 1, f"{filename}: decode_ok 쌍 0개"
