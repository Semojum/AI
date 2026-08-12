"""만화 캡션의 '(상황)' 말머리를 걷는다 (2026-08-12 대표 지시).

지침 예5-4·5-5는 '만화:' 뒤에 말머리 없이 **바로 문장**이 온다. 모델이 '(상황)'을
붙이면 점역사가 매번 지워야 하고, 점자로는 그 네 글자가 그대로 셀을 먹는다.
프롬프트로 막되 후처리로도 걷는다 — 프롬프트 지시는 모델이 어길 수 있다.
"""
from __future__ import annotations

import pytest

from app.ai.captioning.captioner import _strip_situation_head as strip


class TestStrip:
    @pytest.mark.parametrize("src,want", [
        ("만화: (상황) 남학생과 여학생이 등산 중이다", "만화: 남학생과 여학생이 등산 중이다"),
        ("상황: 두 사람이 대화한다", "두 사람이 대화한다"),
        ("(상황)약수터를 본다", "약수터를 본다"),
        ("만화: [상황] 토론회 장면", "만화: 토론회 장면"),
    ])
    def test_말머리를_뗀다(self, src: str, want: str) -> None:
        assert strip(src) == want

    @pytest.mark.parametrize("src", [
        "철수: 상황이 어렵다",          # 대사 속 낱말 — 조사가 붙었다
        "만화: 상황실에서 회의한다",     # 낱말의 일부
        "만화: 정상 문장 상황을 설명한다",
    ])
    def test_본문_낱말은_안_건드린다(self, src: str) -> None:
        """'상황이'·'상황실'까지 지우면 대사가 깨진다 — 실제로 한 번 깼다."""
        assert strip(src) == src

    def test_여러_줄(self) -> None:
        t = "만화: (상황) 교실\n철수: 안녕\n영희: 그래"
        assert strip(t) == "만화: 교실\n철수: 안녕\n영희: 그래"

    def test_빈_입력(self) -> None:
        assert strip("") == ""
