"""C5-critical: 점자 숫자 변환 전수 테스트.

⠼ (수표시) 누락 시 배포 차단.
한국 점자 규정 기준:
  제40항: 숫자 점자 a-j (1-9, 0)
  제41항: 자릿점(,) = ⠂ (dot 2)
  제43항/수학 제8항: 소수점(.) = ⠲ (dots 2,5,6)
  수학 제7항: 분수 = 분모 + ⠌ + 분자
  수학 제17항: 음수 부호 = ⠤
  수학 제18항: 위첨자 = ⠘
  수학 제22항: 근호 = ⠜
"""

import pytest

from app.ai.braille.kor_math_rules import (
    _DIGIT_MAP,
    _NUMBER_INDICATOR,
    convert_latex,
    digits_to_braille,
)
from app.ai.braille.translator import translate_tagged_text


class TestDigitMap:
    """C5: _DIGIT_MAP 전수 검증 (제40항: 숫자 점자 a-j)."""

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

    def test_decimal_point_correct_cell(self) -> None:
        """제43항: 소수점은 ⠲ (dots 2,5,6) — ⠂(dot 2, 자릿점)와 다른 점자."""
        result = digits_to_braille("3.14")
        assert result.startswith(_NUMBER_INDICATOR)
        assert "⠲" in result, f"소수점 ⠲ 없음: {result!r}"

    def test_comma_is_different_cell_from_decimal(self) -> None:
        """제41항 vs 제43항: 자릿점(,)=⠂, 소수점(.)=⠲ — 다른 점자."""
        decimal_result = digits_to_braille("0.5")
        comma_result   = digits_to_braille("1,000")
        assert "⠲" in decimal_result, f"소수점(⠲) 없음: {decimal_result!r}"
        assert "⠂" in comma_result,   f"자릿점(⠂) 없음: {comma_result!r}"

    def test_negative(self) -> None:
        result = digits_to_braille("-5")
        assert result.startswith(_NUMBER_INDICATOR)
        assert "⠤" in result


class TestDigitsToBrailleExact:
    """규정 기반 정확한 점자 셀 검증."""

    def test_decimal_0_48(self) -> None:
        """제43항: 0.48 → ⠼⠚⠲⠙⠓ (소수점=⠲, 수표 재삽입 없음)."""
        assert digits_to_braille("0.48") == "⠼⠚⠲⠙⠓"

    def test_comma_9375(self) -> None:
        """제41항: 9,375 → ⠼⠊⠂⠉⠛⠑ (자릿점=⠂, 수표 재삽입 없음)."""
        assert digits_to_braille("9,375") == "⠼⠊⠂⠉⠛⠑"

    def test_number_indicator_not_repeated_after_comma(self) -> None:
        """제41항: 자릿점 뒤 수표 재삽입 금지."""
        result = digits_to_braille("1,000")
        assert result.count(_NUMBER_INDICATOR) == 1, (
            f"수표(⠼)가 {result.count(_NUMBER_INDICATOR)}번 나타남: {result!r}"
        )

    def test_number_indicator_not_repeated_after_decimal(self) -> None:
        """제43항: 소수점 뒤 수표 재삽입 금지."""
        result = digits_to_braille("3.14")
        assert result.count(_NUMBER_INDICATOR) == 1, (
            f"수표(⠼)가 {result.count(_NUMBER_INDICATOR)}번 나타남: {result!r}"
        )

    def test_negative_3(self) -> None:
        """수학 제17항: 음수 부호는 ⠤."""
        assert digits_to_braille("-3") == "⠼⠤⠉"

    def test_large_number_1234(self) -> None:
        """제40항: 1234 → ⠼⠁⠃⠉⠙."""
        assert digits_to_braille("1234") == "⠼⠁⠃⠉⠙"


