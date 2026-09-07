# -*- coding: utf-8 -*-
"""장식은 '그림 생략'도 남기지 않고 요소째 뺀다 (제작 지침 §6.1.1(4)·§6.3.4(2)②).

배경: 가드가 배지·아이콘을 걸러 캡션을 비우면 우리는 그 자리에 `그림 생략` 을 냈다.
지침은 "장식 용도이거나 본문 이해에 불필요한 경우에는 생략 여부를 표기하지 않는다"고
한다. 점역사에게는 지워야 할 일감만 남던 자리다(dev·val 100쪽 표본에서 4쪽).
"""
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parents[3]))

from app.ai.builder import result_builder as rb  # noqa: E402

_BIG = [100, 100, 500, 500]          # 지면의 16%
_TINY = [100, 100, 130, 130]         # 지면의 0.09%


def _el(bbox, *, px=True):
    el = {"element_id": "e1", "type": "image", "bbox": bbox, "order": 1}
    if px:
        el["bbox_px"] = [1, 1, 2, 2]   # 값은 안 본다 — 있으면 bbox 가 0~1000 정규화라는 표시
    return el


def test_작은_요소만_장식으로_본다():
    assert rb._is_decoration(_el(_TINY))
    assert not rb._is_decoration(_el(_BIG))


def test_좌표계를_모르면_판정하지_않는다():
    """폴백 경로 bbox 는 2배 픽셀이라 같은 나눗셈을 쓰면 값이 뒤집힌다 — 요소를 살린다."""
    assert rb._area_ratio(_el(_TINY, px=False)) is None
    assert not rb._is_decoration(_el(_TINY, px=False))


@pytest.mark.parametrize("bbox, failed, kept", [
    (_TINY, True, 0),     # 설명도 없고 아주 작다 → 장식. 뺀다
    (_TINY, False, 1),    # 설명이 나왔다 → 크기와 무관하게 살린다
    (_BIG, True, 1),      # 큰데 캡셔닝만 실패 → 종전대로 '생략' 표기 + R11
])
def test_장식만_빠진다(tmp_path, monkeypatch, bbox, failed, kept):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(rb, "_caption_all",
                        lambda els: {id(e): ("" if failed else "그림: 실험 장치",
                                             "image", not failed, None) for e in els})
    res = rb.build([_el(bbox)], "job-decor", 1, "OCR")
    assert len(res["elements"]) == kept
    if kept and failed:
        assert "CAPTION_FAILED" in res["elements"][0]["flags"]


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
