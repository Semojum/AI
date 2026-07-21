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
    """정답 도서 표기 관행(BRAILLE_STYLE=book, 기본값) — 규정과 다른 자리.

    ★ 기본=관행(태민 2026-07-17 재판정). 텍스트 축의 잣대가 정답 도서라 정답 표기가 기본.
      시각자료의 관행/규정 갈림은 4안 제공으로 해소(모드 선택 불필요). 규정 경로는
      BRAILLE_STYLE=regulation 스위치로 유지 — TestRegulationSwitch가 검증한다.

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

    def test_단일_대문자_괄호는_붙임표(self):
        # 정답 도서 실측: (A)(B)(C) 라벨은 붙임표+로마자표+대문자표(gold ⠤⠴⠠x⠤ =
        # -0,x-). 전 과목 500/522·소괄호 0건(외국어 444·생물 54·언어 8·사회문화 6…).
        # 소괄호(8' ,0)는 규정 제49항·화학 반응식 글자체 괄호 한정이라 일반 라벨엔 안 쓴다.
        assert self._brf("(A)") == "-0,a-"          # 붙임표 -0,a- (로마자표0+대문자표,+a)
        assert self._brf("(B)") == "-0,b-"
        # 소문자 (x)는 수학 변수(수학2 수식괄호 1609건)라 소괄호 유지 — 회귀 방지
        assert self._brf("(x)") == "8'x,0"

    def test_한글_괄호는_붙임표(self):
        # 정답 도서는 표시 문자뿐 아니라 한글 괄호도 붙임표로 감싼다
        # (예: "소계(해당 인구)" → "소계-해당 인구-", "(2,575)" → "-2,575-")
        assert self._brf("(조사)").startswith("-")
        assert self._brf("(2,575)").startswith("-")

    def test_영문_약어_괄호도_붙임표(self):
        # 2026-07-18 정정: 대문자 약어도 정답은 붙임표(-⠴SNS-, 사회문화 p062 실측).
        # 소괄호 유지는 단일 알파벳 (A)·(x)만.
        assert self._brf("(SNS)").startswith("-")

    def test_화살괄호는_작은따옴표(self):
        assert self._brf("〈보기〉") == ",8~u@o0'"   # ‘보기’
        assert self._brf("<보기>") == ",8~u@o0'"


class TestRegulationSwitch:
    """BRAILLE_STYLE=regulation 스위치가 살아 있다는 계약(기본=관행, 태민 2026-07-17 재판정).

    기본 동작은 TestBookStyleConventions가 검증한다(이제 autouse env 없이도 기본이 관행).
    여기서는 규정 모드로 전환했을 때 규정 표기가 나오는지만 본다.
    """

    @pytest.fixture(autouse=True)
    def _reg_mode(self, monkeypatch):
        import importlib
        from app.ai.braille import translator
        monkeypatch.setenv("BRAILLE_STYLE", "regulation")
        importlib.reload(translator)
        yield
        monkeypatch.delenv("BRAILLE_STYLE")
        importlib.reload(translator)

    def _brf(self, text: str) -> str:
        from app.ai.braille.translator import translate_tagged_text
        from app.utils.braille_ascii import unicode_to_ascii
        return unicode_to_ascii(translate_tagged_text(text))

    def test_표시문자는_규정_소괄호(self):
        assert self._brf("(가)") == "8'$,0"          # 제49항 소괄호 (관행이면 -$-)

    def test_화살괄호는_규정_기호(self):
        # 제63항 〈…〉 — 관행(작은따옴표 ,8~u@o0')로 새지 않아야 한다
        assert self._brf("〈보기〉") != ",8~u@o0'"
