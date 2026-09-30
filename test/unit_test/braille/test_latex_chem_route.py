r"""LaTeX 로 온 단순 화학식은 평문 화학 경로와 같은 점자를 낸다(원장 B-24 · #1058).

규정 과학 제7항 1호(재추출 4435~4437행) 예문 `H₂O와 O₂ 및 NaCl은` = `0,h;#b,o4v`0,o;#b`eo2`…,
괄호 앞 종료표 없음 제34항(1709행). 종전 LaTeX 경로는 식 앞뒤 빈칸 · 둘째 식 로마자표 빠짐 ·
`(CO₂)` 괄호 앞 ⠲ 로 평문 경로와 갈렸다.
"""
import pytest

from app.ai.braille import inline_math
from app.ai.braille.translator import _latex_chem_to_unicode, translate_tagged_text


@pytest.mark.parametrize("latex,plain", [
    (r"이산화 탄소($\mathrm{CO}_{2}$)가", "이산화 탄소(CO₂)가"),
    (r"이산화 탄소($\mathrm{CO_{2}}$)가", "이산화 탄소(CO₂)가"),
    (r"$\mathrm{H}_{2}\mathrm{O}$와 $\mathrm{O}_{2}$ 및", "H₂O와 O₂ 및"),
    (r"$\mathrm{Na}^{+}{-}\mathrm{K}^{+}$ 펌프", "Na⁺-K⁺ 펌프"),
    (r"혈중 $\mathrm{Ca}^{2+}$ 농도", "혈중 Ca²⁺ 농도"),
])
def test_평문_화학_경로와_같다(latex, plain):
    assert _latex_chem_to_unicode(latex) == plain
    assert translate_tagged_text(latex) == translate_tagged_text(plain)


@pytest.mark.parametrize("src", [
    r"선분 $\overline{\mathrm{AB}}$",   # 다른 명령이 섞이면 수식
    r"$x_{2}$ 값",                       # \mathrm 없는 변수
    r"$\mathrm{NaCl}$",                   # 첨자·전하 없음 — 좁게 둔다
    r"$\mathrm{Ab}_{2}$",                 # 원소 아님
])
def test_화학식이_아니면_그대로(src):
    assert _latex_chem_to_unicode(src) == src


def test_수식_쪽의_원소_하나_첨자는_그대로():
    tok = inline_math.MATH_PAGE.set(True)
    try:
        assert _latex_chem_to_unicode(r"점 $\mathrm{P}_{1}$") == r"점 $\mathrm{P}_{1}$"
        assert _latex_chem_to_unicode(r"값은 $\mathrm{Na}^{+}$") == "값은 Na⁺"   # 전하는 수식 쪽에서도 화학식
    finally:
        inline_math.MATH_PAGE.reset(tok)
