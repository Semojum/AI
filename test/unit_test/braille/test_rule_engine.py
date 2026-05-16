"""C5-critical: 점자 숫자 변환 전수 테스트.

⠼ (수표시) 누락 시 배포 차단.
"""

import pytest

from app.ai.braille.kor_math_rules import (
    _DIGIT_MAP,
    _NUMBER_INDICATOR,
    digits_to_braille,
)
from app.ai.braille.translator import translate_tagged_text


class TestDigitMap:
    """C5: _DIGIT_MAP 전수 검증."""

    @pytest.mark.parametrize("digit,expected", [
        ("0", "⠚"), ("1", "⠁"), ("2", "⠃"), ("3", "⠉"), ("4", "⠙"),
        ("5", "⠑"), ("6", "⠋"), ("7", "⠛"), ("8", "⠓"), ("9", "⠊"),
    ])
    def test_digit_cell(self, digit: str, expected: str) -> None:
        assert _DIGIT_MAP[digit] == expected, (
            f"C5 위반: _DIGIT_MAP['{digit}'] = {_DIGIT_MAP[digit]!r}, "
            f"예상값 = {expected!r}"
        )

    def test_all_ten_digits_present(self) -> None:
        assert set(_DIGIT_MAP) == set("0123456789")


class TestDigitsToBraille:
    """C5: digits_to_braille 수표시 삽입 전수 검증."""

    @pytest.mark.parametrize("digit", list("0123456789"))
    def test_number_indicator_prepended(self, digit: str) -> None:
        result = digits_to_braille(digit)
        assert result.startswith(_NUMBER_INDICATOR), (
            f"C5 위반: digits_to_braille('{digit}') = {result!r} — 수표시(⠼) 누락"
        )

    def test_multi_digit(self) -> None:
        assert digits_to_braille("123") == f"{_NUMBER_INDICATOR}⠁⠃⠉"

    def test_zero(self) -> None:
        assert digits_to_braille("0") == f"{_NUMBER_INDICATOR}⠚"

    def test_decimal(self) -> None:
        result = digits_to_braille("3.14")
        assert result.startswith(_NUMBER_INDICATOR)
        assert "⠂" in result

    def test_negative(self) -> None:
        result = digits_to_braille("-5")
        assert result.startswith(_NUMBER_INDICATOR)
        assert "⠤" in result


class TestTranslator:

    def test_hangul_nonempty(self) -> None:
        assert len(translate_tagged_text("가나다")) > 0

    def test_english_roman_indicator(self) -> None:
        result = translate_tagged_text("AB")
        assert "⠴" in result, "영어 앞 로마자표 ⠴ 누락"

    def test_number_in_text_gets_indicator(self) -> None:
        result = translate_tagged_text("5번")
        assert _NUMBER_INDICATOR in result

    def test_formula_tag_fraction(self) -> None:
        result = translate_tagged_text("<formula>\\frac{1}{2}</formula>")
        assert "⠜" in result

    def test_other_tags_stripped(self) -> None:
        result = translate_tagged_text("<em>텍스트</em>")
        assert "<em>" not in result
        assert len(result) > 0

    def test_mixed_korean_english(self) -> None:
        result = translate_tagged_text("Hello 세계")
        assert "⠴" in result
        assert "⠲" in result
