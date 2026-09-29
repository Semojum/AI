"""T36 ②-b ⠠⠠ 갈래 — 반응식 조각의 첨자 없는 화학식(`HCl`)이 대문자 단어표로 나가던 것.

과학 점자 제7항 1호(재추출 4433~4437행): 원소 기호는 앞에 대문자표 — `NaCl` = `,na,cl`.
규정 예문 4406행 `CH₃COONa +HCl →…` = `…,na`5`,h,cl`3o`…`.
"""
from app.ai.braille.kor_math_rules import convert_latex
from app.ai.braille.translator import translate_body


def test_반응식_속_HCl_은_원소마다():
    out = convert_latex(r"\mathrm{CH} _ {3} \mathrm{COONa} + \mathrm{HCl} \rightarrow \mathrm{CH} _ {3} \mathrm{COOH} + \mathrm{NaCl}")
    assert "⠀⠢⠀⠠⠓⠠⠉⠇⠀⠒⠕⠀" in out and "⠠⠠⠓" not in out
    assert "⠠⠓⠠⠉⠇" in translate_body("CH₃COONa +HCl →CH₃COOH +NaCl")[0][0]


def test_두_글자_원소가_있으면_원소마다():
    assert convert_latex("HCl") == "⠠⠓⠠⠉⠇"
    assert convert_latex("NaCl") == "⠠⠝⠁⠠⠉⠇"


def test_수학_대문자는_그대로():
    assert convert_latex("AB") == "⠠⠠⠁⠃"        # A 는 원소가 아니다
