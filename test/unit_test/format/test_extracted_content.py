"""text_ocr.json / formula_ocr.json 파일이 ExtractedContent 스키마를 충족하는지 검증."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.schemas.content import ExtractedContent

_DATA = Path(__file__).parent.parent.parent / "test_data" / "page_001"


class TestTextOcrJson:

    @pytest.fixture(scope="class")
    def items(self):
        raw = json.loads((_DATA / "type" / "text" / "text_ocr.json").read_text(encoding="utf-8"))
        return [ExtractedContent.model_validate(d) for d in raw]

    def test_deserializes_minimum_10(self, items):
        assert len(items) >= 10

    def test_corrected_text_present(self, items):
        assert all(i.corrected_text is not None for i in items)

    def test_latex_string_absent(self, items):
        assert all(i.latex_string is None for i in items)

    def test_ocr_confidence_in_range(self, items):
        assert all(0.0 <= i.ocr_confidence <= 1.0 for i in items)

    def test_flags_is_list_of_str(self, items):
        for i in items:
            assert isinstance(i.flags, list)
            assert all(isinstance(f, str) for f in i.flags)


class TestFormulaOcrJson:

    @pytest.fixture(scope="class")
    def items(self):
        raw = json.loads((_DATA / "type" / "formula" / "formula_ocr.json").read_text(encoding="utf-8"))
        return [ExtractedContent.model_validate(d) for d in raw]

    def test_deserializes_minimum_5(self, items):
        assert len(items) >= 5

    def test_latex_string_present(self, items):
        assert all(i.latex_string is not None for i in items)

    def test_corrected_text_absent(self, items):
        assert all(i.corrected_text is None for i in items)

    def test_ocr_confidence_in_range(self, items):
        assert all(0.0 <= i.ocr_confidence <= 1.0 for i in items)

    def test_flags_is_list_of_str(self, items):
        for i in items:
            assert isinstance(i.flags, list)
            assert all(isinstance(f, str) for f in i.flags)
