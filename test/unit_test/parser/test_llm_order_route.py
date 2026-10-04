"""읽기순서 LLM 라우팅 · 안전판 — 2단(곁단 없음) 지면만 부르고(#1086), 오른쪽 단으로 시작하면 되돌린다(#1090).

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


def _two(monkeypatch, cols, order):
    monkeypatch.setattr(llm_order, "enabled", lambda: True)
    monkeypatch.setattr(llm_order, "_ask", lambda p: (order, 1, 1))
    items = _items(*cols)
    out = asyncio.run(llm_order.apply(LayoutResult(page_id="p", elements=items), {}, 0, (W, H)))
    return out, [b.reading_order for b in items]


def test_오른쪽_단으로_시작하면_되돌린다(monkeypatch):
    # 사회 · 문화 해설 p0042 꼴 — 규칙은 왼쪽 단부터 맞게 냈는데 LLM 이 두 단을 통째로 맞바꿈(옮긴 비율 1.0)
    out, ro = _two(monkeypatch, ((60, 480), (520, 940)), [3, 4, 5, 0, 1, 2])
    assert out["reverted"] and out["reason"] == "안전판" and ro == [0, 1, 2, 3, 4, 5]


def test_왼쪽_단으로_시작하면_다_옮겨도_받는다(monkeypatch):
    # 생활과 윤리 해설 면 꼴 — 규칙이 오른쪽 단을 앞에 둔 것을 LLM 이 왼쪽 단부터 바로잡음. 옮긴 비율 1.0 이라 종전 0.7 은 막았다
    out, ro = _two(monkeypatch, ((520, 940), (60, 480)), [3, 4, 5, 0, 1, 2])
    assert out["applied"] and out["ratio"] == 1.0 and ro == [4, 5, 6, 1, 2, 3]
