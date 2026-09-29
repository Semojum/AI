"""T36 — 화학 반응식 화살표 LaTeX 명령이 표에 없어 지워지던 것(과학 점자 제18항 1호, 재추출 4815행)."""
import pytest

from app.ai.braille.kor_math_rules import convert_latex


@pytest.mark.parametrize("latex, cells", [
    (r"\rightleftharpoons", "⠪⠶⠕"),      # ⇌ = ⇄ `[7O`
    (r"\leftrightharpoons", "⠪⠶⠕"),
    (r"\longrightarrow", "⠒⠕"),          # → `3o`
    (r"\longleftarrow", "⠪⠒"),           # ← `{3`
])
def test_반응식_화살표가_사라지지_않는다(latex, cells):
    assert convert_latex(latex) == cells


def test_반응식_안에서도_남는다():
    assert "⠪⠶⠕" in convert_latex(r"\mathrm{NH}_{3} + \mathrm{H}_{2}\mathrm{O} \rightleftharpoons \mathrm{NH}_{4}^{+}")
