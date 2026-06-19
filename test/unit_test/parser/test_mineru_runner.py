import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[3]))

PAGE_NO    = 1
_TEST_DATA = Path(__file__).parents[2] / "test_data" / "page_001"
LAYOUT_JSON = _TEST_DATA / "merged_layout.json"
MINERU_RAW  = _TEST_DATA / "mineru_raw"

_PROJECT_ROOT = Path(__file__).parents[3]

VALID_TYPES = {
    "title", "text", "caption", "formula", "list_item",
    "footnote", "sidebar", "header_footer", "page_number",
    "table", "image", "chart", "cartoon",
}


def test_fixture_exists():
    assert LAYOUT_JSON.exists(), f"fixture 없음: {LAYOUT_JSON}"
    assert MINERU_RAW.is_dir(), f"fixture 없음: {MINERU_RAW}"


def _load():
    return json.loads(LAYOUT_JSON.read_text(encoding="utf-8"))


def test_merged_layout_schema():
    """필수 필드 전체 존재, type이 13종 이내."""
    data = _load()
    assert len(data) > 0
    for el in data:
        for key in ("element_id", "reading_order", "type", "bbox", "image_path", "flags"):
            assert key in el, f"'{key}' 필드 없음: {el}"
        assert el["type"] in VALID_TYPES, f"알 수 없는 type: {el['type']}"


def test_image_path_format():
    """image_path가 있으면 mineru_raw/images/{uuid}.jpg 형식이고 파일 존재."""
    data = _load()
    for el in data:
        if el["image_path"] is None:
            continue
        p = _PROJECT_ROOT / el["image_path"]
        assert p.exists(), f"image_path 파일 없음: {p}"
        assert "mineru_raw/images" in el["image_path"].replace("\\", "/"), \
            f"경로 형식 불일치: {el['image_path']}"
        stem = p.stem
        assert len(stem) == 36, f"파일명이 UUID 형식이 아님: {stem}"


def test_no_unnecessary_files():
    """불필요 파일(*_v2.json, *.md, *_layout.pdf, *_origin.pdf) 없음."""
    for pattern in ("*_content_list_v2.json", "*.md", "*_layout.pdf", "*_origin.pdf"):
        found = list(MINERU_RAW.rglob(pattern))
        assert len(found) == 0, f"불필요 파일 존재 ({pattern}): {found}"


def test_mineru_raw_images_dir():
    """mineru_raw/images/ 폴더 존재."""
    assert (MINERU_RAW / "images").is_dir(), "mineru_raw/images/ 폴더 없음"


def test_mineru_raw_flat_structure():
    """mineru_raw/ 바로 아래에 *.json 파일이 있어야 함 (중첩 서브디렉토리 아님)."""
    json_files = list(MINERU_RAW.glob("*.json"))
    assert len(json_files) > 0, "mineru_raw/ 루트에 JSON 파일 없음"


def test_no_review_needed_flag():
    """REVIEW_NEEDED 플래그가 없음."""
    data = _load()
    for el in data:
        assert "REVIEW_NEEDED" not in el["flags"], \
            f"REVIEW_NEEDED 플래그 발견: element_id={el['element_id']}"
