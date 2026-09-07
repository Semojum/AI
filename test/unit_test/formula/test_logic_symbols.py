r"""관계·논리 기호 — 수학 점자 제32·34·60·61항.

표에 없어 **통째로 사라지던 것들**이다. `A \cong B` 가 `⠠⠁⠠⠃` 로,
`\vdash` 는 빈 문자열로 나갔다.

`\not X` 는 규정이 부정을 **뒤 기호 앞에 ⠨** 로 나타낸다(`A.,RB`·`A.6,A`).
LaTeX 은 `\not` 을 앞에 따로 쓰므로 0e 단계에서 합친다.
"""
import pytest

from app.ai.braille.kor_math_rules import convert_latex


def _b(t: str) -> str:
    return convert_latex(t).replace("⠀", "")


@pytest.mark.parametrize("tex,want", [
    (r"A \cong B", "⠈⠔⠒⠒"),          # 제32항
    (r"a \nsim b", "⠨⠈⠔"),           # 제34항
    (r"\vdash", "⠸⠒"),               # 제60항
    (r"\dashv", "⠈⠸⠒"),
    (r"v \models P", "⠘⠸⠒"),
    (r"p \nRightarrow q", "⠨⠒⠒⠕"),   # 제61항
    (r"p \rightleftarrows q", "⠪⠶⠕"),
    (r"\nexists x", "⠨⠨⠢"),
])
def test_누락_기호(tex, want):
    assert want in _b(tex)


@pytest.mark.parametrize("tex,want", [
    (r"a \not R b", "⠨⠠⠗"),
    (r"M \not\ni a", "⠨⠲"),
    (r"A \not\subset M", "⠨⠖⠂"),
    (r"M \not\supset A", "⠨⠐⠲"),
])
def test_not_접두(tex, want):
    assert want in _b(tex)


def test_긍정형은_그대로():
    assert "⠨" not in _b(r"A \subset B")
