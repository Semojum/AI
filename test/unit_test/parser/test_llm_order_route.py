"""읽기순서 LLM 라우팅 — 2단(곁단 없음) 지면만 부른다(#1086, pm 결재 2026-10-05).

판정 규칙은 측정에 쓴 classify39.work 와 같다. 2027 끔 팔 경계 1,745쪽에서 두 판정이 쪽마다 같았다(어긋남 0).
쪽 크기 1000×1400 픽셀을 가정한 합성 요소로 갈래 셋을 본다.
"""
import asyncio

from app.ai.parser import llm_order
from app.schemas.layout import BBoxItem, LayoutResult

W, H = 1000, 1400


def _items(*cols):
    """cols = [(x0, x1), …] 열마다 세로로 요소 셋."""
    out = []
    for x0, x1 in cols:
        for k in range(3):
            out.append(BBoxItem(type="text", bbox=(x0, 200 + 300 * k, x1, 400 + 300 * k), reading_order=len(out)))
    return out


def test_2단은_곁단_없음():
    assert llm_order._layout_class(_items((60, 480), (520, 940)), W, H) == (2, False)


def test_좁은_곁단이_붙은_2단():
    assert llm_order._layout_class(_items((60, 600), (700, 900)), W, H) == (2, True)


def test_1단_전폭_요소는_빼고_센다():
    items = _items((100, 500)) + [BBoxItem(type="text", bbox=(50, 1200, 950, 1300), reading_order=9)]
    assert llm_order._layout_class(items, W, H) == (1, False)


def test_2단이_아니면_부르지_않는다(monkeypatch):
    monkeypatch.setattr(llm_order, "enabled", lambda: True)
    monkeypatch.setattr(llm_order, "_ask", lambda p: (_ for _ in ()).throw(AssertionError("불렀다")))
    out = asyncio.run(llm_order.apply(LayoutResult(page_id="p", elements=_items((100, 500), (120, 520))), {}, 0, (W, H)))
    assert not out["called"] and out["reason"] == "부류 1단"


def test_2단이면_부른다(monkeypatch):
    monkeypatch.setattr(llm_order, "enabled", lambda: True)
    monkeypatch.setattr(llm_order, "_ask", lambda p: (list(range(6)), 1, 1))
    out = asyncio.run(llm_order.apply(LayoutResult(page_id="p", elements=_items((60, 480), (520, 940))), {}, 0, (W, H)))
    assert out["called"] and out["applied"]
