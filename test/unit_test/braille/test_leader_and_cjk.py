"""점 이음선 제거 · 한자 전용 요소 생략 (2026-07-29).

둘 다 **홀드아웃 120쪽에서 처음 드러난** 결함이라, dev·val 회귀 테스트로는 못 잡는다.
그래서 여기에 못 박는다.

1. **점 이음선(유도선)** — 문제집 표·목차는 항목과 번호를 점선으로 잇는다
   ("…를 고려해야 한다.⋯⋯⋯⋯(100자) 1"). 묵자 조판 장식이지 글자가 아니다.
   그대로 점역하면 한 쪽 출력의 42%가 ⠠ 연속이 된다(언어 p038 실측 605/1,433셀).
   정답 도서는 ⠠ 연속 런이 최장 2셀뿐이다.
   ⚠ 임계는 정답 도서가 아니라 **규정 제53항**에서 나왔다 — 줄임표는
     가운뎃점형 `……`(2자)·`…`(1자), 마침표형 `...`(3자)가 전부다. 4자 이상은
     줄임표로 성립하지 않는다. 그래서 3자 이하는 **불가침**이다.

2. **한자 전용 요소** — 한자는 점역하지 않는 것이 도서 관행이다(정답 대조 확인).
   따라서 한자만 있는 요소는 **빈 출력이 정답**인데, 소실 가드가 이를 소실로 보고
   `[처리 불가: 점역 불가 문자 匙]`라는 **한글 리터럴을 점자 파일에 찍었다**
   (실측 dev 160자·val 779자·홀드아웃 65자).
"""
from __future__ import annotations

import re
import uuid

import pytest

from app.ai.braille import isolation
from app.ai.braille.translator import strip_leader_dots, translate_tagged_text
from app.schemas.content import BrailleOutput, LLMOutput


# ── 1. 점 이음선 ──────────────────────────────────────────────────────────────
class TestLeaderDots:
    """규정 줄임표는 보존하고 이음선만 걷어낸다."""

    @pytest.mark.parametrize("keep", ["…", "……", "⋯", "⋯⋯", "⋯⋯⋯", "‥"])
    def test_규정_줄임표_3자_이하는_보존한다(self, keep: str) -> None:
        """제53항이 다루는 줄임표 — 한 글자도 건드리면 안 된다."""
        assert keep in strip_leader_dots(f"말끝을 흐렸다{keep} 그리고")

    @pytest.mark.parametrize("n", [4, 7, 30, 100])
    def test_4자_이상은_이음선으로_보고_제거한다(self, n: int) -> None:
        out = strip_leader_dots("고려해야 한다." + "⋯" * n + " 1")
        assert not any(c in out for c in "⋯…‥"), f"{n}자 이음선이 남았다: {out!r}"
        assert "고려해야 한다." in out and "1" in out, "본문이 함께 지워지면 안 된다"

    def test_이음선_자리에_공백이_남아_어절이_붙지_않는다(self) -> None:
        assert strip_leader_dots("한다." + "⋯" * 20 + "1") == "한다. 1"

    def test_점자_셀_폭발이_사라진다(self) -> None:
        """수정 전 실측: 100자 이음선 → ⠠ 연속 300셀."""
        b = translate_tagged_text("고려해야 한다." + "⋯" * 100 + " 1")
        runs = re.findall(r"⠠{4,}", b)
        assert not runs, f"⠠ 연속 런이 남았다(최장 {max(len(r) for r in runs)}셀)"
        assert len(b) < 120, f"셀이 여전히 많다: {len(b)}"

    def test_규정_줄임표는_점자에서도_살아있다(self) -> None:
        """제53항 — 가운뎃점 줄임표는 ⠠⠠⠠."""
        assert "⠠⠠⠠" in translate_tagged_text("실은⋯ 저 사람")

    def test_마침표_이음선도_제거한다(self) -> None:
        assert "." not in strip_leader_dots("목차" + "." * 20 + " 3").replace(" ", "")


# ── 2. 한자 전용 요소 ────────────────────────────────────────────────────────
_EID = uuid.uuid4()


def _opt(text: str) -> LLMOutput:
    return LLMOutput(element_id=_EID, corrected_text=text, routing_tier="ZERO")


def _empty_out() -> BrailleOutput:
    return BrailleOutput(element_id=_EID, braille_lines=[""], rule_trail=[])


class TestCJKOnlyElement:
    """한자만 있는 요소는 빈 출력이 정답 — 플레이스홀더를 찍으면 안 된다."""

    @pytest.mark.parametrize("cjk", ["匙", "套题", "喜题", "卡号", "（喜题）", "一"])
    def test_한자_전용_요소는_플레이스홀더를_만들지_않는다(self, cjk: str) -> None:
        out = isolation.safe_translate([_opt(cjk)], lambda _o: _empty_out())
        joined = "".join(out[0].braille_lines)
        assert "처리 불가" not in joined, f"{cjk!r} → {joined!r}"

    def test_한글이_섞여_있으면_여전히_소실로_잡는다(self) -> None:
        """진짜 소실까지 눈감으면 안 된다 — 가드의 본래 목적은 유지."""
        out = isolation.safe_translate([_opt("과목(果木)")], lambda _o: _empty_out())
        assert "처리 불가" in "".join(out[0].braille_lines)

    def test_점자가_정상이면_손대지_않는다(self) -> None:
        ok = BrailleOutput(element_id=_EID, braille_lines=["⠈⠕⠈⠍"], rule_trail=[])
        out = isolation.safe_translate([_opt("과목")], lambda _o: ok)
        assert out[0].braille_lines == ["⠈⠕⠈⠍"]

    def test_예외가_나면_여전히_플레이스홀더로_격리한다(self) -> None:
        """불변규칙 3 — 한 요소 실패가 페이지를 죽이지 않는다."""
        def boom(_o):
            raise RuntimeError("boom")
        out = isolation.safe_translate([_opt("匙")], boom)
        assert "처리 불가" in "".join(out[0].braille_lines)


def test_점자_파일에_한글_리터럴이_남지_않는다() -> None:
    """계층 A의 'A7 미점역 텍스트 잔존'이 잡던 것 — 점자 파일은 점자여야 한다."""
    out = isolation.safe_translate([_opt("（喜题）")], lambda _o: _empty_out())
    joined = "".join(out[0].braille_lines)
    stray = [c for c in joined if not c.isspace() and not (0x2800 <= ord(c) <= 0x28FF)]
    assert not stray, f"점자가 아닌 문자가 남았다: {stray}"
