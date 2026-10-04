"""#1072 — 한컴 글꼴 복원분을 되돌리기 전 글로만 판정해 버리던 것을, 거부된 요소에 한해 되돌린 글로 다시 본다.

조사 V2 `temp/n83/조사_글꼴경로.md`: 생명과학 I 의 `Á`(=₁) · `ª`(=₂) · `l`(=μ) 같은 라틴-1 쓰레기가 '층을 믿지 말라' 신호를
세워, 복원이 가장 필요한 요소에서 복원분이 통째로 버려졌다(복원이 글을 바꾸는 본문계 1,365 중 적용 281).
"""
from __future__ import annotations

from app.ai.parser import hancom_glyphs as H
from app.ai.parser import mineru_runner as M


def _patch(monkeypatch, plain: str, native: str, struct: bool = False) -> None:
    monkeypatch.setattr(M, "_native_text_pair", lambda *_a, **_k: (plain, native))
    monkeypatch.setattr(M, "_has_struct_font", lambda *_a, **_k: struct)
    monkeypatch.setattr(M, "_MATH_FONT_GUARD", False)


def test_라틴1_쓰레기로_거부된_요소를_되돌린_글로_살린다(monkeypatch):
    plain, native = "ㄴ. tÁ일 때 길이는 0 lm보다 크다.", "ㄴ. t₁일 때 길이는 0 μm보다 크다."
    _patch(monkeypatch, plain, native)
    assert M._layer_untrustworthy(plain)                         # 종전엔 여기서 끝났다
    assert M._native_override(None, [0, 0, 1000, 1000], plain) == native


def test_되돌리기가_적어_넣은_글자는_판정에서_뺀다(monkeypatch):
    """`²` 는 거부 신호 글자다 — 제대로 되돌린 결과 때문에 다시 거부되면 안 된다."""
    plain, native = "혈중 CaÛ±", "혈중 Ca²⁺"
    _patch(monkeypatch, plain, native)
    assert "²" in H.EMITTED and M._layer_untrustworthy(native)
    assert M._native_override(None, [0, 0, 1000, 1000], plain) == native


def test_구조_글꼴이_든_요소는_MinerU_에_둔다(monkeypatch):
    _patch(monkeypatch, "x=;2!;Á", "x=;2!;₁", struct=True)
    assert M._native_override(None, [0, 0, 1000, 1000], "$x=\\frac{1}{2}$") is None


def test_MinerU_의_LaTeX_첨자를_층이_잃으면_MinerU_에_둔다(monkeypatch):
    plain, native = "2  30 에서 33¾", "2  30 에서 33 ℃"          # 되돌리기는 ℃ 만 고쳤고 위첨자는 평범한 숫자다
    _patch(monkeypatch, plain, native)
    assert M._layer_untrustworthy(plain)
    assert M._latex_lost("$2^{30}$", native) and not M._latex_lost("$t_{1}$", "t₁")
    assert M._native_override(None, [0, 0, 1000, 1000], "$2^{30}$ 에서 33¾") is None


def test_되돌리기가_바꾼_것이_없으면_종전대로_거부한다(monkeypatch):
    _patch(monkeypatch, "가격 ±£", "가격 ±£")
    assert M._native_override(None, [0, 0, 1000, 1000], "가격") is None


def test_스위치를_끄면_종전대로(monkeypatch):
    plain, native = "ㄴ. tÁ일 때", "ㄴ. t₁일 때"
    _patch(monkeypatch, plain, native)
    monkeypatch.setattr(M, "_GATE_AFTER_RESTORE", False)
    assert M._native_override(None, [0, 0, 1000, 1000], plain) is None


def test_본문_글꼴의_제어_문자는_띄움이다():
    assert "•\x07적록‌".translate(M._CTRL_TO_SPACE) == "• 적록 "
    assert "가\t나\n다".translate(M._CTRL_TO_SPACE) == "가\t나\n다"


def test_구조_글꼴은_boN_Root_Susic_만_italic_본문은_아니다():
    assert M._STRUCT_FONT_RE.match("ABCDEF+EHboNB-Italic") and M._STRUCT_FONT_RE.match("EHRoot-Plain")
    assert not M._STRUCT_FONT_RE.match("EHsang-Italic")
