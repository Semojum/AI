"""opt 프리필 후처리 _extract 회귀 — 여러 줄 본문 보존 + 프리필 스캐폴드 제거.

리뷰 #1/#3: _extract가 첫 줄만 취해 여러 줄 교정문/수식이 잘려 소실되던 회귀 방지.
"""
from __future__ import annotations

from app.ai.llm.formula_opt import _PREFILL as FP
from app.ai.llm.formula_opt import _extract as formula_extract
from app.ai.llm.text_opt import _PREFILL as TP
from app.ai.llm.text_opt import _extract as text_extract


class TestTextExtract:
    def test_여러줄_보존(self):
        out = text_extract(TP + "첫째 문장 교정.\n둘째 문장 교정.")
        assert "첫째 문장 교정." in out and "둘째 문장 교정." in out

    def test_프리필_제거(self):
        out = text_extract(TP + "물의 어는점은 0℃이다.")
        assert not out.startswith(TP)
        assert out == "물의 어는점은 0℃이다."

    def test_빈_응답_안전(self):
        assert text_extract(TP) == ""

    def test_프리필_없는_폴백_응답도_처리(self):
        # FALLBACK(GPT-4o) 응답은 프리필이 없다 — 그대로 정리만.
        assert text_extract("교정된 한 줄.") == "교정된 한 줄."


class TestFormulaExtract:
    def test_여러줄_LaTeX_보존(self):
        out = formula_extract(FP + "\\begin{cases}\nx=1\\\\\ny=2\n\\end{cases}")
        assert "cases" in out and "x=1" in out and "y=2" in out

    def test_프리필_코드펜스_제거(self):
        out = formula_extract(FP + "`x^2 + 1 = 0`")
        assert not out.startswith(FP)
        assert out == "x^2 + 1 = 0"
