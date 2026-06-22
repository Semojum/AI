import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[3]))

JOB_ID     = "test-job-001"
PAGE_NO    = 1
_TEST_DATA  = Path(__file__).parents[2] / "test_data" / "page_001"
RESULT_JSON = _TEST_DATA / "data" / "001_txt_result.json"
LAYOUT_JSON = _TEST_DATA / "merged_layout.json"

VALID_TYPES = {
    "title", "text", "caption", "formula", "list_item",
    "footnote", "sidebar", "header_footer", "page_number",
    "table", "image", "chart", "cartoon",
}

_PLACEHOLDERS = {"이미지 캡셔닝 대기", "[이미지 경로 없음]", "[캡셔닝 실패]"}


def test_fixture_exists():
    assert RESULT_JSON.exists(), f"fixture 없음: {RESULT_JSON}"
    assert LAYOUT_JSON.exists(), f"fixture 없음: {LAYOUT_JSON}"


def _load_result():
    return json.loads(RESULT_JSON.read_text(encoding="utf-8"))


def _load_layout():
    if LAYOUT_JSON.exists():
        return json.loads(LAYOUT_JSON.read_text(encoding="utf-8"))
    return None


def test_result_schema():
    """meta + elements 구조 검증."""
    data = _load_result()
    assert "meta" in data
    assert "elements" in data
    meta = data["meta"]
    assert meta["job_id"] == JOB_ID
    assert meta["page_no"] == PAGE_NO
    assert meta["extraction_method"] in ("TEXT_NATIVE", "OCR")
    for el in data["elements"]:
        for key in ("id", "order", "type", "content"):
            assert key in el, f"'{key}' 필드 없음: {el}"


def test_types_valid():
    """모든 type이 13종 이내."""
    data = _load_result()
    for el in data["elements"]:
        assert el["type"] in VALID_TYPES, f"알 수 없는 type: {el['type']}"


def test_reading_order_sequential():
    """reading_order가 1부터 연속."""
    data = _load_result()
    orders = [el["order"] for el in data["elements"]]
    assert orders == list(range(1, len(orders) + 1)), \
        f"reading_order 불연속: {orders}"


def test_header_footer_position():
    """header_footer/page_number가 맨 앞과 맨 뒤에만 위치."""
    elements = _load_result()["elements"]
    hf_types = {"header_footer", "page_number"}

    first_body = next((i for i, e in enumerate(elements) if e["type"] not in hf_types), None)
    last_body  = next((i for i in range(len(elements) - 1, -1, -1)
                       if elements[i]["type"] not in hf_types), None)

    if first_body is None:
        return

    for el in elements[:first_body]:
        assert el["type"] in hf_types, f"본문 앞에 비-header 요소: {el}"

    for el in elements[last_body + 1:]:
        assert el["type"] in hf_types, f"본문 뒤에 비-footer 요소: {el}"


def test_id_matches_element_id():
    """001_txt_result.json의 id가 merged_layout.json의 element_id와 일치."""
    layout = _load_layout()
    if layout is None:
        return

    layout_ids = {el["element_id"] for el in layout}
    result_ids = {el["id"] for el in _load_result()["elements"]}
    diff = result_ids - layout_ids
    assert not diff, f"result id가 layout element_id에 없음: {diff}"


def test_id_matches_image_filename():
    """이미지 요소의 id == mineru_raw/images/{id}.jpg 파일명."""
    layout = _load_layout()
    if layout is None:
        return

    layout_by_id = {el["element_id"]: el for el in layout}
    for el in _load_result()["elements"]:
        el_id = el["id"]
        if el_id not in layout_by_id:
            continue
        img_path = layout_by_id[el_id].get("image_path")
        if img_path:
            assert Path(img_path).stem == el_id, \
                f"이미지 파일명({Path(img_path).stem}) ≠ element_id({el_id})"


def test_image_captioning_result(monkeypatch):
    """caption/classify를 mock하여 build()가 placeholder 없는 결과를 생성하는지 검증."""
    monkeypatch.setattr(
        "app.ai.builder.result_builder.caption",
        lambda img_path, img_type: "테스트 캡셔닝: 두 학생이 실험 도구를 사용하는 장면입니다.",
    )
    monkeypatch.setattr(
        "app.ai.builder.result_builder.classify",
        lambda img_path: "image",
    )

    from app.ai.builder.result_builder import build

    layout = json.loads(LAYOUT_JSON.read_text(encoding="utf-8"))
    result = build(layout, "test-fixture", PAGE_NO, "TEXT_NATIVE")

    visual = [e for e in result["elements"] if e["type"] in ("image", "cartoon", "chart")]
    assert len(visual) > 0, "시각 요소 없음 — fixture에 image/cartoon/chart 요소가 필요합니다"
    for el in visual:
        assert el["content"] not in _PLACEHOLDERS, \
            f"캡셔닝 미완료 ({el['type']}): '{el['content']}'"
        assert len(el["content"]) > 10, \
            f"캡셔닝 결과가 너무 짧음: '{el['content']}'"


# ── bbox·페이지 크기 전달 회귀 (BE에 좌표 넘기기) ─────────────────────────────
import uuid as _uuid

from app.ai.builder.result_builder import build as _build


def _mk_el(bbox, bbox_px, content="텍스트"):
    return {"element_id": str(_uuid.uuid4()), "reading_order": 1, "type": "text",
            "bbox": bbox, "bbox_px": bbox_px, "page_width": 1680, "page_height": 2376,
            "content": content, "image_path": None, "heading_level": None,
            "caption_ref": None, "flags": []}


class TestBBoxPassthrough:
    def test_경계요소에_bbox_픽셀_포함(self):
        res = _build([_mk_el([120, 87, 392, 104], [202.4, 146.2, 658.6, 174.7])],
                     "t_bbox1", 1, "OCR")
        el = res["elements"][0]
        assert el["bbox"] == [202, 146, 659, 175]   # bbox_px 반올림

    def test_meta에_페이지크기(self):
        res = _build([_mk_el([0, 0, 500, 500], [0, 0, 840, 840])], "t_bbox2", 1, "OCR")
        assert res["meta"]["image_width"] == 1680
        assert res["meta"]["image_height"] == 2376

    def test_bbox_px_없으면_정규화_bbox_폴백(self):
        el = _mk_el([10, 20, 30, 40], None)
        el.pop("bbox_px")
        res = _build([el], "t_bbox3", 1, "OCR")
        assert res["elements"][0]["bbox"] == [10, 20, 30, 40]
