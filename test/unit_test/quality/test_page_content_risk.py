"""페이지 수준 '내용 누락 의심' 플래그 (confidence.page_content_risk).

gold 없이 런타임에 시각자료·표 셀 비중으로 검수 고지. 셀 출력 불변(메타데이터).
실측 저오탐 조작점: 시각/표 셀이 페이지 점자의 40% 이상이면 고지.
"""
from __future__ import annotations

from app.ai.quality.confidence import page_content_risk


def _el(etype: str, n_cells: int) -> dict:
    # n_cells개의 점자 셀(⠿, U+283F)로 채운 요소
    return {"type": etype, "contents": ["⠿" * n_cells]}


class TestPageContentRisk:
    def test_visual_heavy_page_flagged(self):
        # 시각/표가 페이지 셀의 60% → 고지
        els = [_el("text", 80), _el("image", 120)]
        msg = page_content_risk(els)
        assert msg is not None and "검수" in msg

    def test_text_heavy_page_not_flagged(self):
        # 시각 비중 낮음(20%) → 무플래그
        els = [_el("text", 400), _el("chart_graph", 100)]
        assert page_content_risk(els) is None

    def test_tiny_page_held(self):
        # 총 셀 100 미만(내용 거의 없음)은 판단 보류 — 분모 노이즈 차단
        els = [_el("image", 50)]
        assert page_content_risk(els) is None

    def test_threshold_boundary(self):
        # 정확히 40%는 고지(>=)
        els = [_el("text", 60), _el("table", 40)]
        assert page_content_risk(els) is not None

    def test_all_types_counted_as_visual(self):
        for vt in ("image", "cartoon", "chart_graph", "diagram", "table"):
            els = [_el("text", 40), _el(vt, 120)]
            assert page_content_risk(els) is not None, vt

    def test_no_cells_no_flag(self):
        assert page_content_risk([]) is None
        assert page_content_risk([{"type": "text", "contents": []}]) is None