class TestConvertLatex:
    """수학 점자 변환 규정 기반 검증."""

    def test_fraction_denominator_before_bar(self) -> None:
        """수학 제7항: 분수는 분모, 분수표(⠌), 분자 순서."""
        result = convert_latex("\\frac{1}{2}")
        bar_pos = result.index("⠌")
        assert "⠃" in result[:bar_pos], (
            f"분모(⠃)가 분수표(⠌) 앞에 없음: {result!r}"
        )

    def test_fraction_exact(self) -> None:
        """수학 제7항: \\frac{{1}}{{2}} = 분모(⠼⠃) + 분수표(⠌) + 분자(⠼⠁)."""
        assert convert_latex("\\frac{1}{2}") == "⠼⠃⠌⠼⠁"

    def test_sqrt_indicator(self) -> None:
        """수학 제22항: 근호 시작자 ⠜."""
        assert "⠜" in convert_latex("\\sqrt{x}")

    def test_superscript_indicator(self) -> None:
        """수학 제18항: 위첨자 ⠘."""
        assert "⠣" in convert_latex("x^2")  # ^2 관행 약기(정답 규정형 0회)

    def test_sin_indicator(self) -> None:
        """수학 삼각함수 제47항: sin → ⠖⠎ (6s)."""
        assert "⠖⠎" in convert_latex("\\sin(x)")

    def test_cos_indicator(self) -> None:
        """수학 삼각함수 제47항: cos → ⠖⠉ (6c)."""
        assert "⠖⠉" in convert_latex("\\cos(x)")

    def test_pi_indicator(self) -> None:
        """\\pi → 그리스 문자 표시 포함."""
        assert "⠨" in convert_latex("\\pi")

    def test_decimal_in_formula(self) -> None:
        """제43항: 수식 내 소수점은 ⠲ (convert_latex 경유)."""
        result = convert_latex("0.48")
        assert "⠲" in result, f"소수점 ⠲ 없음: {result!r}"
        assert result.count(_NUMBER_INDICATOR) == 1, "수표 중복 삽입"


class TestMathOperators:
    """수식 연산자·관계·화살표 점형 (한국 점자 규정 수학 제2~4항·제61항). FIX-01.

    근본원인 회귀: 규정 점자폰트 글자(5/9/3/;)를 한국 숫자점형으로 오독하던 버그 방지.
    """

    def test_plus(self) -> None:
        assert convert_latex("3+2") == "⠼⠉⠢⠼⠃"          # 덧셈표 ⠢(폰트 5), ⠑ 아님

    def test_minus_binary(self) -> None:
        assert "⠔" in convert_latex("3 - 2")             # 뺄셈표 ⠔(폰트 9), ⠊ 아님

    def test_equals(self) -> None:
        assert "⠒⠒" in convert_latex("x=y")              # 등호 ⠒⠒(폰트 33), ⠉⠉ 아님

    def test_leq(self) -> None:
        assert "⠖⠖" in convert_latex("x \\leq 5")        # ≤ ⠖⠖(66, ASCII 6=⠖ — 구 ⠦ 폰트 오독 정정)

    def test_geq(self) -> None:
        assert "⠲⠲" in convert_latex("x \\geq 5")        # ≥ ⠲⠲(폰트 44)

    def test_neq(self) -> None:
        # ≠ 규정(수학 제4항 1호)은 .33(⠨⠒⠒)이나 도서 관행은 .3(⠨⠒) —
        # gold 수학2 .3 91회 vs .33 0회(2026-07-20 실측, F4). book 모드 기본.
        assert "⠨⠒" in convert_latex("x \\neq y")
        assert "⠨⠒⠒" not in convert_latex("x \\neq y")

    def test_times(self) -> None:
        assert "⠡" in convert_latex("3 \\times 4")       # × ⠡(폰트 *)

    def test_div(self) -> None:
        assert "⠌⠌" in convert_latex("6 \\div 2")        # ÷ ⠌⠌(폰트 //)

    def test_subscript(self) -> None:
        assert "⠰" in convert_latex("a_2")               # 아래첨자 ⠰(폰트 ;), ⠆ 아님

    def test_arrow_right(self) -> None:
        assert "⠒⠕" in convert_latex("x \\to y")         # → ⠒⠕(폰트 3o)


