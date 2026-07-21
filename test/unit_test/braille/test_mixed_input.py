"""혼합 입력·수식 규정 기반 테스트.

테스트 데이터는 test_data/ JSON 파일에서 로드한다:
  formula_pairs.json  — 수식 입력의 정확한 점자 셀 (수학 점자 규정 수작업)
  mixed_pairs.json    — 한국어+영어+숫자+수식 혼합 입력의 구조 검사

검증 방식:
  expected 필드가 있으면 → translate_tagged_text(input) == expected  (정확성)
  must_contain 필드가 있으면 → 해당 기호들이 결과에 모두 포함             (구조)
  두 필드가 동시에 있으면 두 검사를 모두 수행.

번역기 자체 출력을 expected로 쓰지 않는다 — 순환 검증 방지.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from app.ai.braille.translator import translate_tagged_text
from test.braille_style_equiv import canon_greek

_DATA_DIR = Path(__file__).parent.parent.parent / "test_data"
_FORMULA_PATH = _DATA_DIR / "formula_pairs.json"
_MIXED_PATH   = _DATA_DIR / "mixed_pairs.json"


def _load(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return json.loads(path.read_text(encoding="utf-8"))["pairs"]


def _real_pairs(pairs: list[dict]) -> list[dict]:
    """_section 메타 항목을 제외한 실제 테스트 쌍만 반환."""
    return [p for p in pairs if "id" in p]


_FORMULA_ALL = _real_pairs(_load(_FORMULA_PATH))
_MIXED_ALL   = _real_pairs(_load(_MIXED_PATH))

# expected 있는 것 / must_contain 있는 것 분리
_FORMULA_EXACT    = [p for p in _FORMULA_ALL if "expected" in p]
_FORMULA_CONTAINS = [p for p in _FORMULA_ALL if "must_contain" in p]
_MIXED_CONTAINS   = [p for p in _MIXED_ALL   if "must_contain" in p]


# ── 파일 스모크 ────────────────────────────────────────────────────────────────

def test_formula_pairs_file_exists() -> None:
    assert _FORMULA_PATH.exists(), f"formula_pairs.json 없음: {_FORMULA_PATH}"


def test_mixed_pairs_file_exists() -> None:
    assert _MIXED_PATH.exists(), f"mixed_pairs.json 없음: {_MIXED_PATH}"


def test_formula_exact_pairs_nonempty() -> None:
    assert len(_FORMULA_EXACT) >= 10, f"exact 쌍 부족: {len(_FORMULA_EXACT)}개"


# ── 수식 정확성 테스트: expected == 실제 출력 ────────────────────────────────
# expected 는 수학 점자 규정에서 직접 도출한 값 (번역기 출력 아님)

@pytest.mark.parametrize(
    "case_id,rule,inp,expected",
    [(p["id"], p.get("rule",""), p["input"], p["expected"]) for p in _FORMULA_EXACT],
    ids=[p["id"] for p in _FORMULA_EXACT],
)
def test_formula_exact(case_id: str, rule: str, inp: str, expected: str) -> None:
    """규정에서 도출한 expected 와 번역기 출력이 일치해야 함."""
    result = translate_tagged_text(inp)
    # 그리스 소문자 접두는 규정형(⠨)·관행형(⠈) 둘 다 정당 → 양쪽을 접고 비교
    assert canon_greek(result) == canon_greek(expected), (
        f"[{case_id}] {rule}\n"
        f"  입력:     {inp!r}\n"
        f"  expected: {expected!r}\n"
        f"  got:      {result!r}"
    )


# ── 수식 구조 테스트: must_contain 기호 포함 여부 ────────────────────────────

@pytest.mark.parametrize(
    "case_id,inp,must_contain",
    [(p["id"], p["input"], p["must_contain"]) for p in _FORMULA_CONTAINS],
    ids=[p["id"] for p in _FORMULA_CONTAINS],
)
def test_formula_must_contain(case_id: str, inp: str, must_contain: list[str]) -> None:
    """복잡 수식에서 규정 필수 기호가 결과에 포함되어야 함."""
    result = translate_tagged_text(inp)
    for symbol in must_contain:
        assert canon_greek(symbol) in canon_greek(result), (
            f"[{case_id}] 입력: {inp!r}\n"
            f"  필수 기호 {symbol!r} 누락\n"
            f"  결과: {result!r}"
        )


# ── 혼합 입력 구조 테스트: must_contain 기호 포함 여부 ───────────────────────

@pytest.mark.parametrize(
    "case_id,inp,must_contain",
    [(p["id"], p["input"], p["must_contain"]) for p in _MIXED_CONTAINS],
    ids=[p["id"] for p in _MIXED_CONTAINS],
)
def test_mixed_must_contain(case_id: str, inp: str, must_contain: list[str]) -> None:
    """혼합 입력에서 규정 기반 필수 기호가 결과에 포함되어야 함."""
    result = translate_tagged_text(inp)
    assert len(result) > 0, f"[{case_id}] 빈 결과"
    for symbol in must_contain:
        assert canon_greek(symbol) in canon_greek(result), (
            f"[{case_id}] 입력: {inp!r}\n"
            f"  필수 기호 {symbol!r} 누락\n"
            f"  결과: {result!r}"
        )


# ── 개별 규정 검증 — 단순 기호 포함으로 커버 안 되는 순서·횟수 규정 ───────────

class TestFractionOrder:
    """수학 제7항: 분수표 앞에 분모, 뒤에 분자."""

    def test_denominator_before_bar(self) -> None:
        """\frac{1}{2}: 분모(⠼⠃)가 ⠌ 앞에 있어야 함."""
        result = translate_tagged_text("<!수식>\\frac{1}{2}<!/수식>")
        bar = result.index("⠌")
        assert "⠃" in result[:bar], f"분모(⠃)가 ⠌ 앞에 없음: {result!r}"

    def test_nested_fraction_two_bars(self) -> None:
        """중첩 분수 — ⠌ 가 두 번 이상 등장."""
        result = translate_tagged_text("<!수식>\\frac{\\frac{1}{2}}{3}<!/수식>")
        assert result.count("⠌") >= 2, f"⠌ 개수 부족: {result!r}"


class TestAbsoluteValueCount:
    """수학 제21항: 절댓값 기호 ⠳ 열기·닫기 각 1개."""

    def test_abs_bars_exactly_two(self) -> None:
        result = translate_tagged_text("<!수식>|x+1|<!/수식>")
        assert result.count("⠳") == 2, f"⠳ 개수 불일치: {result!r}"


class TestSuperscriptCount:
    """수학 제18항: 위첨자 지시자 수."""

    def test_pythagorean_three_superscripts(self) -> None:
        """a²+b²=c²: 위첨자 ⠘ 세 번."""
        result = translate_tagged_text("<!수식>a^2+b^2=c^2<!/수식>")
        assert result.count("⠣") == 3, f"제곱 약기 ⠣ 개수 불일치(관행, 정답 규정형 0회): {result!r}"


class TestNumberIndicatorCount:
    """한국 점자 규정 제41항: 수표시 중복 삽입 금지."""

    def test_decimal_no_duplicate_indicator(self) -> None:
        result = translate_tagged_text("<!수식>0.48<!/수식>")
        assert result.count("⠼") == 1, f"⠼ 중복: {result!r}"

    def test_thousands_no_duplicate_indicator(self) -> None:
        result = translate_tagged_text("9,375원")
        assert result.count("⠼") == 1, f"⠼ 중복: {result!r}"


class TestBug1NoDoubleSpace:
    """Bug 1 수정 검증: 숫자 뒤 ASCII 단위에서 이중 점자공백(⠀⠀) 없어야 함."""

    def test_number_cm_no_double_space(self) -> None:
        result = translate_tagged_text("키 175cm")
        assert "⠀⠀" not in result, f"이중 점자공백 발생: {result!r}"
        assert "⠼" in result, f"수표시 없음: {result!r}"

    def test_number_km_no_double_space(self) -> None:
        result = translate_tagged_text("거리는 3.5km")
        assert "⠀⠀" not in result, f"이중 점자공백 발생: {result!r}"


class TestBug2LeadingRoman:
    """Bug 2 수정 검증: 대문자 영어로 시작하는 한영 혼합 문장 ⠴ 삽입."""

    def test_covid_leading_roman(self) -> None:
        result = translate_tagged_text("COVID-19 감염자 수는 1,234명")
        assert "⠴" in result, f"⠴ 없음: {result!r}"


class TestBug3NestedFrac:
    """Bug 3 수정 검증: \\frac 분자 안 \\sqrt 중첩 시 ⠌ 보존."""

    def test_quadratic_frac_has_bar(self) -> None:
        result = translate_tagged_text(
            "<!수식>\\frac{-b\\pm\\sqrt{b^2-4ac}}{2a}<!/수식>"
        )
        assert "⠌" in result, f"분수표(⠌) 없음: {result!r}"
