"""인자를 잃은 함수 이름 명령이 통째로 사라지지 않는지 회귀.

추출이 수식을 텍스트로 흘리면 `lim`만 한 줄에 남는다(실측: 수학2 p016). 그러면
`inline_math.wrap`이 `\\lim`으로 감싸는데, 인자가 없어 미처리 명령 제거 규칙에
그대로 먹혀 **극한 기호가 흔적도 없이 사라졌다**. mode b는 줄 단위로 쪼개므로
그 줄이 통째로 `[처리 불가]`가 됐다.

규정 제51항: "극한 기호 lim는 **lim으로 적은** 다음 범위의 시작(변수), 화살표,
점근값의 …" — 이름을 그대로 적는다. `\\lim_{x \\to a}` 정상 경로도 ⠇⠊⠍를 낸다.
"""
import pytest

from app.ai.braille.kor_math_rules import convert_latex
from app.ai.braille.translator import translate_tagged_text


class TestBareFunctionSurvives:
    """이름이 곧 읽을 내용인 명령 — 지우면 점역사가 있었던 줄도 모른다."""

    @pytest.mark.parametrize("latex,expected", [
        (r"\lim", "⠇⠊⠍"),
        (r"\max", "⠍⠁⠭"),
        (r"\min", "⠍⠊⠝"),
    ])
    def test_인자_없어도_이름이_남는다(self, latex, expected):
        assert convert_latex(latex) == expected

    def test_인자가_있으면_종전대로(self):
        # 정상 경로는 건드리지 않았다 — 같은 ⠇⠊⠍로 시작해야 한다.
        assert convert_latex(r"\lim_{x \to a} f(x)").startswith("⠇⠊⠍")

    def test_텍스트_경로에서도_산다(self):
        # inline_math.wrap이 백슬래시를 붙이는 경로. 종전엔 빈 문자열이었다.
        assert translate_tagged_text("lim") == "⠇⠊⠍"


class TestStructuralCommandsStillStripped:
    """구조 명령은 계속 지운다 — 이름을 남기면 본문에 쓰레기 글자가 찍힌다."""

    @pytest.mark.parametrize("latex", [r"\begin", r"\left", r"\right", r"\frac", r"\quad"])
    def test_이름이_안_남는다(self, latex):
        assert convert_latex(latex) == ""
