"""응답 끊을 자리(`TextElement.breaks` 19 · `Draft.breaks` 5, 이슈 #1240) 배선 — proto 번호 · dict → proto · 초안 불변식.

계산 자체(`layout_braille._flat_breaks`)와 접은 결과 = AI 조판 대조는 `test/unit_test/braille/test_flat_breaks_1240.py`.
"""
from __future__ import annotations

from uuid import uuid4

from app.ai.braille.layout_braille import flatten_elements
from app.core import grpc_server
from app.core.pipeline import _draft_breaks, _draft_contents, _selected_breaks, _selected_lines
from app.schemas.content import BrailleOutput, Draft
from app.schemas.layout import BBoxItem, LayoutResult
from protos.generated import braille_service_pb2 as pb


def test_번호():
    assert pb.TextElement.DESCRIPTOR.fields_by_name["breaks"].number == 19
    assert pb.Draft.DESCRIPTOR.fields_by_name["breaks"].number == 5


def test_dict_에서_proto_로_싣는다():
    e = grpc_server._dict_to_text_element({"contents": ["⠁⠀⠃"], "breaks": [1],
                                           "drafts": [{"contents": ["⠉⠀⠙"], "breaks": [1]}]})
    assert list(e.breaks) == [1] and list(e.drafts[0].breaks) == [1]
    assert list(grpc_server._dict_to_text_element({"contents": ["⠁"]}).breaks) == []   # 없으면 빈 목록(모름)


def test_고른_초안의_끊을_자리가_본문과_같다():
    """proto 불변식 `contents == drafts[selected_idx].contents` 처럼 끊을 자리도 같아야 한다."""
    lines, bps = ["⠁⠀⠃⠀⠉", "⠙⠀⠑"], [[1, 3], [1]]
    bo = BrailleOutput(element_id=uuid4(), braille_lines=lines, break_points=bps, selected_idx=1,
                       drafts=[Draft(option=1, label="a", text="a", braille_lines=["⠋"]),
                               Draft(option=2, label="b", text="b", braille_lines=lines, break_points=bps)])
    lr = LayoutResult(page_id="p1", elements=[BBoxItem(element_id=bo.element_id, type="image",
                                                       bbox=(0, 0, 1, 1), reading_order=1)])
    flat = flatten_elements([bo], lr)
    assert _draft_contents(bo, bo.drafts[1], 1, flat) == _selected_lines(bo, flat)
    assert _draft_breaks(bo, 1, flat) == _selected_breaks(bo, flat) != []
    assert _selected_breaks(None, flat) == [] and _draft_breaks(bo, 5, flat) == []
