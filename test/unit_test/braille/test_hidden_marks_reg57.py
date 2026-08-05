"""제57항 숨김표 — 점형과 반복 표기 (2026-08-06, S5).

## 왜 이 파일이 있나

규정 예문 709건 전수 대조에서 두 결함이 나왔다. 종전 단위 테스트는 4개 절의
`decode_ok` 단어 쌍만 돌려서 이 절을 아무도 안 봤다.

  1. **☆·◇ 점형이 틀렸다** — 규정 [붙임]이 제1~제3 점역자 정의 숨김표로 못 박는데
     우리 표가 다른 글리프를 갖고 있었다.
  2. **`×××`가 곱셈으로 나갔다** — `×`는 두 뜻(곱셈 ⠡ / 숨김표 ⠸⠭⠇)인데 평탄화 표에서
     수학연산이 이기고, 그보다 먼저 `inline_math`가 수식 구간으로 삼켰다.

기대값은 **규정 원문 BRF에서 직접 만든다**(`braille-source/text/규정_텍스트.txt` 제57항).
데이터셋 `regulation_pairs`는 기대값이 445건 틀려 있어 근거로 쓰지 않는다(원장 §9 이력).

## 단독 `×`는 일부러 손대지 않는다

문맥 없이 곱셈·교배 기호·표의 '아니오' 표시·숨김표를 못 가른다. 코퍼스 70건 표본에서
곱셈·교배·표 표시가 대부분이라 건드리면 손해다. 원장 §8 중의성 항목.
"""
from __future__ import annotations

import pytest

from app.ai.braille.translator import translate_tagged_text
from app.utils.braille_ascii import ascii_to_unicode


def _reg(brf: str) -> str:
    """규정 원문 BRF → 유니코드 점자. 규정 관례상 백틱은 칸 띄우기."""
    return ascii_to_unicode(brf, backtick="space")


class TestRegulationExamples:
    """규정 제57항 본문·[붙임] 예시 전수. BRF는 원문 그대로 옮긴 것이다."""

    @pytest.mark.parametrize("korean,reg_brf", [
        ("김○○ 씨", "@o5_00l`,,o"),
        ("이 ×××야!", "o`_xxxl>6"),
        ("△△도서관", "_++liu,s@v3"),
        ("☆☆고등학교", "_99l@ui[7ja@+"),
        ("2016년 ◇월 ◆일", "#bjaf`c*`_5lp1`_olo1"),
    ])
    def test_예시_그대로_나온다(self, korean: str, reg_brf: str) -> None:
        assert translate_tagged_text(korean) == _reg(reg_brf)


class TestGlyphs:
    """점형 자체 — [붙임]이 제1~제3 정의 숨김표로 못 박는다."""

    @pytest.mark.parametrize("mark,reg_brf,note", [
        ("○", "_0l", "제57항 본문"),
        ("×", "_xl", "제57항 본문"),
        ("△", "_+l", "제57항 본문"),
        ("☆", "_9l", "[붙임] 제1점역자 정의"),
        ("◇", "_5l", "[붙임] 제2점역자 정의"),
        ("◆", "_ol", "[붙임] 제3점역자 정의"),
    ])
    def test_숨김표_점형(self, mark: str, reg_brf: str, note: str) -> None:
        """표 원본의 `문장부호` 항을 본다.

        평탄화 표(`SYMBOL_TABLE`)는 못 쓴다 — `×`가 두 항(문장부호 숨김표 ⠸⠭⠇ /
        수학연산 곱셈 ⠡)에 있고 평탄화에서 수학연산이 이긴다. 그건 **의도된 중복**이라
        여기서 다투면 안 된다. 반복 `××`가 숨김표로 나가는지는 TestRepetition이 본다.
        """
        import json
        from pathlib import Path

        tbl = json.loads(
            (Path(__file__).parents[3] / "app/ai/braille/symbol_table.json")
            .read_text(encoding="utf-8"))["문장부호"]
        assert tbl[mark] == _reg(reg_brf), note


class TestRepetition:
    """제57항: 여러 개 붙어 나오면 래퍼 하나 안에 점형을 개수만큼."""

    @pytest.mark.parametrize("mark,cell", [
        ("○", "⠴"), ("×", "⠭"), ("△", "⠬"), ("☆", "⠔"), ("◇", "⠢"), ("◆", "⠕"),
    ])
    @pytest.mark.parametrize("n", [2, 3, 4])
    def test_n개_반복은_래퍼_하나(self, mark: str, cell: str, n: int) -> None:
        got = translate_tagged_text(mark * n + "다")
        assert got.startswith("⠸" + cell * n + "⠇"), got

    def test_묵자_n글자에_n더하기2셀(self) -> None:
        """규정은 n+2셀. 글자마다 래퍼를 씌우면 3n셀이 된다."""
        got = translate_tagged_text("○○○")
        assert len(got) == 5, got

    def test_서로_다른_숨김표는_안_합친다(self) -> None:
        """제57항의 '해당 숨김표'가 하나로 정해지지 않는다."""
        got = translate_tagged_text("○△")
        assert got == "⠸⠴⠇⠸⠬⠇", got


class TestMultiplicationNotBroken:
    """`××`를 숨김표로 본 뒤에도 진짜 곱셈은 그대로여야 한다."""

    @pytest.mark.parametrize("korean", [
        "2×3=6", "3×4", "5×5=25", "반지름×반지름", "가로×세로", "가로 × 세로",
    ])
    def test_단독_곱셈은_그대로(self, korean: str) -> None:
        got = translate_tagged_text(korean)
        assert "⠡" in got, got
        assert "⠸⠭" not in got, got

    def test_단독_x는_손대지_않는다(self) -> None:
        """문맥 없이 곱셈·교배·표 표시·숨김표를 못 가른다(원장 §8).

        코퍼스 실측에서 단독 ×는 곱셈·교배 기호·표의 '아니오'가 대부분이다.
        여기서 동작이 바뀌면 그 판단을 뒤집은 것이므로 원장부터 고쳐야 한다.
        """
        assert "⠡" in translate_tagged_text("가×나")