class TestTranslator:

    def test_hangul_nonempty(self) -> None:
        assert len(translate_tagged_text("가나다")) > 0

    def test_english_roman_indicator(self) -> None:
        """한글 문장 내 영어 단어에 로마자표(⠴) 삽입 — braillify는 순수 영어 입력에는 ⠴ 미삽입."""
        result = translate_tagged_text("번역 Hello")
        assert "⠴" in result, "영어 앞 로마자표 ⠴ 누락"

    def test_number_in_text_gets_indicator(self) -> None:
        result = translate_tagged_text("5번")
        assert _NUMBER_INDICATOR in result

    def test_formula_tag_fraction_order(self) -> None:
        """수학 제7항: \\frac{1}{2} → 분모(⠃) before 분수표(⠌) before 분자(⠁)."""
        result = translate_tagged_text("<!수식>\\frac{1}{2}<!/수식>")
        assert "⠌" in result
        bar_pos = result.index("⠌")
        assert "⠃" in result[:bar_pos], f"분모(⠃)가 분수표(⠌) 앞에 없음: {result!r}"
        assert "⠁" in result[bar_pos:], f"분자(⠁)가 분수표(⠌) 뒤에 없음: {result!r}"

    def test_formula_tag_decimal(self) -> None:
        """제43항: <!수식>0.48<!/수식> → 소수점 ⠲ 포함."""
        result = translate_tagged_text("<!수식>0.48<!/수식>")
        assert "⠲" in result, f"소수점 ⠲ 없음: {result!r}"

    def test_other_tags_stripped(self) -> None:
        result = translate_tagged_text("<em>텍스트</em>")
        assert "<em>" not in result
        assert len(result) > 0

    def test_mixed_korean_english(self) -> None:
        result = translate_tagged_text("Hello 세계")
        assert "⠴" in result        # 영어 로마자 시작 표시
        assert "⠲" in result        # 영어 로마자 종료 표시

    def test_number_in_korean_sentence(self) -> None:
        """제40항: 한글 문장 내 숫자도 수표 + 점자로 변환."""
        result = translate_tagged_text("제20일")
        assert _NUMBER_INDICATOR in result


class TestSymbolGlyphs:
    """특수기호 점형 (한국 점자 규정 제49·53·60항·수학 제3·4·60항). FIX-11/12 회귀.

    규정 점자폰트 글자를 한국 숫자점형으로 오독하던 symbol_table 버그 방지.
    """

    @pytest.mark.parametrize("symbol,expected", [
        ("=", "⠒⠒"), ("≤", "⠖⠖"), ("≥", "⠲⠲"), ("≠", "⠨⠒⠒"),
        ("<", "⠔⠔"), (">", "⠢⠢"),
        ("→", "⠒⠕"), ("←", "⠪⠒"),
        ("∈", "⠖"), ("⊂", "⠖⠂"), ("≡", "⠶⠶"),
        ("…", "⠠⠠⠠"), ("《", "⠰⠶"), ("※", "⠐⠔"), ("〃", "⠴⠴"),
        ("○", "⠸⠴⠇"), ("□", "⠸⠶⠇"),
        ("①", "⠼⠂"), ("⑩", "⠼⠂⠴"), ("⑳", "⠼⠆⠴"),  # 제64항 한 단 내림
        ("㉠", "⠶⠿⠁⠶"), ("㉮", "⠶⠫⠶"),  # 제64항 동그라미 문자(⠶ 래퍼 + 온표/약자)
    ])
    def test_symbol_glyph(self, symbol: str, expected: str) -> None:
        from app.ai.braille.symbol_rules import substitute_symbols
        got = substitute_symbols(symbol)
        assert got == expected, f"{symbol!r} → {got!r}, 기대 {expected!r}"
