r"""MinerU식 LaTeX 입력 정규화 회귀 테스트.

MinerU는 공백 많은 LaTeX(`\frac {1}{a _ {i}}`)·`$$` 구분자·`\left( \right)`·코드펜스를
낸다. convert_latex가 이를 정규화해 구조(분수·첨자·근호)를 점역하는지 확인한다.
"""
from app.ai.braille.kor_math_rules import convert_latex, _normalize_latex_input


class TestNormalizeMinerULatex:
    def test_dollar_제거(self):
        assert "$" not in _normalize_latex_input("$$x$$")

    def test_분수_공백축약(self):
        assert _normalize_latex_input(r"\frac {1}{2}") == r"\frac{1}{2}"

    def test_첨자_공백축약(self):
        assert _normalize_latex_input("a _ {i}") == "a_{i}"
        assert _normalize_latex_input("x ^ {2}") == "x^{2}"

    def test_leftright_제거(self):
        assert "\\left" not in _normalize_latex_input(r"\left( x \right)")
        assert "(" in _normalize_latex_input(r"\left( x \right)")

    def test_코드펜스_제거(self):
        assert "`" not in _normalize_latex_input("```latex\nx\n```")
        assert "latex" not in _normalize_latex_input("```latex\nx\n```")

    def test_text_래퍼_언랩(self):
        # \text는 이제 convert_latex가 처리한다(번역 훅 등록 시 한글 점자, 미등록 시 내용 보존).
        # 어느 경우든 \text 명령 자체는 출력에 남으면 안 된다(영어 음역 금지).
        out = convert_latex(r"\text{값}")
        assert "\\text" not in out and "text" not in out

    def test_boxed_언랩(self):
        # \boxed{X}는 내용만 남고 'boxed' 음역 잔재가 없어야 한다(P3).
        out = convert_latex(r"\boxed{5}")
        assert "boxed" not in out and "\\boxed" not in out
        assert "⠼⠑" in out  # 5는 수표와 함께


class TestConvertMinerULatex:
    def test_분수_점역(self):
        # 분수: 분모⠌분자 (수학 제7항)
        assert convert_latex(r"\frac{1}{2}") == "⠼⠃⠌⠼⠁"

    def test_mineru_분수_공백버전_동일(self):
        assert convert_latex(r"\frac {1}{2}") == convert_latex(r"\frac{1}{2}")

    def test_아래첨자_점역(self):
        # 빈 결과·원시 underscore 없이 점역
        out = convert_latex("a _ {i}")
        assert out and "_" not in out

    def test_위첨자_점역(self):
        out = convert_latex("x ^ {2}")
        assert out and "^" not in out

    def test_dollar래핑_무영향(self):
        assert convert_latex(r"$$\frac{1}{2}$$") == convert_latex(r"\frac{1}{2}")

    def test_latex명령_알파벳누출_없음(self):
        # \frac이 ⠸⠡⠋⠗⠁⠉(f-r-a-c)처럼 알파벳으로 새지 않아야 함
        out = convert_latex(r"\frac{1}{2}")
        assert "⠋⠗⠁⠉" not in out
