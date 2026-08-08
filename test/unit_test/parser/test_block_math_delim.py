r"""QA 11번 — 한 줄짜리 수식에 `$$\n…\n$$` 줄바꿈이 끼던 문제.

MinerU는 블록 수식을 마크다운 관례대로 세 줄로 내보낸다. 경계 파일 계약은
`formula(content=LaTeX)`(SPEC-INTERFACE §2)이므로 구분자는 벗겨서 넘긴다.
대표님 QA 실물(job_260807114847 p001):
    "$$\n\\sqrt {9 n ^ {2} - 5} + 2 n <   a _ {n} <   5 n + 1\n$$"
"""
from __future__ import annotations

import pytest

from app.ai.llm.formula_opt import _normalize
from app.ai.parser.mineru_runner import _strip_block_math_delim

_QA_REAL = "$$\n\\sqrt {9 n ^ {2} - 5} + 2 n <   a _ {n} <   5 n + 1\n$$"


class TestStrip:
    @pytest.mark.parametrize("src,expect", [
        (_QA_REAL, "\\sqrt {9 n ^ {2} - 5} + 2 n <   a _ {n} <   5 n + 1"),
        ("$$\nf (x) = x ^ {3}\n$$", "f (x) = x ^ {3}"),
        ("$$2^{\\frac{13}{6}}$$", "2^{\\frac{13}{6}}"),
        ("$x+1$", "x+1"),
    ])
    def test_구분자를_벗기고_한_줄로(self, src: str, expect: str) -> None:
        got = _strip_block_math_delim(src)
        assert got == expect
        assert "\n" not in got

    @pytest.mark.parametrize("src", [
        "x^{2}+1",                      # 이미 깨끗함
        "",
        "a $ b",                        # 짝이 안 맞는 달러 — 손대지 않는다
        "\\begin{cases}\nx>0\\\\\nx<1\n\\end{cases}",   # 여러 줄 수식은 보존
    ])
    def test_구분자가_없으면_그대로(self, src: str) -> None:
        assert _strip_block_math_delim(src) == src

    def test_멱등(self) -> None:
        once = _strip_block_math_delim(_QA_REAL)
        assert _strip_block_math_delim(once) == once


class TestFormulaOptNormalize:
    """opt 쪽 방어 — ZERO 티어·GPT-4o 폴백은 _extract를 안 타므로 여기서 막는다."""

    def test_normalize가_구분자를_지운다(self) -> None:
        got = _normalize(_QA_REAL)
        assert not got.startswith("$")
        assert "$" not in got
        assert "\n" not in got

    def test_폴백_응답_형태도_지운다(self) -> None:
        """대표님 QA 10 job 전부 routing_tier=FALLBACK이었다(GPT-4o 응답 그대로)."""
        got = _normalize("$$\nb_{k+i} = \\frac{1}{a_{i}} - 1\n$$")
        assert got == "b_{k+i} = \\frac{1}{a_{i}} - 1"
