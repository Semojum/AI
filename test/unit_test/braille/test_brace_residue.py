"""구조 단계가 안 먹은 중괄호가 문장부호로 새던 문제 (2026-08-17).

기호표가 `{`를 한글 중괄호 ⠦⠂로 바꾸는데, 거기까지 온 중괄호는 문장부호가 아니라
**LaTeX 묶음 잔재**다. 잔재를 걷는 단계(13)가 기호표(12)보다 뒤에 있어 손댈 수 없었다.

중괄호 세 변형 중 세 번째다.
    없음      \sqrt3            → 근호 소실        (앞서 수정)
    두 겹     \overline{{X}}    → 괄호 셀 잔재      (앞서 수정)
    안 먹힘   \cos{(x)}         → 괄호 셀 잔재      (이 파일)

gold 대조는 eval 실측(array 실패 35건 중 9건 + 비array 3건).
"""
import pytest

from app.ai.braille.kor_math_rules import convert_latex


def _cells(s: str) -> str:
    return "".join(c for c in s if 0x2800 <= ord(c) <= 0x28FF and c != "⠀")


@pytest.mark.parametrize("latex,gold", [
    (r"\cos {(\angle \mathrm{BIA})}", "⠖⠉⠦⠹⠠⠠⠃⠊⠁⠴"),
    (r"\cos{(x)}", "⠖⠉⠦⠭⠴"),
])
def test_안_먹힌_중괄호가_문장부호로_안_샌다(latex, gold):
    assert _cells(convert_latex(latex)) == _cells(gold)


@pytest.mark.parametrize("latex,gold", [
    (r"\sqrt{x^{2}}", "⠜⠭⠘⠼⠃"),
    (r"\sqrt {1 - \sin^{2} γ}", "⠜⠷⠼⠁⠔⠖⠎⠘⠼⠃⠨⠛⠾"),
    (r"\sqrt{a+b^{2}}", "⠜⠷⠁⠢⠃⠘⠼⠃⠾"),
])
def test_근호_안에_중괄호가_있어도_근호가_안_사라진다(latex, gold):
    """정규식은 중첩 중괄호를 못 읽어 `\\sqrt{x^{2}}`가 통째로 안 잡혔다.

    코퍼스 2,413건 중 188건(8%)이 이 꼴이고 전부 근호를 잃었다.
    """
    assert _cells(convert_latex(latex)) == _cells(gold)


def test_단순_근호는_그대로():
    assert convert_latex(r"\sqrt{2}") == "⠜⠼⠃"
    assert convert_latex(r"\sqrt[3]{8}") == "⠼⠉⠻⠼⠓"
