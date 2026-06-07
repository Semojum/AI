"""T5-1 BE 데모 데이터셋 무결성 테스트 (GPU-free).

데이터셋 구조·유형 커버리지·manifest 정합을 검증한다. 파이프라인은 돌리지 않는다
(실행 대조는 demo_runner / T5-2). expected_braille는 placeholder(None)여도 통과한다.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

_DEMO_DIR = Path(__file__).parent.parent.parent / "test_data" / "demo_set"
_ALLOWED_TYPES = {
    "text", "title", "list_item", "formula", "table", "image", "cartoon",
    "chart_graph", "header_footer", "page_number", "footnote", "sidebar", "caption",
}
_REQUIRED_MIX = {"text", "formula", "table", "image", "chart_graph"}


@pytest.fixture(scope="module")
def manifest() -> dict:
    return json.loads((_DEMO_DIR / "manifest.json").read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def pages(manifest) -> list[dict]:
    return [json.loads((_DEMO_DIR / e["file"]).read_text(encoding="utf-8")) for e in manifest["pages"]]


class TestManifest:
    def test_최소_10페이지(self, manifest):
        assert manifest["page_count"] >= 10

    def test_manifest_파일수_일치(self, manifest):
        on_disk = list((_DEMO_DIR / "pages").glob("*.json"))
        assert len(on_disk) == manifest["page_count"] == len(manifest["pages"])

    def test_demo_id_유일(self, manifest):
        ids = [e["demo_id"] for e in manifest["pages"]]
        assert len(ids) == len(set(ids))

    def test_요구_혼합_커버(self, manifest):
        assert _REQUIRED_MIX.issubset(set(manifest["type_coverage"]))
        assert manifest["required_mix_covered"] is True

    def test_manifest_파일_실재(self, manifest):
        for e in manifest["pages"]:
            assert (_DEMO_DIR / e["file"]).exists(), e["file"]


class TestPages:
    def test_txt_result_구조(self, pages):
        for p in pages:
            meta = p["txt_result"]["meta"]
            assert meta["extraction_method"] == "TEXT_NATIVE"
            assert p["txt_result"]["elements"], p["demo_id"]

    def test_요소_필드(self, pages):
        for p in pages:
            for el in p["txt_result"]["elements"]:
                assert {"id", "order", "type", "content"} <= el.keys()
                assert el["type"] in _ALLOWED_TYPES, f"{p['demo_id']}: {el['type']}"
                assert el["content"].strip()

    def test_order_연속_유일(self, pages):
        for p in pages:
            orders = [el["order"] for el in p["txt_result"]["elements"]]
            assert orders == list(range(1, len(orders) + 1)), p["demo_id"]

    def test_declared_types_정합(self, pages):
        for p in pages:
            actual = {el["type"] for el in p["txt_result"]["elements"]}
            assert set(p["declared_types"]) == actual, p["demo_id"]

    def test_expected_placeholder_허용(self, pages):
        for p in pages:
            assert p["expected_braille"] is None or isinstance(p["expected_braille"], list)


class TestRunnerLoader:
    def test_load_pages(self):
        sys.path.insert(0, str(_DEMO_DIR.parent.parent))  # test/ 디렉토리
        import demo_runner
        assert len(demo_runner.load_pages()) >= 10
        one = demo_runner.load_pages(only_id="p01")
        assert len(one) == 1 and one[0]["demo_id"] == "p01"

    def test_count_tiers(self, tmp_path, monkeypatch):
        # 리뷰 #2: FALLBACK 집계를 opt 산출물(routing_tier)에서 — braille_text_list엔 없음.
        sys.path.insert(0, str(_DEMO_DIR.parent.parent))
        import demo_runner
        monkeypatch.chdir(tmp_path)
        base = tmp_path / "storage/jobs/J/temp/page_001/type"
        (base / "text").mkdir(parents=True)
        (base / "text" / "text_opt.json").write_text(
            json.dumps([{"routing_tier": "FALLBACK"}, {"routing_tier": "QUALITY"}]), encoding="utf-8")
        (base / "image").mkdir(parents=True)
        (base / "image" / "image_opt.json").write_text(
            json.dumps([{"routing_tier": "ZERO"}]), encoding="utf-8")
        total, fb = demo_runner.count_tiers("J")
        assert total == 3 and fb == 1

    def test_count_tiers_없는_job(self, tmp_path, monkeypatch):
        sys.path.insert(0, str(_DEMO_DIR.parent.parent))
        import demo_runner
        monkeypatch.chdir(tmp_path)
        assert demo_runner.count_tiers("missing") == (0, 0)
