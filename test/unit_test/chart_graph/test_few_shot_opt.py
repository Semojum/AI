"""점역자 주 최적화 few-shot 예시 검증 — 형식 규칙 단위 테스트.

few_shot_examples.json의 각 예시가 §5.3 / §6.3.4 / §6.4 규정 형식 요건을
만족하는지 검증하고, _verify_numbers() 함수의 수치 그라운딩 로직을 검증한다.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pytest

from app.ai.llm.chart_graph_opt import _verify_numbers

_FEW_SHOT_PATH = Path(__file__).parent.parent.parent / "test_data" / "few_shot_examples.json"

_CHART_TYPES = {"막대그래프", "꺾은선그래프", "비율그래프", "선그래프", "그림그래프", "수직선"}
_IMAGE_TYPES = {"사진", "그림", "삽화", "지도", "도표", "도형"}


def _load_examples() -> list[dict[str, Any]]:
    return json.loads(_FEW_SHOT_PATH.read_text(encoding="utf-8"))["examples"]


@pytest.fixture(scope="module")
def few_shot_examples() -> list[dict[str, Any]]:
    return _load_examples()


class TestFewShotFileIntegrity:

    def test_file_exists(self) -> None:
        assert _FEW_SHOT_PATH.exists(), f"few_shot_examples.json 없음: {_FEW_SHOT_PATH}"

    def test_has_examples_key(self) -> None:
        data = json.loads(_FEW_SHOT_PATH.read_text(encoding="utf-8"))
        assert "examples" in data
        assert len(data["examples"]) >= 3

    def test_all_required_fields(self, few_shot_examples: list[dict[str, Any]]) -> None:
        required = {"id", "opt_type", "input_caption", "expected_output", "rule_refs"}
        for ex in few_shot_examples:
            missing = required - ex.keys()
            assert not missing, f"id={ex.get('id')}: 필수 필드 누락 {missing}"

    def test_opt_type_values(self, few_shot_examples: list[dict[str, Any]]) -> None:
        valid = {"image", "cartoon", "chart_graph"}
        for ex in few_shot_examples:
            assert ex["opt_type"] in valid, f"id={ex['id']}: opt_type 오류 '{ex['opt_type']}'"

    def test_all_three_types_covered(self, few_shot_examples: list[dict[str, Any]]) -> None:
        types = {ex["opt_type"] for ex in few_shot_examples}
        assert "image" in types, "image 예시 없음"
        assert "cartoon" in types, "cartoon 예시 없음"
        assert "chart_graph" in types, "chart_graph 예시 없음"


class TestExpectedOutputFormat:
    """모든 expected_output이 §6.3.4 형식 요건을 만족하는지 검증."""

    def test_all_start_with_jyeoksa_tag(self, few_shot_examples: list[dict[str, Any]]) -> None:
        for ex in few_shot_examples:
            output = ex["expected_output"]
            assert output.startswith("[점역사주]"), (
                f"id={ex['id']}: [점역사주] 미시작 — {output[:30]}"
            )

    def test_chart_outputs_contain_valid_type(self, few_shot_examples: list[dict[str, Any]]) -> None:
        for ex in few_shot_examples:
            if ex["opt_type"] != "chart_graph":
                continue
            output = ex["expected_output"]
            prefix = output.replace("[점역사주]", "").strip()
            has_type = any(t in prefix for t in _CHART_TYPES)
            assert has_type, f"id={ex['id']}: 그래프 유형 미명시 — {prefix[:40]}"

    def test_image_outputs_contain_valid_type(self, few_shot_examples: list[dict[str, Any]]) -> None:
        for ex in few_shot_examples:
            if ex["opt_type"] != "image":
                continue
            output = ex["expected_output"]
            has_type = any(t in output for t in _IMAGE_TYPES | _CHART_TYPES)
            assert has_type, f"id={ex['id']}: 시각자료 유형 미명시 — {output[:40]}"

    def test_cartoon_outputs_contain_manhwa_keyword(self, few_shot_examples: list[dict[str, Any]]) -> None:
        for ex in few_shot_examples:
            if ex["opt_type"] != "cartoon":
                continue
            output = ex["expected_output"]
            assert "만화" in output, f"id={ex['id']}: '만화' 키워드 없음 — {output[:40]}"

    def test_cartoon_no_double_quotes_in_dialogue(self, few_shot_examples: list[dict[str, Any]]) -> None:
        for ex in few_shot_examples:
            if ex["opt_type"] != "cartoon":
                continue
            output = ex["expected_output"]
            assert '"' not in output and '“' not in output and '”' not in output, (
                f"id={ex['id']}: 만화 대사에 따옴표 사용 금지 — {output}"
            )

    def test_chart_numbers_preserved(self, few_shot_examples: list[dict[str, Any]]) -> None:
        for ex in few_shot_examples:
            if ex["opt_type"] != "chart_graph":
                continue
            assert _verify_numbers(ex["input_caption"], ex["expected_output"]), (
                f"id={ex['id']}: 원본 수치가 출력에 없음 (R5 기준 실패)"
            )

    def test_arabic_numerals_not_converted_to_korean(self, few_shot_examples: list[dict[str, Any]]) -> None:
        # 아라비아 숫자 변환 금지 검증: 입력의 숫자가 출력에서도 아라비아 숫자로 유지되는지
        # _verify_numbers가 이미 수치 존재 여부를 검증하므로, 여기서는 100→백/1000→천 패턴만 확인
        # 예: 입력에 "100"이 있고 출력에 "100"이 없으면서 "백"이 있으면 변환 의심
        numeral_map = {r"\b100\b": "백", r"\b1000\b": "천", r"\b10000\b": "만"}
        for ex in few_shot_examples:
            inp = ex["input_caption"]
            out = ex["expected_output"]
            for pattern, korean in numeral_map.items():
                if re.search(pattern, inp) and not re.search(pattern, out):
                    # 출력에 해당 숫자가 없는데 한글 수사로 시작하는 단어가 있으면 의심
                    assert korean not in out or re.search(r"\d" + korean, out), (
                        f"id={ex['id']}: {pattern}→'{korean}' 변환 의심"
                    )


class TestVerifyNumbers:
    """_verify_numbers() 수치 그라운딩 함수 단위 검증."""

    def test_all_numbers_present(self) -> None:
        assert _verify_numbers("62%, 21.6%, 5.5%", "[점역사주] 비율그래프: 62%, 21.6%, 5.5%")

    def test_missing_number_returns_false(self) -> None:
        assert not _verify_numbers("62%, 21.6%", "[점역사주] 비율그래프: 62%")

    def test_decimal_numbers_matched(self) -> None:
        assert _verify_numbers("1,103백만 1,395 1,592", "1,103 1,395 1,592")

    def test_no_numbers_in_original_always_passes(self) -> None:
        assert _verify_numbers("만화 장면 설명", "[점역사주] 만화: 장면 설명")

    def test_subset_passes_superset_fails(self) -> None:
        original = "39 16 46"
        assert _verify_numbers(original, "39 16 46 28 65 5")
        assert not _verify_numbers(original + " 99", "39 16 46")

    def test_integer_within_decimal_counts(self) -> None:
        # 원본에 "5"가 있으면 "5.5"에서도 추출된 "5"로 매칭 — 세트 비교이므로 OK
        assert _verify_numbers("5%", "5.5% and 5%")
