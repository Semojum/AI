"""T36 ②-b — 식 전체 대문자 구절표(과학 점자 제4항). 기대값은 eval `temp/n32/기대값_과학42_braille.md`.

구절표 표지만 본다(`⠠⠠⠠ … ⠠⠄` 자리). `+`·`→` 앞뒤 간격 · 구간 밖 `HCl` 대문자 단어표 · 헛 로마자표는
갈래가 달라 따로 고친다(pm: 한 PR 에 몰지 말 것).
"""
import re

import pytest

from app.ai.braille.kor_math_rules import convert_latex
from app.ai.braille.translator import translate_body


def _phrase(cells: str) -> list[str]:
    """구절표 구간(⠠⠠⠠ 부터 ⠠⠄ 까지)을 빈칸 빼고 뽑는다."""
    return [m.replace("⠀", "") for m in re.findall(r"⠠⠠⠠.*?⠠⠄", cells)]


@pytest.mark.parametrize("latex, want", [
    # 재추출 4393행 `,,,h;#bs`55`so;#b,'`55`,cl;#b` — 두 글자 Cl₂ 는 구간 밖
    (r"\mathrm{H} _ {2} \mathrm{S} > \mathrm{SO} _ {2} > \mathrm{Cl} _ {2}", ["⠠⠠⠠⠓⠰⠼⠃⠎⠢⠢⠎⠕⠰⠼⠃⠠⠄"]),
    # 4406행 — Na 에서 끊기고 HCl 은 한 글자 원소가 하나뿐이라 구절표 없음
    (r"\mathrm{CH} _ {3} \mathrm{COONa} + \mathrm{HCl} \rightarrow \mathrm{CH} _ {3} \mathrm{COOH} + \mathrm{NaCl}",
     ["⠠⠠⠠⠉⠓⠰⠼⠉⠐⠉⠕⠕⠠⠄", "⠠⠠⠠⠉⠓⠰⠼⠉⠐⠉⠕⠕⠓⠠⠄"]),
    # 4400행 — 계수 2 뒤 H 에서는 시작 못 한다(3호), O₂ 부터 끝까지 · 제5항 ⠐
    (r"2\mathrm{H}_{2} + \mathrm{O}_{2} \rightarrow 2\mathrm{H}_{2}\mathrm{O}", ["⠠⠠⠠⠕⠰⠼⠃⠒⠕⠼⠃⠐⠓⠰⠼⠃⠕⠠⠄"]),
    # 4414행 — 화살표 ↑ 앞에서 닫는다([붙임 2])
    (r"\mathrm{P} _ {4} \mathrm{S} _ {3} + 8 \mathrm{O} _ {2} \rightarrow 2 \mathrm{P} _ {2} \mathrm{O} _ {5} + 3 \mathrm{SO} _ {2} \uparrow",
     ["⠠⠠⠠⠏⠰⠼⠙⠎⠰⠼⠉⠢⠼⠓⠕⠰⠼⠃⠒⠕⠼⠃⠏⠰⠼⠃⠕⠰⠼⠑⠢⠼⠉⠎⠕⠰⠼⠃⠠⠄"]),
])
def test_제품_경로_식_전체_구절표(latex, want):
    assert _phrase(convert_latex(latex)) == want


def test_글_경로_화학식_줄():
    assert translate_body("CH₃COOH")[0][0] == "⠠⠠⠠⠉⠓⠰⠼⠉⠐⠉⠕⠕⠓⠠⠄"          # 4366행
    assert translate_body("C₂H₅OH")[0][0].startswith("⠠⠠⠠⠉⠰⠼⠃")


def test_원소마다인_자리는_그대로():
    assert translate_body("H₂O와 O₂ 및 NaCl은")[0][0].startswith("⠴⠠⠓⠰⠼⠃⠠⠕")   # 제7항 1호 4435행
    assert translate_body("CO₂가")[0][0].startswith("⠴⠠⠉⠠⠕⠰⠼⠃")
    assert translate_body("HCO₃⁻는 중탄산 이온이다.")[0][0].startswith(
        "⠴⠠⠠⠠⠓⠉⠕⠰⠼⠉⠘⠔⠠⠄⠲⠉⠵")                                            # 4350행 · 이중 적용 없음
