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


class TestBookStyleConventions:
    """정답 도서 표기 관행(BRAILLE_STYLE=book) — 규정과 다른 자리.

    ★ 기본값이 아니다. 기본은 규정(태민 2026-07-17) — 보유 도서가 규정을 완벽히 준수하진
      않으므로 규정을 정답으로 본다. 관행 경로는 지우지 않고 스위치로 남겼고, 이 클래스가
      그 경로를 검증한다. 지우면 관행 모드가 무검증이 된다.

    근거: 정답 코퍼스(수능특강 점역본 1131p) 전수 관찰.
      · 표시 문자 (가)/(1) → 붙임표로 감쌈: -가- 1217회 / -1- 281회
      · 일반 소괄호는 규정대로: 730회. 영문 (A)(B)도 소괄호 유지: 124/74회
      · 화살괄호 〈〉《》: 코퍼스에 0회 → 작은따옴표(3618회)로 적음
    """

    @pytest.fixture(autouse=True)
    def _book_mode(self, monkeypatch):
        """_BOOK_STYLE은 import 시점 상수라 env만 바꿔선 안 먹는다 — reload가 필요하다."""
        import importlib
        from app.ai.braille import translator
        monkeypatch.setenv("BRAILLE_STYLE", "book")
        importlib.reload(translator)
        yield
        monkeypatch.delenv("BRAILLE_STYLE")
        importlib.reload(translator)

    def _brf(self, text: str) -> str:
        from app.ai.braille.translator import translate_tagged_text
        from app.utils.braille_ascii import unicode_to_ascii
        return unicode_to_ascii(translate_tagged_text(text))

    def test_한글_표시문자는_붙임표(self):
        assert self._brf("(가)") == "-$-"          # 가 = $ (약자)
        assert self._brf("(나)") == "-c-"

    def test_숫자_표시문자는_붙임표(self):
        assert self._brf("(1)") == "-#a-"

    def test_영문_괄호는_소괄호_유지(self):
        assert self._brf("(A)") == "8',a,0"        # 여는 8' · 닫는 ,0 (규정 제49항)

    def test_한글_괄호는_붙임표(self):
        # 정답 도서는 표시 문자뿐 아니라 한글 괄호도 붙임표로 감싼다
        # (예: "소계(해당 인구)" → "소계-해당 인구-", "(2,575)" → "-2,575-")
        assert self._brf("(조사)").startswith("-")
        assert self._brf("(2,575)").startswith("-")

    def test_영문_섞인_괄호는_소괄호_유지(self):
        assert self._brf("(SNS)").startswith("8'")

    def test_화살괄호는_작은따옴표(self):
        assert self._brf("〈보기〉") == ",8~u@o0'"   # ‘보기’
        assert self._brf("<보기>") == ",8~u@o0'"


class TestRegulationIsDefault:
    """스위치 없이도 규정 표기가 나와야 한다 — 기본값이 규정이라는 계약(태민 2026-07-17).

    ★ 이 클래스가 통과해야 "규정이 정답"이 실제로 배선된 것이다. TestBookStyleConventions는
      env를 켰을 때만 관행이 나오는지 보므로, 기본값 자체는 여기서만 검증된다.
    """

    def _brf(self, text: str) -> str:
        from app.ai.braille.translator import translate_tagged_text
        from app.utils.braille_ascii import unicode_to_ascii
        return unicode_to_ascii(translate_tagged_text(text))

    def test_표시문자는_규정_소괄호(self):
        assert self._brf("(가)") == "8'$,0"          # 제49항 소괄호 (관행이면 -$-)

    def test_화살괄호는_규정_기호(self):
        # 제63항 〈…〉 — 관행(작은따옴표 ,8~u@o0')로 새지 않아야 한다
        assert self._brf("〈보기〉") != ",8~u@o0'"

    def test_글머리표는_규정_제72항(self):
        from app.ai.braille.layout_braille import _HIDDEN_TO_BULLET
        assert _HIDDEN_TO_BULLET["⠐⠆"] == "⠸⠲⠀"    # _4 (관행이면 ⠔⠔)
