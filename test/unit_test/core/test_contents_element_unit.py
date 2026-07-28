"""`contents` 직렬화 계약 — 요소당 1항목, 줄은 `\\n` 구분 (2026-07-28 BE 합의).

배경: 종전에는 32칸 조판 줄 **하나가 `contents` 항목 하나**였다. BE가 FE로 넘길 때는
묵자 문단·시각자료 하나가 요소 하나여야 하는데 그 단위가 깨졌다(BE 보고).
조판 규칙(32칸)은 규정이라 버릴 수 없으므로 줄 경계는 `\\n`으로 표시한다.

이 파일이 지키는 것:
  1. `_join_lines`가 요소당 1항목을 만든다(빈 요소는 빈 배열 유지).
  2. 줄 내용·순서가 보존된다(조판 결과를 잃지 않는다).
  3. `/finalize`가 **두 형식을 모두** 받는다 — BE가 응답 `contents`를 그대로 되돌려줘도 동작.
"""
from __future__ import annotations

from app.core.pipeline import _join_lines
from app.core.routes import FinalizeBlock

_L1 = "⠓⠣⠉⠁"
_L2 = "⠑⠕⠃⠎"
_L3 = "⠠⠍⠓⠪⠁"


class TestJoinLines:
    def test_요소당_1항목(self) -> None:
        assert _join_lines([_L1, _L2, _L3]) == [f"{_L1}\n{_L2}\n{_L3}"]

    def test_한_줄짜리도_1항목(self) -> None:
        assert _join_lines([_L1]) == [_L1]

    def test_빈_요소는_빈_배열(self) -> None:
        """빈 문자열 1개짜리 배열을 만들지 않는다 — BE가 '내용 있음'으로 오인한다."""
        assert _join_lines([]) == []

    def test_줄_내용과_순서가_보존된다(self) -> None:
        lines = [_L1, _L2, _L3]
        assert _join_lines(lines)[0].split("\n") == lines

    def test_빈_줄도_보존된다(self) -> None:
        """제목 앞뒤 빈 줄은 조판 규칙이라 사라지면 안 된다."""
        lines = [_L1, "", _L2]
        assert _join_lines(lines)[0].split("\n") == lines


class TestFinalizeAcceptsBothForms:
    def test_줄_배열_형식(self) -> None:
        b = FinalizeBlock(lines=[_L1, _L2])
        assert b.normalized_lines() == [_L1, _L2]

    def test_줄바꿈_결합_형식(self) -> None:
        b = FinalizeBlock(lines=[f"{_L1}\n{_L2}"])
        assert b.normalized_lines() == [_L1, _L2]

    def test_두_형식이_같은_결과(self) -> None:
        a = FinalizeBlock(lines=[_L1, _L2, _L3]).normalized_lines()
        c = FinalizeBlock(lines=[f"{_L1}\n{_L2}\n{_L3}"]).normalized_lines()
        assert a == c

    def test_혼합_형식도_펴진다(self) -> None:
        b = FinalizeBlock(lines=[f"{_L1}\n{_L2}", _L3])
        assert b.normalized_lines() == [_L1, _L2, _L3]

    def test_빈_블록(self) -> None:
        assert FinalizeBlock().normalized_lines() == []


def test_왕복_직렬화_후_조판_입력이_동일하다() -> None:
    """AI 응답(contents) → BE 저장 → FE 편집 → /finalize 왕복에서 줄이 안 깨진다."""
    original = [_L1, _L2, _L3]
    serialized = _join_lines(original)                      # AI → BE
    restored = FinalizeBlock(lines=serialized).normalized_lines()   # BE → AI
    assert restored == original
