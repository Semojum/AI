"""정오 표시 ○·× (원장 M-04 · C-14) — 검출과 배치.

해설은 선지마다 맞음/틀림을 ○·×로 찍는데 **텍스트레이어에도 MinerU 추출에도 안 나온다** —
글리프가 채움 경로로 그려져 있어서다(밑줄·글상자와 같은 사정).
정답 도서는 로마자 소괄호로 적는다: (O)=⠦⠄⠴⠠⠕⠠⠴ · (X)=⠦⠄⠴⠠⠭⠠⠴.
dev-2027 900쪽에 1,058회(≈6,300셀)인데 우리는 0회였다.

실측(5쪽): O 54/54 · X 34/34 · 쪽 완전일치 5/5.
"""
from __future__ import annotations

import pytest

from app.ai.preprocessor.pdf_analyzer import tag_answer_marks


def _el(content: str, bbox: tuple[float, ...]) -> dict:
    return {"type": "text", "content": content, "bbox": list(bbox)}


class TestPlacement:
    def test_선지_요소_앞에_붙는다(self) -> None:
        """표시는 **선지 번호 위에 겹쳐** 찍힌다(⌧ = ① 위의 ×). 그 요소 앞에 붙어야
        gold 배치 `…해당한다.(X)①아메바가…`와 같아진다."""
        els = [_el("① 아메바가 분열한다", (66, 328, 459, 363)),
               _el("② 달걀이 부화한다", (66, 364, 461, 398))]
        assert tag_answer_marks(els, [("X", [72, 333, 85, 344]),
                                      ("O", [72, 369, 85, 380])]) == 2
        assert els[0]["content"].startswith("(X)①")
        assert els[1]["content"].startswith("(O)②")

    def test_다른_줄에는_안_붙는다(self) -> None:
        els = [_el("① 본문", (60, 500, 300, 518))]
        assert tag_answer_marks(els, [("O", [62, 100, 70, 108])]) == 0
        assert "(" not in els[0]["content"]

    def test_선지가_아니면_안_붙는다(self) -> None:
        """줄글 본문에 표시가 겹쳐 보여도 붙이지 않는다 — 오검출이 6셀 삽입이 된다."""
        els = [_el("앞 문장이다.", (66, 328, 459, 363))]
        assert tag_answer_marks(els, [("X", [72, 333, 85, 344])]) == 0

    def test_짝이_없으면_버린다(self) -> None:
        assert tag_answer_marks([], [("O", [1, 1, 2, 2])]) == 0
        assert tag_answer_marks([_el("x", (0, 0, 1, 1))], []) == 0


class TestPairRule:
    """○이 하나도 없는 쪽의 ×는 **곱셈 기호**다 — 정오 표기는 쌍으로 온다.

    이 규칙 없이는 수학1에서 곱셈 ×를 정오 표시로 오검출한다(실측 2쪽).
    """

    def test_규칙이_문서화돼_있다(self) -> None:
        from app.ai.preprocessor import pdf_analyzer as m
        doc = m.mark_glyphs.__doc__ or ""
        assert "곱셈" in doc and "쌍으로" in doc
