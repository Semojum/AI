"""PART 3 — LayoutMerger 단위 테스트."""

from uuid import uuid4

import pytest

from app.ai.layout.layout_merger import LayoutMerger, _iou


class TestIou:

    def test_identical(self) -> None:
        assert _iou([0, 0, 100, 100], [0, 0, 100, 100]) == pytest.approx(1.0)

    def test_no_overlap(self) -> None:
        assert _iou([0, 0, 50, 50], [60, 60, 100, 100]) == pytest.approx(0.0)

    def test_partial_overlap(self) -> None:
        iou = _iou([0, 0, 100, 100], [50, 50, 150, 150])
        assert 0.0 < iou < 1.0

    def test_zero_area_no_crash(self) -> None:
        assert _iou([0, 0, 0, 0], [0, 0, 0, 0]) == pytest.approx(0.0)


class TestLayoutMerger:

    def _q(self, x1, y1, x2, y2, etype="text", order=1):
        return {
            "element_id": str(uuid4()),
            "type": etype,
            "bbox": [x1, y1, x2, y2],
            "reading_order": order,
            "heading_level": None,
        }

    def _y(self, x1, y1, x2, y2, conf=0.8):
        return {"bbox": [x1, y1, x2, y2], "type": "text", "conf": conf}

    def test_iou_above_threshold_qwen_wins(self, tmp_path, monkeypatch) -> None:
        monkeypatch.chdir(tmp_path)
        result = LayoutMerger().merge(
            [self._q(0, 0, 100, 100)],
            [self._y(5, 5, 95, 95)],
            "j1", 1,
        )
        assert len(result.elements) == 1

    def test_no_overlap_yolo_appended(self, tmp_path, monkeypatch) -> None:
        monkeypatch.chdir(tmp_path)
        result = LayoutMerger().merge(
            [self._q(0, 0, 100, 100)],
            [self._y(200, 200, 300, 300)],
            "j2", 1,
        )
        assert len(result.elements) == 2

    def test_empty_yolo(self, tmp_path, monkeypatch) -> None:
        monkeypatch.chdir(tmp_path)
        result = LayoutMerger().merge([self._q(0, 0, 100, 100)], [], "j3", 1)
        assert len(result.elements) == 1

    def test_reading_order_left_col_first(self, tmp_path, monkeypatch) -> None:
        """좌열 요소 reading_order < 우열 요소 reading_order (2단 레이아웃 활성화 조건: right>1)."""
        monkeypatch.chdir(tmp_path)
        left = self._q(50, 100, 550, 200, order=3)
        right1 = self._q(650, 100, 1150, 200, order=1)
        right2 = self._q(650, 250, 1150, 350, order=2)
        result = LayoutMerger().merge([right1, right2, left], [], "j4", 1, img_width=1240)
        left_e = next(e for e in result.elements if e.bbox[0] < 620)
        right_es = [e for e in result.elements if e.bbox[0] >= 620]
        assert all(left_e.reading_order < r.reading_order for r in right_es)

    def test_merged_layout_json_saved(self, tmp_path, monkeypatch) -> None:
        monkeypatch.chdir(tmp_path)
        LayoutMerger().merge([self._q(0, 0, 100, 100)], [], "j5", 2)
        assert (tmp_path / "storage/jobs/j5/temp/page_002/layout/merged_layout.json").exists()

    def test_caption_ref_linked(self, tmp_path, monkeypatch) -> None:
        monkeypatch.chdir(tmp_path)
        img = self._q(100, 100, 600, 400, etype="image")
        cap = self._q(100, 410, 600, 440, etype="caption")
        result = LayoutMerger().merge([img, cap], [], "j6", 1)
        cap_elem = next(e for e in result.elements if e.type == "caption")
        assert cap_elem.caption_ref is not None
