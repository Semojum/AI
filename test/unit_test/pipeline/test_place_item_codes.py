"""문항코드 자리 스위치(원장 C-107, #1052). 기본 X(대표 결재 2026-10-04), 요청마다 Y · off 로 바꾼다.

좌표는 014 body p0023 경계 그대로 — 코드가 발문 첫 줄 **오른쪽 위**에 앉고 MinerU 는 발문 뒤에 낸다.
"""
from uuid import uuid4

import pytest

from app.core import pipeline as P


def _parse(form, els, monkeypatch):
    monkeypatch.setattr(P, "_ITEM_CODE_FORM", form)
    ex = {"meta": {"extraction_method": "OCR", "bbox_space": "norm1000",
                   "image_width": 1240, "image_height": 1754}, "elements": els}
    lay, em, _ = P._parse_txt_result(ex, "p")
    return [(b.type, em[b.element_id].corrected_text)
            for b in sorted(lay.elements, key=lambda b: b.reading_order)]


def _page():
    e = lambda t, c, b: {"id": str(uuid4()), "type": t, "content": c, "bbox": b}
    return [e("text", "<!강조>01<!/강조>  다음 가상 대화에서 스승의 입장으로 가장 적절한 것은?", [100, 112, 470, 132]),
            e("title", "[26015-0017]", [416, 101, 490, 114]),
            e("text", "① 모든 사람이 관직을 맡는 이상 사회를 지향해야 한다.", [100, 397, 470, 416]),
            e("text", "② 사회 규범은 도덕적 삶을 살아가는 데 기여할 수 없다.", [100, 418, 475, 436])]


def test_off_는_종전_동작(monkeypatch):
    out = _parse("off", _page(), monkeypatch)
    assert ("title", "[26015-0017]") in out and len(out) == 4


def test_Y는_코드를_발문_바로_앞_문단으로(monkeypatch):
    out = _parse("Y", _page(), monkeypatch)
    i = out.index(("text", "[26015-0017]"))
    assert out[i + 1][1].startswith("<!강조>01")


def test_X는_번호_뒤에_합친다(monkeypatch):
    out = _parse("X", _page(), monkeypatch)
    assert out[0] == ("text", "<!강조>01<!/강조> [26015-0017] 다음 가상 대화에서 스승의 입장으로 가장 적절한 것은?")
    assert len(out) == 3


@pytest.mark.parametrize("form", ["Y", "X"])
def test_짝_발문이_없으면_손대지_않는다(form, monkeypatch):
    els = _page()
    els[0]["bbox"] = [100, 300, 470, 320]            # 발문이 코드에서 멀리 아래
    out = _parse(form, els, monkeypatch)
    assert ("title", "[26015-0017]") in out and len(out) == 4


def test_서버_기본은_X():
    import os
    assert P._ITEM_CODE_FORM == os.environ.get("ITEM_CODE_FORM", "X")


def test_요청마다_고른_꼴이_서버_기본을_이긴다(monkeypatch):
    monkeypatch.setattr(P, "_ITEM_CODE_FORM", "X")
    tok = P._ITEM_CODE_FORM_JOB.set("Y")
    try:
        ex = {"meta": {"extraction_method": "OCR", "bbox_space": "norm1000",
                       "image_width": 1240, "image_height": 1754}, "elements": _page()}
        lay, em, _ = P._parse_txt_result(ex, "p")
        out = [(b.type, em[b.element_id].corrected_text) for b in sorted(lay.elements, key=lambda b: b.reading_order)]
        assert ("text", "[26015-0017]") in out                  # Y: 코드가 제 문단으로
    finally:
        P._ITEM_CODE_FORM_JOB.reset(tok)


def test_PageTask_는_proto_에_필드가_없어도_빈_값():
    from types import SimpleNamespace
    from app.schemas.task import PageTask
    req = SimpleNamespace(job_id="j", page_no=1, total_pages=1, pdf_data=b"", mode="c", source_text="")
    assert PageTask.from_proto(req).item_code_form == ""
