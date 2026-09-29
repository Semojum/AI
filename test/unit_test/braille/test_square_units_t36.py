"""T36 ① — 사각 단위 문자(U+3380~33DF)가 사라지거나 예외로 죽던 것(eval T32 결함 1, 제69항).

종전: `부피는 3 ㎥이다` → `3 이다`(㎥ 소실) · `kg/㎥` → ValueError(#956 회귀, 요소 통째 [처리 불가]).
규정 예문(재추출 2682행~): `96.7 ㎒` = `0,m,hz4` · `1 μm` = `0.mm4` · `160㎎/㎗` = `0mg_/dl4` ·
`cal/㎠/min` = `0cal_/cm~#b_/…`.
"""
import pytest

from app.ai.braille.symbol_rules import SQUARE_UNIT_TABLE, SYMBOL_TABLE
from app.ai.braille.translator import dropped_symbols, translate_body


def _b(text: str) -> str:
    return translate_body(text)[0][0]


@pytest.mark.parametrize("text, cells", [
    ("부피는 3 ㎥이다.", "⠼⠉⠀⠴⠍⠘⠼⠉⠕⠊"),        # m³
    ("전압 5 ㎷를", "⠴⠍⠠⠧⠲⠐⠮"),               # mV
    ("시간(㎳)", "⠴⠍⠎⠲"),                      # ms
    ("1 ㎛는", "⠴⠨⠍⠍⠲⠉⠵"),                  # μm = 규정 `0.mm4`
    ("저항 2 ㏀", "⠴⠅⠠⠨⠺⠲"),                  # kΩ
])
def test_사각_단위가_사라지지_않는다(text, cells):
    assert cells in _b(text)
    assert not dropped_symbols(text)


def test_빗금_복합_단위가_죽지_않는다():
    assert _b("kg/㎥") == "⠴⠅⠛⠸⠌⠍⠘⠼⠉"
    assert "⠴⠛⠸⠌⠉⠍⠘⠼⠉" in _b("밀도는 1 g/㎤이다.")
    assert "⠼⠁⠚⠚⠚⠀⠴⠅⠛⠸⠌⠍⠘⠼⠉⠕⠊" in _b("밀도는 1000 kg/㎥이다.")   # 한 구간


def test_종전_단위는_그대로():
    assert "⠴⠍⠛⠸⠌⠙⠇⠲" in _b("160㎎/㎗를")          # 규정 예문
    assert "⠴⠠⠍⠠⠓⠵⠲" in _b("96.7 ㎒이다.")          # 규정 예문 `0,m,hz4`
    assert SYMBOL_TABLE["㎡"] == "⠴⠍⠘⠼⠃"


def test_단위가_아닌_글자는_만들지_않는다():
    assert "㏂" not in SQUARE_UNIT_TABLE and "㏒" not in SQUARE_UNIT_TABLE
    assert "㎥" not in SYMBOL_TABLE             # 역점역 표를 오염시키지 않는다
