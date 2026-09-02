r"""n제곱근 중첩·자릿점 표기·연산 기호 둘 — 수학 점자 제22항 붙임1 · 제41항 · 제15항.

**n제곱근** — 정규식(`[^{}]*`)으로는 중첩 중괄호를 못 읽어 `\sqrt[3]{x^{3}}` 과
`\sqrt[m]{\sqrt[n]{a}}` 가 안 잡혔다. 대괄호가 점형 ⠷⠄…⠠⠾ 로 그대로 나갔다.

**`{,}`** — LaTeX 에서 자릿점을 쓰는 표준 표기인데 못 읽어 곱셈점 ⠐ 으로 나갔다
(규정 제41항은 ⠂).

**`\bullet`** — 곱셈점 `·` 이 아니라 **검정동그라미 ∙**(제15항 7호 `_4`)다.
"""
import pytest

from app.ai.braille.kor_math_rules import convert_latex
from app.utils.braille_ascii import unicode_to_ascii


def _b(t: str) -> str:
    return unicode_to_ascii(convert_latex(t)).replace("`", "").strip()


@pytest.mark.parametrize("tex,want", [
    (r"\sqrt[3]{x^{3}}", "#c"),
    (r"\sqrt[n]{a}", "n"),
    (r"\sqrt[m]{\sqrt[n]{a}}", "m"),
])
def test_n제곱근이_대괄호를_안_남긴다(tex, want):
    got = _b(tex)
    assert want in got and "[" not in got and "]" not in got


@pytest.mark.parametrize("tex,want", [
    ("5{,}700{,}000", "#e1gjj1jjj"),
    ("1{,}000", "#a1jjj"),
    ("5,700,000", "#e1gjj1jjj"),
])
def test_자릿점(tex, want):
    assert _b(tex) == want


def test_bullet_은_검정동그라미():
    assert "_4" in _b(r"a \bullet b")


def test_cdot_은_곱셈점_그대로():
    assert '"' in _b(r"a \cdot b")


def test_겹동그라미():
    assert "_00" in _b(r"x \circledcirc y")
