"""opt 프리필 후처리 _extract 회귀 — 여러 줄 수식 보존 + 프리필 스캐폴드 제거.

리뷰 #1/#3: _extract가 첫 줄만 취해 여러 줄 수식이 잘려 소실되던 회귀 방지.

※ 텍스트 몫(`text_opt._extract`)은 없어졌다 — 본문 OCR 교정 LLM 을 갈래째 지웠다(#788,
  대표 결정 「고급 점역의 정의」). 프리필도 후처리도 부를 자리가 없다. 수식 몫만 남는다.
"""
from __future__ import annotations

from app.ai.llm.formula_opt import _PREFILL as FP
from app.ai.llm.formula_opt import _extract as formula_extract


class TestFormulaExtract:
    def test_여러줄_LaTeX_보존(self):
        out = formula_extract(FP + "\\begin{cases}\nx=1\\\\\ny=2\n\\end{cases}")
        assert "cases" in out and "x=1" in out and "y=2" in out

    def test_프리필_코드펜스_제거(self):
        out = formula_extract(FP + "`x^2 + 1 = 0`")
        assert not out.startswith(FP)
        assert out == "x^2 + 1 = 0"
