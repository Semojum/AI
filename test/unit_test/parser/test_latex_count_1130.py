"""#1130 — MinerU 가 LaTeX 로 읽은 수식이 첨자를 잃은 층 글로 덮이던 문제.

#1072 가드는 층 글에 첨자 글자가 하나라도 있으면 통과했다. 수학 Ⅰ(009)은 한컴 글꼴 되돌리기가 숫자 첨자(`a₁`)만
살리고 글자 첨자(`n+1`)는 평평하게 남겨, `₁` 하나로 가드를 넘었다. 제어 문자 띄움으로 층을 믿게 된 요소는
가드를 아예 안 거쳤다(생명과학 `$\\frac{3}{8}$` → 한컴 분수 쓰레기 `;8#;`).
"""
from __future__ import annotations

from app.ai.parser import mineru_runner as M

BOX = [0, 0, 1000, 1000]


def _patch(monkeypatch, plain: str, native: str) -> None:
    monkeypatch.setattr(M, "_native_text_pair", lambda *_a, **_k: (plain, native))
    monkeypatch.setattr(M, "_has_struct_font", lambda *_a, **_k: False)
    monkeypatch.setattr(M, "_MATH_FONT_GUARD", False)


def test_첨자를_하나만_담은_층은_잃은_것이다():
    assert M._latex_lost("$a_1 = a, a_{n+1} = a_n + d$", "a₁=a, an+1=an+d")
    assert M._latex_lost("$\\frac{a_{n+1}}{a_n} = 3$", "an+1  an =3")
    assert M._latex_lost("$\\frac { 3 } { 8 }$", ";8#;") and M._latex_lost("$\\frac 1 4$", ";4!;")


def test_첨자를_다_담은_층은_그대로_쓴다():
    assert not M._latex_lost("$\\log_{2}a+\\log_{4}b$", "log₂ a+log₄ b")
    assert not M._latex_lost("$t _ { 1 }$ 일 때 $t _ { 2 }$", "t₁일 때 t₂")
    assert not M._latex_lost("$\\mathrm { N a } ^ { + }$", "Na⁺")


def test_깨진_LaTeX_와_수식_밖_밑줄은_세지_않는다():
    """MinerU 가 깨진 글리프를 쓰레기 LaTeX 로 적은 자리 · `×` 를 `_` 로 읽은 자리는 구조가 아니다(생명과학)."""
    assert not M._latex_lost("$t _ { 1 } ^ { \\phantom { + } }$ $\\Xi ^ { | } { \\circ }$", "t₁")
    assert not M._latex_lost("(2_㉡의 길이) $t _ { 1 }$", "(2×㉡의 길이) t₁")
    assert not M._latex_lost("$\\frac { \\textcircled { \\dag } }$", "㉠")


def test_처음부터_믿는_층도_첨자를_잃으면_MinerU_에_둔다(monkeypatch):
    """제어 문자 띄움(#1072)으로 믿게 된 요소는 되살림 경로를 안 탄다 — 닮음 문턱만 보고 덮였다."""
    plain = native = "모든 자연수 n에 대하여 an+1-an=5이므로 수열 {an}은 등차수열이다."
    _patch(monkeypatch, plain, native)
    assert not M._layer_untrustworthy(plain)
    mineru = "모든 자연수 $n$ 에 대하여 $a_{n+1} - a_n = 5$ 이므로 수열 $\\{a_n\\}$ 은 등차수열이다."
    assert M._native_override(None, BOX, mineru) is None
    monkeypatch.setattr(M, "_LATEX_COUNT_GUARD", False)
    assert M._native_override(None, BOX, mineru) == native        # 스위치를 끄면 종전대로 덮는다


def test_되살림_경로도_첨자_수로_본다(monkeypatch):
    plain, native = "⑴ aÁ=a, an+1=an+d 을 만족시키는", "⑴ a₁=a, an+1=an+d 을 만족시키는"
    _patch(monkeypatch, plain, native)
    assert M._layer_untrustworthy(plain)
    mineru = "(1) $a_1 = a, a_{n+1} = a_n + d$ 을 만족시키는"
    assert M._native_override(None, BOX, mineru) is None
    monkeypatch.setattr(M, "_LATEX_COUNT_GUARD", False)
    assert M._native_override(None, BOX, mineru) == native        # 종전 가드는 ₁ 하나로 통과했다
