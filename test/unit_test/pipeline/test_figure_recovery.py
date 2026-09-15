"""놓친 그림 회수 — 켤 조건과 요소 변환 (원장 C-02 계열).

평가 실측(dev-2027 32쪽, LLM 켬): 시각 요소를 잡은 쪽은 우리가 gold의 381%를 쓰는데
**시각 요소가 0인 26쪽에서는 1%**다. 프롬프트·포장으로는 그 26쪽이 안 움직인다.
비전 모델 실측: 재현 4/4 · 오검출 0/10(opus) · 1/10(sonnet).
"""
from __future__ import annotations

import pytest

from app.ai.parser import figure_detect as F


class TestGate:
    """A/B(무-LLM)와 키 없는 환경에서는 절대 돌지 않아야 한다 — 과금·비결정성 때문이다."""

    def test_무_LLM_실행에서는_꺼진다(self, monkeypatch) -> None:
        monkeypatch.setenv("DISABLE_LLM_FALLBACK", "1")
        assert F.enabled() is False

    def test_스위치로_끌_수_있다(self, monkeypatch) -> None:
        monkeypatch.delenv("DISABLE_LLM_FALLBACK", raising=False)
        monkeypatch.setenv("FIGURE_DETECT", "0")
        assert F.enabled() is False

    def test_키가_없으면_꺼진다(self, monkeypatch) -> None:
        monkeypatch.delenv("DISABLE_LLM_FALLBACK", raising=False)
        monkeypatch.setenv("FIGURE_DETECT", "1")
        monkeypatch.setattr(F.config, "anthropic_api_key", "", raising=False)
        assert F.enabled() is False


class TestToElements:
    def test_유형이_체인에_맞게_갈린다(self) -> None:
        figs = [{"kind": "그래프", "x0": 0, "y0": 0, "x1": 50, "y1": 20, "what": "a"},
                {"kind": "모식도", "x0": 0, "y0": 30, "x1": 50, "y1": 50, "what": "b"},
                {"kind": "만화", "x0": 0, "y0": 60, "x1": 50, "y1": 80, "what": "c"}]
        got = [e["type"] for e in F.to_elements(figs, 1000, 1000, 1)]
        assert got == ["chart_graph", "diagram", "cartoon"]

    def test_추정_좌표는_bbox_est_에만_담는다(self) -> None:
        """#875 — 비전 모델 눈대중을 경계 bbox 로 내보내면 FE 가 엉뚱한 자리를 짚는다."""
        e = F.to_elements([{"kind": "사진", "x0": 10, "y0": 20, "x1": 60, "y1": 50,
                            "what": "사진"}], 1000, 2000, 1)[0]
        assert e["bbox"] is None
        assert e["bbox_est"] == [100, 400, 600, 1000]
        assert "BBOX_UNKNOWN" in e["flags"]

    def test_읽기순서는_위에서_아래로(self) -> None:
        figs = [{"kind": "그림", "x0": 0, "y0": 80, "x1": 9, "y1": 90, "what": "아래"},
                {"kind": "그림", "x0": 0, "y0": 10, "x1": 9, "y1": 20, "what": "위"}]
        got = [e["content"] for e in F.to_elements(figs, 100, 100, 1)]
        assert got == ["위", "아래"]

    @pytest.mark.parametrize("bad", [
        {"kind": "그림", "x0": 0, "y0": 0, "x1": 0, "y1": 0, "what": "빈 상자"},
        {"kind": "그림", "x0": 0, "y0": 0, "x1": 9, "y1": 9, "what": ""},
        {"kind": "그림", "what": "좌표 없음"},
    ])
    def test_망가진_검출은_버린다(self, bad: dict) -> None:
        assert F.to_elements([bad], 100, 100, 1) == []

    def test_회수분에_표시가_남는다(self) -> None:
        """품질 추적용 — 회수분이 원래 추출분과 섞이면 원인을 못 가른다."""
        e = F.to_elements([{"kind": "그림", "x0": 0, "y0": 0, "x1": 9, "y1": 9,
                            "what": "x"}], 100, 100, 1)[0]
        assert "FIGURE_RECOVERED" in e["flags"]


class TestPlacement:
    """회수분은 bbox 가 없으므로 기하 보정이 안 잡는다 — 자리를 여기서 정해 둔다(#875)."""

    def test_추정_y_자리에_끼워_넣는다(self) -> None:
        from app.core.pipeline import _place_recovered_figures
        elements = [{"order": 1, "bbox": [0, 100, 500, 140], "content": "위"},
                    {"order": 2, "bbox": [0, 600, 500, 640], "content": "아래"}]
        add = F.to_elements([{"kind": "그래프", "x0": 10, "y0": 30, "x1": 60, "y1": 45,
                              "what": "가운데 그래프"}], 1000, 1000, 3)
        _place_recovered_figures(elements, add)
        assert [e["content"] for e in elements] == ["위", "가운데 그래프", "아래"]
        assert [e["order"] for e in elements] == [1, 2, 3]

    def test_추정값이_없으면_끝에_붙인다(self) -> None:
        from app.core.pipeline import _place_recovered_figures
        elements = [{"order": 1, "bbox": [0, 100, 500, 140], "content": "본문"}]
        _place_recovered_figures(elements, [{"order": 9, "content": "좌표 없음"}])
        assert [e["content"] for e in elements] == ["본문", "좌표 없음"]

    def test_응답에는_좌표가_0으로_나간다(self) -> None:
        """bbox 가 없는 요소는 BoundingBox 가 (0,0,0,0) — 지어낸 좌표를 안 싣는다."""
        from app.core.pipeline import _valid_bbox
        from app.schemas.layout import BBoxItem
        from uuid import uuid4
        b = BBoxItem(element_id=uuid4(), type="chart_graph", bbox=(0, 0, 0, 0),
                     reading_order=1, flags=["FIGURE_RECOVERED", "BBOX_UNKNOWN"])
        assert _valid_bbox(b) is False
