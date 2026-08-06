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


class TestBracketRegulation:
    """원문 대괄호 [ ] → 규정 제49항 대괄호 셀 82…;0 (⠦⠆…⠰⠴). 2026-07-27 결정.

    기대값은 **규정·지침 원문의 점자 예시에서 그대로 옮겼다**(순환검증 금지) —
    우리 출력으로 만들지 않았다. 인용 위치는 각 케이스 주석에 적는다.

    · 「한국 점자 규정」 제49항 표(braille-source/text/규정_텍스트.txt 2163~2168행)
        ( = 8' · ) = ,0   |   [ = 82 · ] = ;0
    · 정답 코퍼스는 원문 대괄호를 소괄호 셀로 적어(471/471) 이 기대값과 어긋난다.
      코퍼스가 아니라 규정을 따르기로 한 결정이므로, 코퍼스 대조 지표는 내려간다.
    """

    def _brf(self, text: str) -> str:
        from app.ai.braille.translator import translate_tagged_text
        from app.utils.braille_ascii import unicode_to_ascii
        return unicode_to_ascii(translate_tagged_text(text))

    # ── 지침 원문이 점자까지 실어 둔 예시 — 셀 단위 전부 대조 ──────────────────
    # 「점자 도서 제작 지침」 발음 표기 예(braille-source/text/점자 도서 제작 지침_text.txt
    # 1299~1301행). 네 쌍이 한 문단 안에 연달아 있고 모두 대괄호 셀 82…;0이다.
    @pytest.mark.parametrize("korean,expected", [
        ("나뭇가지[나무까지]", "cem'$.o82cem,$.o;0"),
        ("머릿기름[머리끼름]", "es\"o'@o\"{582es\"o,@o\"{5;0"),
        ("귓병[귀뼝]", "@mr'~}82@mr,~};0"),
        ("전셋집[전세찝]", ".),n'.ob82.),n,.ob;0"),
    ])
    def test_지침_발음표기_대괄호(self, korean: str, expected: str) -> None:
        assert self._brf(korean) == expected

    def test_지침_배점_대괄호(self) -> None:
        # 「점자 자료 제작 지침」 [예] 배점(점자 자료 제작 지침_text.txt 1627행) = 82#a.s5;0
        assert self._brf("[1점]") == "82#a.s5;0"
        # 「점자 도서 제작 지침」 [예 3-57] 발문(점자 도서 제작 지침_text.txt 3058행) = 82#c.s5;0
        assert self._brf("[3점]") == "82#c.s5;0"

    # ── 화이트리스트가 소괄호로 내리던 부류 — 이제 규정형이어야 한다 ────────────
    # 안쪽 점형은 이 테스트의 주장이 아니므로 여닫는 괄호 셀만 본다(비순환).
    @pytest.mark.parametrize("korean", ["[2012 수능]", "[16]", "[A]", "[실험 과정]"])
    def test_화이트리스트_부류도_규정_대괄호(self, korean: str) -> None:
        brf = self._brf(korean)
        assert brf.startswith("82") and brf.endswith(";0"), brf
        assert not brf.startswith("8'"), f"소괄호 셀로 새고 있다: {brf}"

    def test_수식_대괄호는_별도_점형(self) -> None:
        # 「한국 점자 규정」 수학 제6항(규정_텍스트.txt 3100~3112행)의 수학 대괄호 ('…,).
        # 문장부호 대괄호(82…;0)와 다른 체계라 이 변경이 수식 경로를 건드리면 안 된다.
        assert self._brf("<!수식>[3,5]<!/수식>") == "('#c1e,)"

    def test_관행_복귀_스위치(self, monkeypatch) -> None:
        """_BRACKET_BOOK_STYLE=True 한 줄로 코퍼스 관행(소괄호 셀)으로 되돌아간다."""
        from app.ai.braille import translator
        monkeypatch.setattr(translator, "_BRACKET_BOOK_STYLE", True)
        assert self._brf("[3점]") == "8'#c.s5,0"
        assert self._brf("[2012 수능]").startswith("8'")


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


class TestCircledJamoReg64:
    """동그라미 자모·음절 = 규정 제64항 감쌈형 ⠶…⠶ (2026-08-06 판정 번복).

    종전에는 "도서는 맨 글자로 적는다"고 봤는데, 그 실측이 **구판 수능특강 한 종류**였다.
    신규 2027 코퍼스 48쪽에서 묵자 ㉠ 개수와 gold `⠶⠿⠁⠶` 개수가 쪽마다 1:1로 맞는다
    (4개 책 전부). 규정도 관행도 감쌈형이다.
    """

    @staticmethod
    def _t(text: str) -> str:
        from app.ai.braille.translator import translate_tagged_text
        return translate_tagged_text(text)

    def test_자모는_온표까지_감싼다(self) -> None:
        assert self._t("㉠") == "⠶⠿⠁⠶"          # ⠶ + 온표⠿ + ㄱ⠁ + ⠶
        assert self._t("㉡") == "⠶⠿⠒⠶"

    def test_음절은_온표가_없다(self) -> None:
        assert self._t("㉮") == "⠶⠫⠶"           # ⠶ + 가⠫ + ⠶

    def test_뒤에_조사가_붙어도_감쌈이_남는다(self) -> None:
        assert self._t("㉠은").startswith("⠶⠿⠁⠶")

    def test_맨_자모는_감싸지_않는다(self) -> None:
        assert self._t("ㄱ") == "⠿⠁"            # 글머리 ㄱ은 온표+자모 그대로

    def test_동그라미_숫자는_수표_그대로(self) -> None:
        assert self._t("①").startswith("⠼")     # 규정=도서 일치라 건드리지 않는다
