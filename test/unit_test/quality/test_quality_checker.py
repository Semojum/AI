"""PART 11 QualityChecker — C1~C6 감지·R 플래그·status 결정 규칙(plan §4-1).

기대값은 plan V2_기술명세서 §4-1 status 표에서 수동 도출(순환검증 금지).
"""
from uuid import uuid4

from app.ai.quality.quality_checker import (
    C6_OVERFLOW_THRESHOLD,
    QualityChecker,
    R1_CONFIDENCE_THRESHOLD,
)
from app.schemas.content import BrailleOutput, ExtractedContent, LLMOutput
from app.schemas.layout import BBoxItem, LayoutResult


def _layout(n: int) -> tuple[LayoutResult, list]:
    items = [
        BBoxItem(element_id=uuid4(), type="text", bbox=(0, 0, 10, 10), reading_order=i + 1)
        for i in range(n)
    ]
    return LayoutResult(page_id="p_001", elements=items), [b.element_id for b in items]


def _llm(eid, text="정상 텍스트"):
    return LLMOutput(element_id=eid, corrected_text=text, render_mode="text_only",
                     routing_tier="ZERO", processing_time_ms=0)


def _ext(eid, conf=1.0, flags=None):
    return ExtractedContent(element_id=eid, corrected_text="원문", ocr_confidence=conf,
                            flags=flags or [])


class TestStatusDecision:
    def test_clean_page_completed(self):
        layout, ids = _layout(2)
        report = QualityChecker().check(
            "p_001", layout_result=layout,
            extracted=[_ext(i) for i in ids],
            llm_outputs=[_llm(i) for i in ids],
        )
        assert report.status == "COMPLETED"
        assert report.critical_errors == []
        assert report.review_flags == []

    def test_c2_placeholder_needs_review(self):
        layout, ids = _layout(2)
        outputs = [_llm(ids[0]), _llm(ids[1], "[처리 불가: fallback_failed]")]
        report = QualityChecker().check(
            "p_001", layout_result=layout,
            extracted=[_ext(i) for i in ids], llm_outputs=outputs,
        )
        assert report.status == "NEEDS_REVIEW"
        assert [c.type for c in report.critical_errors] == ["C2"]
        assert report.critical_errors[0].element_id == str(ids[1])

    def test_c3_formula_placeholder(self):
        layout, ids = _layout(2)
        outputs = [_llm(ids[0]), _llm(ids[1], "[수식 재확인 필요]")]
        report = QualityChecker().check("p_001", layout_result=layout,
                                        llm_outputs=outputs)
        assert report.status == "NEEDS_REVIEW"
        assert [c.type for c in report.critical_errors] == ["C3"]

    def test_c4_table_placeholder(self):
        layout, ids = _layout(2)
        outputs = [_llm(ids[0]), _llm(ids[1], "[표 수동 입력 필요]")]
        report = QualityChecker().check("p_001", layout_result=layout,
                                        llm_outputs=outputs)
        assert report.status == "NEEDS_REVIEW"
        assert [c.type for c in report.critical_errors] == ["C4"]

    def test_c1_all_elements_blocked(self):
        layout, ids = _layout(2)
        outputs = [_llm(i, "[처리 불가: OCR 실패]") for i in ids]
        report = QualityChecker().check("p_001", layout_result=layout,
                                        llm_outputs=outputs)
        assert report.status == "BLOCKED"
        assert any(c.type == "C1" for c in report.critical_errors)

    def test_c1_empty_extraction(self):
        # MinerU 실패 격리 → 요소 0개: 페이지 전체 실패
        report = QualityChecker().check(
            "p_001", layout_result=LayoutResult(page_id="p_001", elements=[]),
        )
        assert report.status == "BLOCKED"
        assert [c.type for c in report.critical_errors] == ["C1"]

    def test_c1_elements_but_no_output(self):
        layout, _ = _layout(3)
        report = QualityChecker().check("p_001", layout_result=layout, llm_outputs=[])
        assert report.status == "BLOCKED"

    def test_c6_overflow(self):
        layout, ids = _layout(1)
        report = QualityChecker().check(
            "p_001", layout_result=layout, llm_outputs=[_llm(ids[0])],
            line_overflow_rate=C6_OVERFLOW_THRESHOLD + 0.01,
        )
        assert report.status == "NEEDS_REVIEW"
        assert [c.type for c in report.critical_errors] == ["C6"]
        # 임계 이하이면 미발생
        ok = QualityChecker().check(
            "p_001", layout_result=layout, llm_outputs=[_llm(ids[0])],
            line_overflow_rate=C6_OVERFLOW_THRESHOLD,
        )
        assert ok.status == "COMPLETED"


