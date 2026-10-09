"""따로 뽑힌 문항 번호를 같은 줄 발문에 붙인다(원장 C-107 (ㄴ), #1050).

좌표는 004 body p0015 경계 파일 그대로(0~1000 정규화). gold `  #ja …` = `01 발문` 한 줄.
"""
from uuid import uuid4

import pytest

from app.core import pipeline
from app.core.pipeline import _parse_txt_result


@pytest.fixture(autouse=True)
def _form_off(monkeypatch):
    # 번호 붙이기만 본다. 코드 꼴(기본 X)은 test_place_item_codes.py 가 본다.
    monkeypatch.setattr(pipeline, "_ITEM_CODE_FORM", "off")


def _el(typ, content, bbox):
    return {"id": str(uuid4()), "type": typ, "content": content, "bbox": bbox}


def _parse(els):
    ex = {"meta": {"extraction_method": "OCR", "bbox_space": "norm1000",
                   "image_width": 1240, "image_height": 1754}, "elements": els}
    lay, em, _ = _parse_txt_result(ex, "p")
    return [(b.type, em[b.element_id].corrected_text)
            for b in sorted(lay.elements, key=lambda b: b.reading_order)]


def test_기본_X_꼴이면_번호_코드_발문이_한_줄(monkeypatch):
    monkeypatch.setattr(pipeline, "_ITEM_CODE_FORM", "X")
    out = _parse([
        _el("title", "[26004-0003]", [222, 116, 305, 132]),
        _el("title", "01", [145, 137, 183, 164]),
        _el("text", "<보기>를 참고하여 탐구한 내용으로 적절한 것은?", [222, 139, 783, 158]),
    ])
    assert out[0] == ("text", "01 [26004-0003] <보기>를 참고하여 탐구한 내용으로 적절한 것은?")   # gold X 꼴(004)


def test_번호가_발문_앞에_붙고_번호_요소는_빠진다():
    out = _parse([
        _el("title", "[26004-0003]", [222, 116, 305, 132]),
        _el("title", "01", [145, 137, 183, 164]),
        _el("text", "<보기>를 참고하여 탐구한 내용으로 적절한 것은?", [222, 139, 783, 158]),
        _el("text", "① 가  ② 나", [236, 187, 867, 227]),
    ])
    assert ("text", "01 <보기>를 참고하여 탐구한 내용으로 적절한 것은?") in out
    assert all(t != "01" for _, t in out)
    assert len(out) == 3


def test_page_number_형_번호도_붙는다():
    # ★ #1068 — 번호 요소의 형을 안 가리는 것은 일부러다. d8c dev·val 쪽 가운데 `page_number` 번호 232 중 209 가
    #   이 동작으로 살아난다. 이 시험이 깨지면 그 209 가 한꺼번에 사라지고 `02` 가 페이지행 쪽 번호 자리를 차지한다.
    out = _parse([
        _el("page_number", "02", [145, 603, 186, 632]),
        _el("text", "<보기>를 참조하여 빈칸을 채우시오.", [222, 607, 538, 626]),
        _el("text", "본문 둘째 줄", [229, 823, 847, 843]),
    ])
    assert out[0] == ("text", "02 <보기>를 참조하여 빈칸을 채우시오.")


def test_상자로_시작하는_발문엔_안_붙인다():
    out = _parse([
        _el("title", "01", [145, 137, 183, 164]),
        _el("text", "<!상자>보기<!/상자>\n본문", [222, 139, 783, 158]),
        _el("text", "다른 글", [229, 823, 847, 843]),
    ])
    assert ("title", "01") in out


def test_제목_짝과_멀리_떨어진_번호는_그대로():
    out = _parse([
        _el("title", "7", [100, 100, 120, 120]),
        _el("title", "방어 작용", [130, 100, 300, 120]),          # 단원 제목 — 짝은 text 형만
        _el("text", "먼 발문", [400, 300, 800, 320]),             # 세로로 안 겹침
    ])
    assert ("title", "7") in out and ("text", "먼 발문") in out
