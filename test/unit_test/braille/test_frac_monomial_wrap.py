"""분수 분모·분자의 단항의 곱을 묶음 괄호로 묶는다 (수학 점자 제6항 2호).

규정 원문 예시가 `(ab)/#a`(= ⠷⠁⠃⠾⠌⠼⠁)다. 기대값은 규정에서 수동 도출했다.

⚠ 2026-07-22에 곱 묶음을 되살렸다가 기각된 적이 있다(요소 win 4 : lose 42). 그때
깨진 것은 `\\sqrt{3}`·`f(x)`를 2인수로 세어 과잉으로 묶은 자리다. 그래서 여기서는
역슬래시·괄호가 없는 영숫자 덩어리만 묶는다 — 아래 두 반례가 그 경계를 지킨다.
"""
import pytest

from app.ai.braille.kor_math_rules import convert_latex


@pytest.mark.parametrize("latex,expected", [
    ("\\frac{1}{ab}", "⠷⠁⠃⠾⠌⠼⠁"),      # 규정 제6항 2호 예시 (ab)/#a
    ("\\frac{1}{2a}", "⠷⠼⠃⠐⠁⠾⠌⠼⠁"),
    ("\\frac{b}{2R}", "⠷⠼⠃⠠⠗⠾⠌⠃"),
])
def test_단항의_곱은_묶음_괄호로_묶는다(latex, expected):
    assert convert_latex(latex) == expected


@pytest.mark.parametrize("latex,expected", [
    ("\\frac{1}{2}", "⠼⠃⠌⠼⠁"),          # 단일 수 — 제7항 1호
    ("\\frac{a}{b}", "⠃⠌⠁"),             # 단일 문자
])
def test_단일_항은_안_묶는다(latex, expected):
    assert convert_latex(latex) == expected


@pytest.mark.parametrize("latex", ["\\frac{1}{\\sqrt{3}}", "\\frac{1}{f(x)}"])
def test_함수값은_안_묶는다_2026_07_22_기각_사유(latex):
    """√3·f(x)를 2인수로 세어 묶던 것이 종전 기각의 원인이었다."""
    assert "⠷" not in convert_latex(latex)
