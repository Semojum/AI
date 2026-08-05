"""mode b 응답 계약 — 줄 하나 = 요소 하나, 원문·점역이 같은 `id`로 짝지어진다.

## 왜 이 파일이 있나 (2026-08-06)

BE는 txt·hwp를 **줄마다 `\\n`으로 이어 붙인 한 문자열**로 보내고, 응답을 줄 단위로 잘라
FE에 흘려보낸다. 그런데 우리는 두 가지를 안 지키고 있었다.

  1. `source_text` 전체를 요소 **하나**로 묶어 냈다 → BE가 원문과 점역을 짝지을 수 없다.
  2. `text_list`가 `mode in ("a","c")`로 막혀 있어 mode b에서는 **아예 비어** 있었다.

둘 다 코드로 확인된 결함이다. 여기서 계약을 못 박아 다시 어긋나지 않게 한다.

## 계약

  · 원문 줄 하나 → 요소 하나. 빈 줄은 요소를 만들지 않는다(지침상 문단 구분은 빈 줄이
    아니라 들여쓰기 — BBPG 2장2절2).
  · `order` = **원본 줄 번호**. 빈 줄에서 번호가 건너뛰므로 BE가 빈 줄 위치를 안다.
  · `text_list[i].id == braille_text_list[i].id` — 이게 짝짓기의 열쇠다.
  · `text_list[i].contents == [원문 그 줄]`.
  · mode a·c의 `order`는 **바뀌지 않는다**(나열 순서 1..N).
"""
from __future__ import annotations

import asyncio

import pytest

from app.core import pipeline
from app.schemas.task import PageTask

SRC = (
    "인공지능과 우리의 미래\n"
    "인공지능 기술은 우리 삶의 모든 영역에서 혁신을 이끌고 있습니다.\n"
    "\n"                                   # ← 빈 줄. 요소를 만들지 않는다
    "의료 분야에서는 질병을 조기에 진단합니다.\n"
    "2026년까지 시장은 3배 성장할 전망이다."
)


@pytest.fixture(scope="module")
def resp() -> dict:
    return asyncio.run(pipeline.run(
        PageTask(job_id="test-mode-b", page_no=1, mode="b", source_text=SRC)))


class TestLineSplit:
    def test_줄마다_요소가_하나씩(self, resp: dict) -> None:
        """종전에는 여기가 1이었다 — 통째로 묶여 나갔다."""
        assert len(resp["braille_text_list"]) == 4

    def test_원문_목록이_비어_있지_않다(self, resp: dict) -> None:
        """종전에는 mode b에서 text_list가 통째로 없었다."""
        assert len(resp["text_list"]) == 4

    def test_원문이_그_줄_그대로(self, resp: dict) -> None:
        got = [t["contents"][0] for t in resp["text_list"]]
        assert got == [ln for ln in SRC.split("\n") if ln.strip()]

    def test_빈_줄은_요소를_안_만든다(self, resp: dict) -> None:
        assert all(t["contents"][0].strip() for t in resp["text_list"])

    def test_order가_원본_줄_번호(self, resp: dict) -> None:
        """빈 줄(3번)이 건너뛴다 — BE가 원문에서 빈 줄 위치를 알 수 있다."""
        assert [t["order"] for t in resp["text_list"]] == [1, 2, 4, 5]


class TestPairing:
    def test_id가_원문과_점역에서_같다(self, resp: dict) -> None:
        """짝짓기의 열쇠. 이게 어긋나면 BE가 줄을 못 맞춘다."""
        assert ([t["id"] for t in resp["text_list"]]
                == [b["id"] for b in resp["braille_text_list"]])

    def test_order도_양쪽이_같다(self, resp: dict) -> None:
        assert ([t["order"] for t in resp["text_list"]]
                == [b["order"] for b in resp["braille_text_list"]])

    def test_점역_내용이_비어_있지_않다(self, resp: dict) -> None:
        for b in resp["braille_text_list"]:
            assert b["contents"] and b["contents"][0].strip()

    def test_점역_항목은_통_문자열_하나(self, resp: dict) -> None:
        """조판 가이드 §3 — 항목이 여럿이면 옛 계약(32칸 조판 줄)으로 돌아간 것이다."""
        for b in resp["braille_text_list"]:
            assert len(b["contents"]) == 1

    def test_숫자가_수표를_달고_나온다(self, resp: dict) -> None:
        """C5 배포 블로커의 mode b 경로 확인 — '2026년'과 '3배'."""
        last = resp["braille_text_list"][-1]["contents"][0]
        assert last.count("⠼") >= 2, last


class TestModeAcUnchanged:
    """mode a·c의 `order`는 나열 순서 1..N 그대로다 — 조용한 계약 변경 금지."""

    def test_a_c는_나열_순서(self) -> None:
        from app.core.pipeline import _line_order

        m = {"x": 7, "y": 9}
        assert [_line_order("c", m, k, i) for i, k in enumerate(["x", "y"])] == [1, 2]
        assert [_line_order("a", m, k, i) for i, k in enumerate(["x", "y"])] == [1, 2]

    def test_b는_읽기_순서를_쓴다(self) -> None:
        from app.core.pipeline import _line_order

        m = {"x": 7, "y": 9}
        assert [_line_order("b", m, k, i) for i, k in enumerate(["x", "y"])] == [7, 9]

    def test_b라도_없으면_나열_순서로_떨어진다(self) -> None:
        from app.core.pipeline import _line_order

        assert _line_order("b", {}, "없는키", 3) == 4


class TestEdgeCases:
    def test_빈_입력도_죽지_않는다(self) -> None:
        r = asyncio.run(pipeline.run(
            PageTask(job_id="test-mode-b-empty", page_no=1, mode="b", source_text="")))
        assert r["status"] in ("COMPLETED", "NEEDS_REVIEW", "BLOCKED")

    def test_한_줄만_있어도_된다(self) -> None:
        r = asyncio.run(pipeline.run(
            PageTask(job_id="test-mode-b-one", page_no=1, mode="b", source_text="한 줄")))
        assert len(r["text_list"]) == 1
        assert r["text_list"][0]["contents"] == ["한 줄"]

    def test_끝에_빈_줄이_붙어도_요소가_안_는다(self) -> None:
        r = asyncio.run(pipeline.run(
            PageTask(job_id="test-mode-b-tail", page_no=1, mode="b",
                     source_text="첫 줄\n둘째 줄\n\n\n")))
        assert len(r["text_list"]) == 2