class TestReviewFlags:
    def test_r1_low_confidence(self):
        layout, ids = _layout(1)
        report = QualityChecker().check(
            "p_001", layout_result=layout,
            extracted=[_ext(ids[0], conf=R1_CONFIDENCE_THRESHOLD - 0.1)],
            llm_outputs=[_llm(ids[0])],
        )
        assert report.status == "NEEDS_REVIEW"
        assert [r.type for r in report.review_flags] == ["R1"]

    def test_r5_flag_passthrough(self):
        layout, ids = _layout(1)
        report = QualityChecker().check(
            "p_001", layout_result=layout,
            extracted=[_ext(ids[0], flags=["R5"])],
            llm_outputs=[_llm(ids[0])],
        )
        assert report.status == "NEEDS_REVIEW"
        assert [r.type for r in report.review_flags] == ["R5"]

    def test_subtype_uncertain_maps_r2(self):
        layout, ids = _layout(1)
        report = QualityChecker().check(
            "p_001", layout_result=layout,
            extracted=[_ext(ids[0], flags=["SUBTYPE_UNCERTAIN"])],
            llm_outputs=[_llm(ids[0])],
        )
        assert [r.type for r in report.review_flags] == ["R2"]

    def test_unknown_flag_ignored(self):
        layout, ids = _layout(1)
        report = QualityChecker().check(
            "p_001", layout_result=layout,
            extracted=[_ext(ids[0], flags=["SOMETHING_ELSE"])],
            llm_outputs=[_llm(ids[0])],
        )
        assert report.status == "COMPLETED"


class TestBrailleFailure:
    def test_braille_only_failure_is_c2(self):
        layout, ids = _layout(1)
        report = QualityChecker().check(
            "p_001", layout_result=layout,
            llm_outputs=[_llm(ids[0])],
            braille_outputs=[BrailleOutput(
                element_id=ids[0], braille_lines=["[처리 불가: 점역 오류]"],
            )],
        )
        assert report.status == "NEEDS_REVIEW"
        assert [c.type for c in report.critical_errors] == ["C2"]

    def test_no_double_count_with_opt_placeholder(self):
        layout, ids = _layout(1)
        report = QualityChecker().check(
            "p_001", layout_result=layout,
            llm_outputs=[_llm(ids[0], "[처리 불가: OCR 실패]")],
            braille_outputs=[BrailleOutput(
                element_id=ids[0], braille_lines=["[처리 불가: 점역 오류]"],
            )],
        )
        # 같은 요소는 C 1건만 (opt 단계에서 이미 감지)
        assert len([c for c in report.critical_errors if c.element_id == str(ids[0])]) == 1


class TestReportFields:
    def test_ocr_confidence_avg(self):
        layout, ids = _layout(2)
        report = QualityChecker().check(
            "p_001", layout_result=layout,
            extracted=[_ext(ids[0], conf=0.9), _ext(ids[1], conf=1.0)],
            llm_outputs=[_llm(i) for i in ids],
        )
        assert abs(report.ocr_confidence_avg - 0.95) < 1e-9
        assert report.page_id == "p_001"
