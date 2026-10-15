"""#1423 — 딩뱃 동그라미 숫자 ➀–➉ · ➊–➓(U+2780–2793)가 점자에서 빠지던 것.

「한국 점자 규정」 제64항(재추출 2566행): 동그라미 숫자는 수표 뒤에 숫자의 점형을 한 단 내려 적는다.
"""
import pytest

from app.ai.braille.translator import dropped_symbols, translate_plain

_LOW = "⠴⠂⠆⠒⠲⠢⠖⠶⠦⠔"     # 한 단 내린 0–9


def _want(n: int) -> str:
    return "⠼" + "".join(_LOW[int(d)] for d in str(n))


@pytest.mark.parametrize("cp", range(0x2780, 0x2794))
def test_dingbat_circled_digit_is_number_sign_plus_lowered_digits(cp):
    n = (cp - 0x2780) % 10 + 1
    assert translate_plain(f"가 {chr(cp)} 나") == f"⠫⠀{_want(n)}⠀⠉"


def test_dingbat_circled_digits_no_longer_counted_as_dropped():
    assert dropped_symbols("".join(chr(c) for c in range(0x2780, 0x2794)) + "▶") == {"▶": 1}


def test_bracket_after_dingbat_keeps_number():
    # ❶[…] 지우기는 언어 인용 콜아웃 관행(❶–❻)이다. 근거 없는 ➊ 에는 넓히지 않는다.
    assert translate_plain("➊[가]").startswith("⠼⠂")
    assert not translate_plain("❶[가]").startswith("⠼⠂")
