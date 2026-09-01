"""글자를 그림으로 잡은 것을 가르는 가드 (원장 C-40 부록, 2026-08-23).

가르는 신호는 '같은 자리를 두 번 잡았는가'다. 정상이면 레이아웃이 텍스트와 그림을
갈라 놓으므로 겹칠 이유가 없다. dev 정상 시각 요소 830건에 IoU 0.8 이상이 0건이다.
"""
from app.ai.parser.mineru_runner import _bbox_iou, _mark_text_lookalikes


def _el(t, bbox, eid="e1"):
    return {"element_id": eid, "type": t, "bbox": list(bbox)}


def test_텍스트와_자리가_같으면_표시된다():
    """글자를 그림으로 잡은 경우. IoU 1.00."""
    els = [_el("text", [65, 370, 621, 551], "t1"),
           _el("image", [65, 370, 621, 551], "v1")]
    assert _mark_text_lookalikes(els, 1) == 1
    assert els[1]["text_lookalike_iou"] == 1.0


def test_텍스트와_안_겹치는_그림은_통과한다():
    els = [_el("text", [65, 100, 621, 200], "t1"),
           _el("image", [65, 400, 621, 600], "v1")]
    assert _mark_text_lookalikes(els, 1) == 0
    assert "text_lookalike_iou" not in els[1]


def test_축_라벨이_겹쳐도_정상_그림은_통과한다():
    """★ 제일 중요한 케이스. 실물 좌표다(dev 실측).

    `chart_graph [174,177,363,284]` 가 텍스트 요소 `[111,101,723,299]` 안에 완전히 든다.
    덮인 비율은 **1.00**이지만 IoU는 **0.167**이다. 덮인 비율로 걸렀다면 이 정상 그림이
    죽었을 것이다(전수에서 그렇게 죽는 것이 3.0%였다).
    """
    els = [_el("text", [111, 101, 723, 299], "t1"),
           _el("chart_graph", [174, 177, 363, 284], "v1")]
    assert _bbox_iou(els[1]["bbox"], els[0]["bbox"]) < 0.2
    assert _mark_text_lookalikes(els, 1) == 0
    assert "text_lookalike_iou" not in els[1]


def test_임계_아래는_통과한다():
    """0.8 미만이면 표시하지 않는다 — 여유를 둔 값이다."""
    els = [_el("text", [0, 0, 100, 100], "t1"),
           _el("image", [0, 0, 100, 78], "v1")]      # IoU 0.78
    assert 0.7 < _bbox_iou(els[1]["bbox"], els[0]["bbox"]) < 0.8
    assert _mark_text_lookalikes(els, 1) == 0


def test_텍스트_요소가_없으면_아무것도_안_한다():
    els = [_el("image", [0, 0, 100, 100], "v1")]
    assert _mark_text_lookalikes(els, 1) == 0


def test_bbox_없는_요소는_건너뛴다():
    els = [{"element_id": "t1", "type": "text"}, {"element_id": "v1", "type": "image"}]
    assert _mark_text_lookalikes(els, 1) == 0
