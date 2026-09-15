"""가드4 장식 판정이 "캡셔닝 빈 응답" 으로 둔갑하던 문제 (#872).

2026-09-12 dev 900쪽 재추출에서 `CAPTION_FAILED` 가 13→11→10 으로만 줄어 "매번 빈 응답이
오는 제품 결함" 으로 올라왔다. 그 10쪽을 제품 함수(`_do_caption`)로 전건 재현해 보니
**모델은 한 번도 빈 응답을 주지 않았다** — `stop_reason` 전부 `end_turn`, 출력 11~101토큰.
전부 문항 번호 배지였고, 6건은 가드4 정규식에 걸리고 4건은 표현이 달라 비켜 갔다
(`숫자 08이 원 안에 적혀 있다` · `09라는 숫자가 원 안에 있다`). 13→11→10 흔들림의 정체가
그 표현 차이다.

여기서 지키는 것 셋:
  ① 배지 캡션은 어순이 달라도 잡힌다(구조로 본다)
  ② 왜 비었는지가 밖으로 나온다(`out_info["rejected_by"]`)
  ③ 장식으로 판정된 요소는 `그림 생략` 을 내지 않고 **버린다**(제작 지침 §6.1.1(4))
"""
from __future__ import annotations

from unittest.mock import patch

import pytest

from app.ai.builder import result_builder as RB
from app.ai.captioning import captioner as C


class TestBadgePredicate:
    @pytest.mark.parametrize("cap", [
        # ↓ 캡션 캐시 전수(3,242건)에서 새로 잡히는 8건
        "그림: 원 안에 숫자 \"03\"",
        "그림: 반원 안에 숫자 11",
        "그림: 초록색 원 안에 흰색 숫자 1",
        "그림: 보라색 사각형 안에 흰색 숫자 2",
        "그림: 검정 네모 안에 흰색 숫자 4",
        # ↓ 10쪽 재현에서 가드를 비켜 갔던 두 표현
        "그림: 숫자 08이 원 안에 적혀 있다.",
        "그림: 09라는 숫자가 원 안에 있다.",
        # ↓ 모델이 스스로 장식이라 부른 자리
        "그림: 숫자 09가 쓰인 원 모양 장식.",
    ])
    def test_배지는_어순이_달라도_잡는다(self, cap: str) -> None:
        assert C._is_badge_caption(cap) is True

    @pytest.mark.parametrize("cap", [
        # 쉼표 뒤로 내용이 이어지면 진짜 그림이다(유물 사진 실측)
        '사진: 숫자 2 모양 오브제, 하트 모양에 "정" 글자가 적힌 오브제',
        "그림: 주머니 속 카드 6장\n\n카드 숫자: 1, 2, 2, 3, 3, 3",
        # 도형 낱말이 합성어 안에 든 경우 — `원그래프` 를 배지로 보면 진짜 그림이 죽는다
        "그림: 원그래프에 숫자가 적혀 있다",
        # 도형도 숫자도 없는 보통 캡션
        "그림: 세포 안 염색체 네 개가 두 무리로 나뉘어 있다",
        # 유형 제시어가 없으면 캡션 사슬 밖이다
        "원 안에 숫자 3",
        # `장식` 이 들어도 여러 줄이면 진짜 그림이다(캐시 전수 3건 전부 이 꼴)
        "사진: 조몬 토우\n\n- 머리에 돌기 장식\n- 숫자 3개 표시",
    ])
    def test_진짜_그림은_안_잡는다(self, cap: str) -> None:
        assert C._is_badge_caption(cap) is False

    def test_길면_안_잡는다(self) -> None:
        assert C._is_badge_caption("그림: " + "원 안에 숫자 3 " * 5) is False


class TestReasonReachesCaller:
    """왜 비었는지가 밖으로 나와야 검출기가 둘을 가른다(이슈 §'capcheck 가 못 가른다')."""

    def test_장식이면_이유를_채운다(self) -> None:
        out: dict = {}
        assert C._finish("그림: 원 안에 숫자 03", "image", out) == ""
        assert out.get("rejected_by") == "decoration"

    def test_보통_캡션은_이유가_없다(self) -> None:
        out: dict = {}
        got = C._finish("그림: 세포 안 염색체 네 개가 두 무리로 나뉘어 있다", "image", out)
        assert got and out == {}

    def test_out_info를_안_줘도_동작은_같다(self) -> None:
        assert C._finish("그림: 원 안에 숫자 03", "image") == ""


class TestElementDropped:
    """장식은 `그림 생략` + R11 을 내지 않는다 — 점역사가 찾아 지워야 할 일감이 된다."""

    def _layout(self) -> list[dict]:
        return [{"element_id": "e1", "type": "image", "bbox": [100, 100, 300, 300],
                 "image_path": "/nonexistent.jpg", "content": ""}]

    def test_장식_판정이면_요소를_버린다(self) -> None:
        layout = self._layout()
        with patch.object(RB, "_do_caption",
                          return_value=("", "image", False, None, "", True)):
            res = RB.build(layout, "job", 1, "OCR")
        assert res["elements"] == []

    def test_진짜_실패면_요소를_살린다(self) -> None:
        layout = self._layout()
        with patch.object(RB, "_do_caption",
                          return_value=("", "image", False, None, "", False)):
            res = RB.build(layout, "job", 1, "OCR")
        assert len(res["elements"]) == 1
        assert "CAPTION_FAILED" in res["elements"][0]["flags"]

    def test_성공하면_그대로_싣는다(self) -> None:
        layout = self._layout()
        with patch.object(RB, "_do_caption",
                          return_value=("그림: 염색체 네 개", "image", True, None, "", False)):
            res = RB.build(layout, "job", 1, "OCR")
        assert len(res["elements"]) == 1
        assert res["elements"][0]["content"].startswith("그림:")
        assert res["elements"][0]["flags"] == []
