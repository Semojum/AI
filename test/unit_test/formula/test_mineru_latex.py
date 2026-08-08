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


class TestSpacedDigits:
    r"""MinerU가 자리마다 띄어 낸 다자리 수 복원 (2026-08-02).

    기대값은 규정에서 직접 세운다 — 수표(⠼)는 **수 하나에 한 번**이고 자릿수는
    ⠁⠃⠉⠙⠑⠋⠛⠓⠊⠚(1~9,0). 그러므로 12 = ⠼⠁⠃이지 ⠼⠁ ⠼⠃가 아니다.
    코퍼스 실측: formula 429개 중 43개(10.0%)에 이 분리가 있었다.
    """

    def test_다자리수_한_수로_붙는다(self):
        assert convert_latex("1 2") == "⠼⠁⠃"
        assert convert_latex("6 0") == "⠼⠋⠚"
        assert convert_latex("1 0") == "⠼⠁⠚"

    def test_수표는_수마다_한_번(self):
        # 분리돼 있으면 자리마다 수표가 찍힌다 — 그게 고치려는 증상이다.
        assert convert_latex("1 2").count("⠼") == 1

    def test_분수_분모_다자리(self):
        # 5/12 — 한국 점자는 분모를 먼저 쓴다(십이분의 오): 12 ⠌ 5
        assert convert_latex(r"\frac {5}{1 2}") == "⠼⠁⠃⠌⠼⠑"

    def test_공백버전과_붙임버전_동일(self):
        for spaced, tight in ((r"6 0 p", "60p"), (r"\ln 1 0", r"\ln 10"),
                              (r"x ^ {1 0}", "x^{10}")):
            assert convert_latex(spaced) == convert_latex(tight)

    def test_쉼표는_넘지_않는다(self):
        # 집합 원소 {1, 2, 4, 5} — 붙이면 값 자체가 바뀐다(1245).
        out = convert_latex(r"\{1, 2, 4, 5 \}")
        assert out.count("⠼") == 4

    def test_행렬_칸은_붙지_않는다(self):
        # & 로 나뉜 칸은 서로 다른 수다. 평탄화가 &를 공백으로 바꾸므로,
        # 숫자 붙이기가 그보다 뒤에 오면 여기서 깨진다(순서 회귀 감시).
        out = convert_latex(r"\begin{pmatrix} 1 & 2 \\ 3 & 4 \end{pmatrix}")
        assert out.count("⠼") == 4

    def test_두_칸_이상_벌어지면_안_붙인다(self):
        assert convert_latex("1  2").count("⠼") == 2


class TestScienceBraille:
    r"""「과학 점자」 제1항 — 화학식은 로마자표로 열고 종료표로 닫는다 (원장 M-01).

    규정 원문(규정_텍스트.txt 4322행~)의 BRF 예문을 유니코드로 옮긴 값이 기대값이다.
      H          `0,h4`                → ⠴⠠⠓⠲
      Li, Na, K  `0,li1`,na1`,k4`      → 로마자표·종료표는 **식 전체에 한 번**
    제2항 이온 위첨자(⠘)·부호(+=⠢, −=⠔)는 이미 우리 출력과 같아 손대지 않았다.
    """

    def test_화학식은_로마자표로_감싼다(self):
        out = convert_latex(r"\mathrm{H} ^ {+} \mathrm{Hb} + \mathrm{O} _ {2}")
        assert out.startswith("⠴") and out.endswith("⠲")

    def test_로마자표는_한_번만(self):
        out = convert_latex(r"\mathrm{Hb} + 4 \mathrm{O} _ {2} \xrightarrow {결합} \mathrm{Hb}")
        assert out.count("⠴") == 1 and out.count("⠲") == 1

    def test_이온_위첨자와_부호는_규정형(self):
        # 규정 제2항 `0,h^5` = ⠴⠠⠓⠘⠢ — 위첨자 ⠘, + 는 ⠢.
        # 단, 반응식 **안에서만** 화학으로 판정한다(아래 test_기하_표기는_화학이_아니다 참조).
        out = convert_latex(r"\mathrm{H} ^ {+} + \mathrm{Hb} \xrightarrow {x} \mathrm{HbO}")
        assert "⠠⠓⠘⠢" in out and out.startswith("⠴")

    def test_기하_표기는_화학이_아니다(self):
        """점·선분·도형 이름도 \mathrm으로 적고 글자가 원소 기호와 겹친다(P·O·Q·C·N…).

        `\overline{\mathrm{PQ}}^2`(선분 PQ의 제곱)에 로마자표가 붙는 사고가 실제로 났다.
        """
        from app.ai.braille.kor_math_rules import _looks_chemical
        for s in (r"\overline {{\mathrm{PQ}}} ^ {2} = \overline {{\mathrm{OP}}} ^ {2}",
                  r"\triangle \mathrm{ABC}",
                  r"\mathrm{AB} \perp \mathrm{CD}",
                  r"\mathrm{C} = 2 \pi r"):
            assert not _looks_chemical(s), s
            assert not convert_latex(s).startswith("⠴"), s

    def test_수학식은_건드리지_않는다(self):
        for s in (r"x ^ {2} + 3 x - 1 = 0", r"\frac {5}{12}", r"\lim _ {x \to 0} x"):
            out = convert_latex(s)
            assert not out.startswith("⠴"), s

    def test_원소기호_하나만으로는_화학식이_아니다(self):
        # 판정은 \mathrm·반응 화살표 + 원소 기호 2개 이상. 변수 x·함수 f를 삼키면 안 된다.
        from app.ai.braille.kor_math_rules import _looks_chemical
        assert not _looks_chemical(r"\mathrm{C} = 2 \pi r")
        assert _looks_chemical(r"\mathrm{H} _ {2} \mathrm{O}")
