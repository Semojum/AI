"""점역자 주 문구 — 우리가 임의로 정한 것을 독자에게 밝히는 말 (2026-08-12 대표 지시).

정본 308건에서 점역자 주 덩이 56개를 세니 **시각자료 대체텍스트는 24개뿐**이고 나머지
32개가 "가독성을 위해 임의로 번호를 기입하였음" 같은 **표기 방식 고지**였다.
점자 독자는 원본을 볼 수 없다. 우리가 표를 뒤집었는지, 위계를 들여쓰기로 폈는지
말해 주지 않으면 그것이 원본에 있던 것인 줄 안다.
"""
from __future__ import annotations

import pytest

from app.ai.braille import tn_notices as tn


class TestParticle:
    """이 문구는 **점자로 그대로 찍힌다** — 조사가 틀리면 그대로 나간다."""

    @pytest.mark.parametrize("word,want", [
        ("항목", "을"), ("내용", "을"), ("것", "을"),      # 받침 있음
        ("기구", "를"), ("자료", "를"), ("표", "를"),      # 받침 없음
    ])
    def test_받침으로_을를을_가른다(self, word: str, want: str) -> None:
        assert tn._eul(word) == want

    def test_한글이_아니면_를(self) -> None:
        assert tn._eul("A") == "를"
        assert tn._eul("") == "를"


class TestIndentHierarchy:
    def test_칸_수를_밝힌다(self) -> None:
        """몇 칸이 한 단계인지 없으면 독자는 빈칸을 세도 단계를 못 센다."""
        assert tn.indent_hierarchy(2) == "하위에 속한 항목을 2칸씩 들여 쓰기함"
        assert "3칸씩" in tn.indent_hierarchy(3)

    def test_조직도는_정본_예6_22와_같은_말(self) -> None:
        assert tn.indent_hierarchy(2, "기구") == "하위에 속한 기구를 2칸씩 들여 쓰기함"


class TestOtherNotices:
    def test_표_분할(self) -> None:
        assert tn.table_split(5) == "가독성을 고려하여 5개의 표로 분할 점역함"

    def test_생략_고지(self) -> None:
        assert tn.omitted("그림") == "그림 생략"
        assert tn.omitted("수직선상의 -5와 5", "공간이 부족하여") == \
            "공간이 부족하여 수직선상의 -5와 5을 생략함"

    def test_읽는_순서(self) -> None:
        assert tn.reading_order(["멜로디", "한글 가사"]) == "멜로디, 한글 가사 순으로 점역하였음"

    def test_장면_표지(self) -> None:
        assert tn.scene(1) == "장면 1"

    def test_전치는_지침_두_권이_다르다(self) -> None:
        """자료지침 예3-2는 짧고 도서지침 예3-13은 이유를 앞에 둔다 — 둘 다 정본이다.

        우리 table_braille은 예3-2와 셀 단위로 일치하는 쪽을 쓴다. 한 예시만 보고
        "이유가 빠졌다"며 고쳤다가 대조가 깨진 적이 있다(같은 날).
        """
        from app.ai.braille.table_braille import _TN_TRANSPOSE

        assert _TN_TRANSPOSE == tn.TRANSPOSE_JARYO
        assert tn.TRANSPOSE != tn.TRANSPOSE_JARYO
