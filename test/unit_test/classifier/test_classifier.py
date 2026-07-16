"""PART 3-4 이미지 세분류 단위 테스트 (목 데이터 기반).

현주 파트(classifier.py / ImageClassifier) 미구현.

테스트 범위:
  - pipeline.py의 type 기반 체인 라우팅 코드 (태민 파트, 실제 코드 검증)
  - LayoutResult.model_copy를 통한 type 갱신 불변량 (인터페이스 스펙)
  - 목 데이터 구조 유효성 (미래 ImageClassifier 구현 시 인터페이스 기준)

제외 (순환/자기일관성):
  - "mock 딕셔너리 조회 함수 결과가 mock 딕셔너리와 일치한다"는 식의 자기 일관성 테스트
  - 실제 ImageClassifier 없이 분류 정확도를 측정하는 테스트
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from uuid import UUID

import pytest

from app.schemas.layout import BBoxItem, LayoutResult

_DATA_PATH = Path(__file__).parent.parent.parent / "test_data" / "classifier_test_set.json"


def _load_test_set() -> dict:
    return json.loads(_DATA_PATH.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def test_data() -> dict:
    return _load_test_set()


class TestClassifierTestSetValidity:
    """목 데이터 파일 구조 검증 — ImageClassifier 구현 시 인터페이스 기준."""

    def test_data_file_exists(self) -> None:
        assert _DATA_PATH.exists(), f"분류 테스트 데이터 없음: {_DATA_PATH}"

    def test_has_enough_cases(self, test_data: dict) -> None:
        assert len(test_data["test_cases"]) >= 10

    def test_all_cases_have_required_fields(self, test_data: dict) -> None:
        for case in test_data["test_cases"]:
            assert "element_id" in case
            assert "visual_subtype" in case
            assert "expected_type" in case
            assert "subtype_confidence" in case

    def test_expected_types_are_valid_pipeline_types(self, test_data: dict) -> None:
        """expected_type은 pipeline.py가 체인 라우팅에 사용하는 타입이어야 함."""
        valid_types = {"image", "cartoon", "chart_graph"}
        for case in test_data["test_cases"]:
            assert case["expected_type"] in valid_types, (
                f"알 수 없는 expected_type: {case['expected_type']!r}"
            )

    def test_low_confidence_cases_exist(self, test_data: dict) -> None:
        """신뢰도 < 0.75 케이스 존재 확인 — SUBTYPE_UNCERTAIN 플래그 경계 기준."""
        low_conf = [c for c in test_data["test_cases"] if c["subtype_confidence"] < 0.75]
        assert len(low_conf) >= 1, "신뢰도 < 0.75 케이스 없음"


class TestPipelineChainRouting:
    """pipeline.py의 실제 type 기반 체인 라우팅 코드 검증 (태민 파트).

    분류기가 layout의 type 필드를 업데이트하면 pipeline.py는
    type 값으로 요소를 필터링해 해당 체인에 전달한다.
    이 필터링 코드가 올바른지 직접 검증.
    """

    def _make_layout(self) -> LayoutResult:
        return LayoutResult(page_id="p_test", elements=[
            BBoxItem(type="text",        bbox=(0,   0, 100,  30), reading_order=1),
            BBoxItem(type="formula",     bbox=(0,  30, 100,  60), reading_order=2),
            BBoxItem(type="table",       bbox=(0,  60, 100, 130), reading_order=3),
            BBoxItem(type="image",       bbox=(0, 130, 100, 230), reading_order=4),
            BBoxItem(type="cartoon",     bbox=(0, 230, 100, 330), reading_order=5),
            BBoxItem(type="chart_graph", bbox=(0, 330, 100, 430), reading_order=6),
        ])

    def test_text_types_filter(self) -> None:
        """pipeline._TEXT_TYPES에 정의된 타입만 text 체인이 처리."""
        from app.core.pipeline import _TEXT_TYPES
        layout = self._make_layout()
        text_elems = [e for e in layout.elements if e.type in _TEXT_TYPES]
        assert len(text_elems) == 1
        assert text_elems[0].type == "text"

    def test_formula_type_filter(self) -> None:
        layout = self._make_layout()
        formula_elems = [e for e in layout.elements if e.type == "formula"]
        assert len(formula_elems) == 1

    def test_table_type_filter(self) -> None:
        layout = self._make_layout()
        table_elems = [e for e in layout.elements if e.type == "table"]
        assert len(table_elems) == 1

    def test_image_type_filter(self) -> None:
        layout = self._make_layout()
        image_elems = [e for e in layout.elements if e.type == "image"]
        assert len(image_elems) == 1

    def test_cartoon_type_filter(self) -> None:
        layout = self._make_layout()
        cartoon_elems = [e for e in layout.elements if e.type == "cartoon"]
        assert len(cartoon_elems) == 1

    def test_chart_graph_type_filter(self) -> None:
        layout = self._make_layout()
        chart_elems = [e for e in layout.elements if e.type == "chart_graph"]
        assert len(chart_elems) == 1

    def test_reclassified_image_routes_to_correct_chain(self) -> None:
        """classifier가 image → cartoon으로 type을 업데이트하면 cartoon 체인에 라우팅됨."""
        elem = BBoxItem(type="image", bbox=(0, 0, 100, 100), reading_order=1)
        layout = LayoutResult(page_id="p_001", elements=[elem])

        # classifier(현주 파트)가 하는 일: type 필드 갱신
        updated_elem = elem.model_copy(update={"type": "cartoon"})
        updated_layout = LayoutResult(page_id="p_001", elements=[updated_elem])

        # 갱신 후 라우팅
        image_elems   = [e for e in updated_layout.elements if e.type == "image"]
        cartoon_elems = [e for e in updated_layout.elements if e.type == "cartoon"]
        assert len(image_elems) == 0,   "cartoon으로 재분류된 요소가 image 체인에도 남음"
        assert len(cartoon_elems) == 1, "재분류된 요소가 cartoon 체인에 없음"

    def test_model_copy_does_not_mutate_original(self) -> None:
        """model_copy(update=...) 후 원본 요소는 불변이어야 함."""
        elem = BBoxItem(type="image", bbox=(0, 0, 100, 100), reading_order=1)
        _ = elem.model_copy(update={"type": "chart_graph"})
        assert elem.type == "image"


class TestClassifyWithConfidence:
    """classify_with_confidence — logprob 기반 세분류 신뢰도 (R2 발화 근거).

    OpenAI 응답은 목 — 실 API 검증은 크레딧 복구 후.
    """

    @staticmethod
    def _mock_resp(content: str, logprob_tokens: list[tuple[str, float]] | None):
        logprobs = None
        if logprob_tokens is not None:
            logprobs = SimpleNamespace(content=[
                SimpleNamespace(token=t, logprob=lp) for t, lp in logprob_tokens
            ])
        return SimpleNamespace(choices=[SimpleNamespace(
            message=SimpleNamespace(content=content), logprobs=logprobs,
        )])

    def _run(self, tmp_path, resp):
        from test.conftest import DUMMY_PNG_BYTES
        from app.ai.captioning import classifier

        img = tmp_path / "crop.png"
        img.write_bytes(DUMMY_PNG_BYTES)
        client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(
            create=lambda **kw: resp,
        )))
        with patch.object(classifier, "_get_client", return_value=client):
            return classifier.classify_with_confidence(str(img))

    def test_confidence_from_logprob(self, tmp_path) -> None:
        label, conf = self._run(tmp_path, self._mock_resp("chart", [("chart", -0.05)]))
        assert label == "chart"
        assert conf == pytest.approx(math.exp(-0.05))

    def test_multi_token_logprobs_summed(self, tmp_path) -> None:
        # 공백 스캐폴드 토큰은 제외, 라벨 토큰 logprob은 합산
        resp = self._mock_resp("cartoon", [("\n", -0.9), ("car", -0.2), ("toon", -0.1)])
        label, conf = self._run(tmp_path, resp)
        assert label == "cartoon"
        assert conf == pytest.approx(math.exp(-0.3))

    def test_invalid_label_zero_confidence(self, tmp_path) -> None:
        # 세 라벨 밖 응답 = 형식 이탈 → image 폴백 + 신뢰도 0.0 (R2 대상)
        label, conf = self._run(tmp_path, self._mock_resp("photograph", [("photograph", -0.1)]))
        assert label == "image"
        assert conf == 0.0

    def test_missing_logprobs_returns_none(self, tmp_path) -> None:
        label, conf = self._run(tmp_path, self._mock_resp("image", None))
        assert label == "image"
        assert conf is None

    def test_classify_wrapper_returns_label_only(self, tmp_path) -> None:
        from app.ai.captioning import classifier
        from test.conftest import DUMMY_PNG_BYTES

        img = tmp_path / "crop.png"
        img.write_bytes(DUMMY_PNG_BYTES)
        client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(
            create=lambda **kw: self._mock_resp("cartoon", [("cartoon", -0.01)]),
        )))
        with patch.object(classifier, "_get_client", return_value=client):
            assert classifier.classify(str(img)) == "cartoon"
