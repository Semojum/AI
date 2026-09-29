"""T36 ⑤ — 유니코드 아래첨자 글자(ₑ 등)가 표에 없어 `logₑ` 의 밑이 사라지던 것(eval T32 결함 5)."""
from app.ai.braille.translator import convert_latex, translate_body


def test_로그_밑_e_가_남는다():
    # 텍스트 경로가 LaTeX 경로(규정 일치)와 같은 점형을 낸다
    assert translate_body("logₑ(2+h)의 값")[0][0].startswith(convert_latex(r"\log_{e}(2+h)"))


def test_아래첨자_글자():
    assert translate_body("xₐ+xₑ")[0][0] == "⠭⠰⠁⠢⠭⠰⠑"
