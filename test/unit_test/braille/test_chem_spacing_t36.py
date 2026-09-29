"""T36 ②-b 간격 갈래 — 화학 반응식 기호 앞뒤 한 칸(과학 점자 제18항 1호 4815행 · 제8항 4475행).

기체·침전 기호는 분자식에 붙인다(제18항 2호). 이온 부호 ⁺ 는 띄우지 않는다.
"""
import pytest

from app.ai.braille.kor_math_rules import chem_operator_spacing, convert_latex


@pytest.mark.parametrize("latex, want", [
    (r"2\mathrm{H}_{2} + \mathrm{O}_{2} \rightarrow 2\mathrm{H}_{2}\mathrm{O}",          # 4817행
     "⠼⠃⠠⠓⠰⠼⠃⠀⠢⠀⠠⠠⠠⠕⠰⠼⠃⠀⠒⠕⠀⠼⠃⠐⠓⠰⠼⠃⠕⠠⠄"),
    (r"\mathrm{Ag}^{+} + \mathrm{Cl}^{-} \rightarrow \mathrm{AgCl} \downarrow",          # 제18항 2호 예문
     "⠠⠁⠛⠘⠢⠀⠢⠀⠠⠉⠇⠘⠔⠀⠒⠕⠀⠠⠁⠛⠠⠉⠇⠘⠒⠕"),
    (r"\mathrm{H} _ {2} \mathrm{S} > \mathrm{SO} _ {2} > \mathrm{Cl} _ {2}",               # 4393행 · 제8항
     "⠠⠠⠠⠓⠰⠼⠃⠎⠀⠢⠢⠀⠎⠕⠰⠼⠃⠠⠄⠀⠢⠢⠀⠠⠉⠇⠰⠼⠃"),
])
def test_반응식_기호_간격(latex, want):
    assert convert_latex(latex).strip("⠴⠲") == want


def test_이온_부호는_연산_기호가_아니다():
    # `Ca²⁺ + 2Cl⁻` 의 ⠘⠼⠃⠢ 와 더하기 ⠢ 가 비교 기호 ⠢⠢ 로 읽히지 않는다
    assert chem_operator_spacing("⠠⠉⠁⠘⠼⠃⠢⠢⠼⠃⠠⠉⠇⠘⠔") == "⠠⠉⠁⠘⠼⠃⠢⠀⠢⠀⠼⠃⠠⠉⠇⠘⠔"


def test_수식은_붙인다():
    assert "⠀⠢⠀" not in convert_latex("x+1")
