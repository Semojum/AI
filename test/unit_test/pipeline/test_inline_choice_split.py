"""한 줄로 뭉친 선택지를 줄마다 하나씩으로 가른다 (2026-08-10).

MinerU는 선택지를 쪽마다 다르게 낸다 — 어떤 쪽은 ①②③이 각각 제 줄, 어떤 쪽은 한 줄에
몰려서 나온다. 뒤쪽이면 `layout_braille._mark_item_lines`가 `len(src) < 2`로 조기 반환해
**항목 들여쓰기가 통째로 안 붙는다**.

실측(valall 6권 951쪽): 선택지 블록 243개 중 **48개(19.8%)**가 그 모양이었다.
정답 도서는 항목 구분 2칸 97.8%·선택지 줄 들여쓰기 2칸 99.5%로 결정적으로 일관적이다.

⚠ 본문 안의 단독 `①`(주석 참조 등)까지 가르면 멀쩡한 문장이 토막 난다 — 둘 이상일 때만 가른다.
"""
from __future__ import annotations

import pytest

from app.core.pipeline import _split_inline_choices


class TestSplit:
    @pytest.mark.parametrize("src,want", [
        ("① 가 ② 나 ③ 다", "① 가\n② 나\n③ 다"),
        ("다음 중 옳은 것은?\n① 가 ② 나", "다음 중 옳은 것은?\n① 가\n② 나"),
        ("① 가 ② 나\n③ 다 ④ 라", "① 가\n② 나\n③ 다\n④ 라"),
    ])
    def test_둘_이상이면_가른다(self, src: str, want: str) -> None:
        assert _split_inline_choices(src) == want

    @pytest.mark.parametrize("src", [
        "본문에 ① 참조가 하나만 있다",          # 단독 — 문장을 토막 내면 안 된다
        "① 첫째\n② 둘째",                      # 이미 갈려 있다
        "",
        "선택지가 없는 평범한 문장이다.",
    ])
    def test_건드리지_않는다(self, src: str) -> None:
        assert _split_inline_choices(src) == src

    def test_내용은_안_잃는다(self) -> None:
        """가르기는 배치만 바꾼다 — 글자가 사라지면 안 된다."""
        src = "① 가나다 ② 라마바 ③ 사아자"
        got = _split_inline_choices(src)
        assert got.replace("\n", " ") == src


class TestIndentApplied:
    """가른 뒤 조판이 실제로 항목 들여쓰기를 준다 (이 수정의 목적)."""

    def test_가른_뒤_항목마다_들여쓴다(self) -> None:
        from uuid import uuid4

        from app.ai.braille.layout_braille import LayoutBraille
        from app.ai.braille.translator import translate_tagged_text
        from app.schemas.content import BrailleOutput

        src = _split_inline_choices("① 가 ② 나 ③ 다")
        lines = [translate_tagged_text(ln) for ln in src.split("\n")]
        bo = BrailleOutput(element_id=uuid4(), braille_lines=lines)
        bo.corrected_text = src
        LayoutBraille()._mark_item_lines(bo, "text", 2)
        assert bo.line_indents == [2, 2, 2], "항목마다 2칸(= '3칸에서 시작')이어야 한다"
