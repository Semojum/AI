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


class TestAnswerList:
    """정답 목록은 선택지가 아니다 — 가르지 않는다(#1353).

    해설 권 정답 띠 `01 ①  02 ③ …` 를 가르면 `01` / `① 02` / `③ 03` 으로 쌍마다 줄이 끊겼다
    (2027 dev · val 해설 권 94쪽 192곳). gold 는 쌍을 한 줄에 잇는다(`01 ⑤  02 ③  03 ②  04 ④`).
    """

    @pytest.mark.parametrize("src", [
        "01 ①  02 ③  03 ②  04 ④",                                   # 동아시아사 해설 p5 꼴
        "07 ③ 08 ⑤ <!상자끝><!/상자끝>",                               # 상자가 두 요소로 갈린 뒤쪽
        "<!상자>수능 기본 문제<!/상자> 01 ①  02 ③  03 ⑤  04 ①",          # 상자 제목이 앞에 붙은 줄
        "1 ⑤  2 ⑤  3 ②  4 ⑤  5 100  6 5  7 ⑤",                      # 수학 띠 — 숫자 답이 섞인다
    ])
    def test_정답_목록은_건드리지_않는다(self, src: str) -> None:
        assert _split_inline_choices(src) == src

    def test_수학_선택지는_그대로_가른다(self) -> None:
        """선택지 내용이 숫자라도 첫 원문자가 쌍의 답이 아니므로 선택지다."""
        assert _split_inline_choices("① 1  ② 2  ③ 3") == "① 1\n② 2\n③ 3"
