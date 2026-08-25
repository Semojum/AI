"""캡셔닝 동시 처리 불변식 (2026-07-29).

배경: `result_builder.build()`가 시각요소를 `for` 루프로 한 장씩 캡셔닝해,
소요 시간이 개수에 정비례했다(실측 8.86초/개 — 그림 11개 페이지에서 97.5초).
캡셔닝은 외부 API 호출이라 GPU를 안 쓰므로 동시에 던져도 서로 막지 않는다.

동시 처리로 바꾸면서 깨지기 쉬운 것 세 가지를 여기서 고정한다:
  1. **결과가 요소에 정확히 매핑된다** — 완료 순서가 뒤섞여도 A의 캡션이 B에 붙지 않는다.
  2. **요소 격리** — 한 요소가 예외를 던져도 나머지 요소와 페이지가 살아남는다(불변규칙 3).
  3. **호출 횟수 보존** — 시각요소 수만큼만 부른다(중복 과금 방지).
"""
from __future__ import annotations

import time
from unittest.mock import patch

# ★ 2026-08-25(C003) — `_do_caption` 이 주변 본문 문맥을 두 번째 인자로 받는다.
#   대역이 그 인자를 안 받으면 TypeError 가 요소 격리에 삼켜져 **빈 캡션**으로
#   돌아온다(실패가 아니라 "캡션이 비었다"로 보인다). 대역도 같이 받게 둔다.

import pytest

from app.ai.builder import result_builder as rb

_VIS = ("image", "cartoon", "chart_graph")


def _el(i: int, typ: str = "image") -> dict:
    return {"element_id": f"e{i:02d}", "type": typ, "order": i,
            "bbox": [0, 0, 100, 100], "content": "", "page_width": 1000, "page_height": 1000}


def _build(els, **kw):
    return rb.build(els, job_id="t", page_no=1, extraction_method="OCR", **kw)


class TestCaptionMapping:
    """결과가 요소에 정확히 붙는가 — 병렬의 첫 번째 위험."""

    def test_완료_순서가_뒤섞여도_요소별_캡션이_맞다(self) -> None:
        # 뒤쪽 요소일수록 빨리 끝나게 해서 완료 순서를 역전시킨다.
        def fake(el, context=""):
            idx = int(el["element_id"][1:])
            time.sleep((6 - idx) * 0.01)
            return f"CAP-{el['element_id']}", el["type"], True, None

        els = [_el(i) for i in range(6)]
        with patch.object(rb, "_do_caption", side_effect=fake):
            out = _build(els)
        got = {e["id"]: e["content"] for e in out["elements"]}
        assert got == {f"e{i:02d}": f"CAP-e{i:02d}" for i in range(6)}

    def test_읽기_순서가_보존된다(self) -> None:
        with patch.object(rb, "_do_caption",
                          side_effect=lambda el, context="": (f"C{el['element_id']}", el["type"], True, None)):
            out = _build([_el(i) for i in range(5)])
        orders = [e["order"] for e in out["elements"]]
        assert orders == sorted(orders), "order가 병렬 완료 순서에 오염되면 안 된다"

    def test_텍스트_요소는_캡셔닝하지_않는다(self) -> None:
        els = [_el(0, "image"), {**_el(1, "text"), "content": "본문"}]
        with patch.object(rb, "_do_caption",
                          side_effect=lambda el, context="": ("CAP", el["type"], True, None)) as m:
            out = _build(els)
        assert m.call_count == 1
        assert {e["content"] for e in out["elements"]} == {"CAP", "본문"}


class TestIsolation:
    """한 요소의 실패가 페이지를 죽이지 않는다 (불변규칙 3)."""

    def test_한_요소_예외가_나머지를_죽이지_않는다(self) -> None:
        def fake(el, context=""):
            if el["element_id"] == "e02":
                raise RuntimeError("boom")
            return f"CAP-{el['element_id']}", el["type"], True, None

        with patch.object(rb, "_do_caption", side_effect=fake):
            out = _build([_el(i) for i in range(5)])
        ids = {e["id"] for e in out["elements"]}
        assert {"e00", "e01", "e03", "e04"} <= ids, "예외 난 요소 외에는 전부 남아야 한다"

    def test_예외_요소도_버리지_않고_실패표시로_남는다(self) -> None:
        """빈 결과 금지 — 요소가 사라지면 학생은 거기 그림이 있었다는 사실도 모른다."""
        def fake(el, context=""):
            if el["element_id"] == "e01":
                raise RuntimeError("boom")
            return "CAP", el["type"], True, None

        with patch.object(rb, "_do_caption", side_effect=fake):
            out = _build([_el(i) for i in range(3)])
        bad = [e for e in out["elements"] if e["id"] == "e01"]
        assert bad and "CAPTION_FAILED" in bad[0]["flags"]

    def test_캡셔닝_실패_요소도_남는다(self) -> None:
        """예외가 아니라 ok=False로 돌아온 경우."""
        with patch.object(rb, "_do_caption",
                          side_effect=lambda el, context="": ("", el["type"], False, None)):
            out = _build([_el(0)])
        assert len(out["elements"]) == 1
        assert "CAPTION_FAILED" in out["elements"][0]["flags"]


class TestCallCount:
    """중복 호출 = 중복 과금. 시각요소 수만큼만 부른다."""

    @pytest.mark.parametrize("n", [1, 2, 5, 11])
    def test_시각요소_수만큼만_호출한다(self, n: int) -> None:
        with patch.object(rb, "_do_caption",
                          side_effect=lambda el, context="": ("CAP", el["type"], True, None)) as m:
            _build([_el(i) for i in range(n)])
        assert m.call_count == n

    def test_시각요소가_없으면_아예_호출하지_않는다(self) -> None:
        els = [{**_el(i, "text"), "content": f"문단{i}"} for i in range(3)]
        with patch.object(rb, "_do_caption") as m:
            out = _build(els)
        m.assert_not_called()
        assert len(out["elements"]) == 3

    def test_동시_1로_제한해도_결과가_같다(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """CAPTION_CONCURRENCY=1은 종전 직렬 동작 — 결과가 동일해야 한다."""
        side = lambda el, context="": (f"CAP-{el['element_id']}", el["type"], True, None)  # noqa: E731
        with patch.object(rb, "_do_caption", side_effect=side):
            par = _build([_el(i) for i in range(4)])
        monkeypatch.setenv("CAPTION_CONCURRENCY", "1")
        with patch.object(rb, "_do_caption", side_effect=side):
            seq = _build([_el(i) for i in range(4)])
        assert [(e["id"], e["content"]) for e in par["elements"]] \
            == [(e["id"], e["content"]) for e in seq["elements"]]


def test_동시_처리가_직렬보다_빠르다() -> None:
    """실제로 겹쳐 도는지 확인 — 이 테스트가 깨지면 병렬화가 무력화된 것이다."""
    delay = 0.05
    side = lambda el: (time.sleep(delay), ("CAP", el["type"], True, None))[1]  # noqa: E731
    n = 8
    with patch.object(rb, "_do_caption", side_effect=side):
        t0 = time.monotonic()
        _build([_el(i) for i in range(n)])
        elapsed = time.monotonic() - t0
    assert elapsed < delay * n * 0.7, f"직렬과 다를 바 없다: {elapsed:.2f}s (직렬 예상 {delay*n:.2f}s)"
