"""로마 숫자 점역 회귀 테스트 (D-1).

버그: 로마 숫자(Ⅰ Ⅱ … 유니코드 Number Forms)가 SYMBOL_TABLE·알파벳 어디에도 없어
braillify가 'Invalid character'로 거부 → 같은 페이지 텍스트가 통째로 손실됐다.

규정(한국 점자):
  제36항 "로마 숫자는 해당 로마자를 사용하여 적는다" → Ⅱ = 로마자 II.
  제29항 "국어 문장 안에 로마자가 나오면 앞에 로마자표 ⠴, 뒤에 종료표 ⠲".
기대 글리프는 규정에서 수동 도출한다(순환검증 금지). 로마자표·종료표·대문자표는
braillify 유무와 무관하게 고정이므로 결정적으로 단언한다.
"""
from __future__ import annotations

from app.ai.braille.translator import (
    _normalize_roman_numerals,
    translate_tagged_text,
)

_ROMAN = "⠴"   # 로마자표 (제29항)
_END = "⠲"     # 로마자 종료표 (제29항)


class TestNormalize:
    def test_대문자_로마숫자_정규화(self):
        assert _normalize_roman_numerals("Ⅱ. 물질") == "II. 물질"
        assert _normalize_roman_numerals("Ⅰ Ⅲ Ⅳ Ⅹ") == "I III IV X"
        assert _normalize_roman_numerals("Ⅻ") == "XII"

    def test_소문자_로마숫자_정규화(self):
        assert _normalize_roman_numerals("ⅲ장") == "iii장"

    def test_멱등(self):
        once = _normalize_roman_numerals("Ⅱ. 물질")
        assert _normalize_roman_numerals(once) == once  # 재적용해도 불변

    def test_로마숫자_없는_텍스트_불변(self):
        assert _normalize_roman_numerals("물의 상태 변화 100℃") == "물의 상태 변화 100℃"


class TestRomanTranslate:
    def test_크래시_없음(self):
        # 구버그: Invalid character로 예외 → 예외 없이 점역돼야 한다.
        for t in ["Ⅰ", "Ⅱ", "Ⅲ", "Ⅳ", "Ⅴ", "Ⅹ", "Ⅻ", "Ⅱ. 물질의 상태 변화"]:
            out = translate_tagged_text(t)
            assert out and isinstance(out, str)

    def test_국어문장속_로마숫자_로마자표_종료표(self):
        # 제29항: 한글과 섞인 로마 숫자는 ⠴ … ⠲ 로 감싼다.
        out = translate_tagged_text("Ⅱ. 물질의 상태 변화")
        assert out.startswith(_ROMAN)        # 앞에 로마자표
        assert _END in out                   # 종료표 존재
        # 종료표 뒤에 한글 점자가 이어진다(로마자 구간이 'Ⅱ'에 한정).
        assert out.index(_END) < len(out) - 1

    def test_로마숫자_해당로마자_사용(self):
        # 제36항: Ⅰ=I(대문자 i 점형 ⠊ 포함), 한글표기로 둔갑하지 않는다.
        out = translate_tagged_text("Ⅰ. 서론")
        assert out.startswith(_ROMAN + "⠠⠊" + _END)   # 로마자표+대문자 i+종료표
