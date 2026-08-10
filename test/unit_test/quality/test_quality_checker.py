"""PART 11 QualityChecker — C1~C6 감지·R 플래그·status 결정 규칙(plan §4-1).

기대값은 plan V2_기술명세서 §4-1 status 표에서 수동 도출(순환검증 금지).
"""
from uuid import uuid4

from app.ai.quality.quality_checker import (
    C6_OVERFLOW_THRESHOLD,
    QualityChecker,
    R1_CONFIDENCE_THRESHOLD,
    R2_SUBTYPE_CONFIDENCE_THRESHOLD,
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


def _ext(eid, conf=1.0, flags=None, visual_subtype=None, subtype_confidence=None):
    return ExtractedContent(element_id=eid, corrected_text="원문", ocr_confidence=conf,
                            visual_subtype=visual_subtype,
                            subtype_confidence=subtype_confidence,
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


class TestC5RuntimeScanner:
    """C5 2차 방어선: 원문에 아라비아 숫자가 있는데 요소 점자에 수표(⠼)가 0개면 C5.

    기대값 근거: 한국 점자 규정 제43항 — 숫자는 수표(⠼)를 앞세운다. 3 = ⠼⠉.
    """

    def test_missing_number_indicator_is_c5(self):
        layout, ids = _layout(1)
        report = QualityChecker().check(
            "p_001", layout_result=layout,
            extracted=[_ext(ids[0])],
            llm_outputs=[_llm(ids[0], "정답은 3번")],
            # ⠼ 없이 숫자 점형만 (수표 누락 회귀 상황)
            braille_outputs=[BrailleOutput(element_id=ids[0], braille_lines=["⠨⠻⠊⠣⠃⠵⠀⠉⠘⠞"])],
        )
        assert report.status == "NEEDS_REVIEW"
        assert [c.type for c in report.critical_errors] == ["C5"]
        assert report.critical_errors[0].element_id == str(ids[0])

    def test_number_indicator_present_no_c5(self):
        layout, ids = _layout(1)
        report = QualityChecker().check(
            "p_001", layout_result=layout,
            extracted=[_ext(ids[0])],
            llm_outputs=[_llm(ids[0], "정답은 3번")],
            braille_outputs=[BrailleOutput(element_id=ids[0], braille_lines=["⠨⠻⠊⠣⠃⠵⠀⠼⠉⠘⠞"])],
        )
        assert report.status == "COMPLETED"

    def test_no_digits_no_c5(self):
        layout, ids = _layout(1)
        report = QualityChecker().check(
            "p_001", layout_result=layout,
            extracted=[_ext(ids[0])],
            llm_outputs=[_llm(ids[0], "숫자 없는 문장")],
            braille_outputs=[BrailleOutput(element_id=ids[0], braille_lines=["⠁⠃⠉"])],
        )
        assert report.status == "COMPLETED"

    def test_visual_element_exempt(self):
        # 시각자료 초안은 LLM 생성이라 수치가 정당하게 요약·생략될 수 있음(R5 소관) → C5 제외
        layout, ids = _layout(1)
        report = QualityChecker().check(
            "p_001", layout_result=layout,
            extracted=[_ext(ids[0], visual_subtype="chart_graph")],
            llm_outputs=[_llm(ids[0], "1990년 30% 상승 그래프")],
            braille_outputs=[BrailleOutput(element_id=ids[0], braille_lines=["⠠⠄⠈⠪⠐⠗⠘⠪⠠⠄"])],
        )
        assert not any(c.type == "C5" for c in report.critical_errors)

    def test_empty_braille_skipped(self):
        # 점역 출력 자체가 없으면 C5가 아니라 상위 실패(C1/C2) 신호의 소관
        layout, ids = _layout(1)
        report = QualityChecker().check(
            "p_001", layout_result=layout,
            extracted=[_ext(ids[0])],
            llm_outputs=[_llm(ids[0], "정답은 3번")],
            braille_outputs=[BrailleOutput(element_id=ids[0], braille_lines=[])],
        )
        assert not any(c.type == "C5" for c in report.critical_errors)

    def test_english_contraction_does_not_mask_missing_number_sign(self):
        """★ 회귀 가드 — 영어 약자 ble의 ⠼가 수표 자리를 대신 채우면 안 된다.

        ⠼(3456점)는 수표(제40항)이자 EBAE 영어 약자 'ble'이다. `possible`은 ⠏⠕⠎⠎⠊⠼로
        적히므로 "⠼가 하나라도 있으면 통과"로 세면 **진짜 수표 누락을 못 잡는다**.
        기대 점형 근거: 제40항(1911행) 숫자는 수표를 앞세운다 → 3 = ⠼⠉.
        아래 점자에는 3의 수표가 없고 ble의 ⠼만 있으므로 C5여야 한다.
        """
        layout, ids = _layout(1)
        report = QualityChecker().check(
            "p_001", layout_result=layout,
            extracted=[_ext(ids[0])],
            llm_outputs=[_llm(ids[0], "possible 한 3가지")],
            # ⠴⠏⠕⠎⠎⠊⠼⠲ = possible(끝 ⠼ = ble) + 종료표, 그 뒤 3은 수표 없이 ⠉만
            braille_outputs=[BrailleOutput(
                element_id=ids[0], braille_lines=["⠴⠏⠕⠎⠎⠊⠼⠲⠀⠚⠒⠀⠉⠫⠨⠕"])],
        )
        assert [c.type for c in report.critical_errors] == ["C5"]

    def test_english_contraction_plus_real_number_sign_no_c5(self):
        """반대 방향 — ble의 ⠼와 진짜 수표가 함께 있으면 C5가 아니다(오탐 금지)."""
        layout, ids = _layout(1)
        report = QualityChecker().check(
            "p_001", layout_result=layout,
            extracted=[_ext(ids[0])],
            llm_outputs=[_llm(ids[0], "possible 한 3가지")],
            braille_outputs=[BrailleOutput(
                element_id=ids[0], braille_lines=["⠴⠏⠕⠎⠎⠊⠼⠲⠀⠚⠒⠀⠼⠉⠫⠨⠕"])],
        )
        assert not any(c.type == "C5" for c in report.critical_errors)

    def test_ble_followed_by_digit_cell_still_caught(self):
        """잔여 모호형(-bled처럼 ble 뒤 글자가 a~j)도 원문 낱말로 세어 잡는다.

        `assembled` = ⠁⠎⠎⠑⠍⠼⠙ — ⠼ 뒤 ⠙는 숫자 4의 셀과 같아 점형만으로는 수표와
        구별되지 않는다. 원문에 그 낱말이 있으므로 수표 후보에서 뺀다.
        """
        layout, ids = _layout(1)
        report = QualityChecker().check(
            "p_001", layout_result=layout,
            extracted=[_ext(ids[0])],
            llm_outputs=[_llm(ids[0], "assembled 부품 2개")],
            braille_outputs=[BrailleOutput(
                element_id=ids[0], braille_lines=["⠴⠁⠎⠎⠑⠍⠼⠙⠲⠀⠘⠍⠙⠍⠢⠀⠃⠈⠗"])],
        )
        assert [c.type for c in report.critical_errors] == ["C5"]

    def test_blocked_element_not_double_flagged(self):
        layout, ids = _layout(2)
        report = QualityChecker().check(
            "p_001", layout_result=layout,
            extracted=[_ext(i) for i in ids],
            llm_outputs=[_llm(ids[0], "[처리 불가: OCR 실패] 3번"), _llm(ids[1])],
            braille_outputs=[BrailleOutput(element_id=ids[0], braille_lines=["⠁⠃⠉"])],
        )
        # placeholder C2만 — 같은 요소에 C5 중복 없음
        elem_criticals = [c for c in report.critical_errors if c.element_id == str(ids[0])]
        assert [c.type for c in elem_criticals] == ["C2"]


class TestR2SubtypeConfidence:
    """R2: classifier logprob 신뢰도 < 0.75 → 세분류 불확실 검토 플래그."""

    def test_low_confidence_fires_r2(self):
        layout, ids = _layout(1)
        report = QualityChecker().check(
            "p_001", layout_result=layout,
            extracted=[_ext(ids[0], visual_subtype="cartoon",
                            subtype_confidence=R2_SUBTYPE_CONFIDENCE_THRESHOLD - 0.1)],
            llm_outputs=[_llm(ids[0])],
        )
        assert report.status == "NEEDS_REVIEW"
        assert [r.type for r in report.review_flags] == ["R2"]

    def test_high_confidence_no_r2(self):
        layout, ids = _layout(1)
        report = QualityChecker().check(
            "p_001", layout_result=layout,
            extracted=[_ext(ids[0], visual_subtype="cartoon", subtype_confidence=0.98)],
            llm_outputs=[_llm(ids[0])],
        )
        assert report.status == "COMPLETED"

    def test_none_confidence_no_r2(self):
        # logprobs 미제공 → 판단 불가, 플래그 안 띄움 (기존 동작 보존)
        layout, ids = _layout(1)
        report = QualityChecker().check(
            "p_001", layout_result=layout,
            extracted=[_ext(ids[0], visual_subtype="image", subtype_confidence=None)],
            llm_outputs=[_llm(ids[0])],
        )
        assert report.status == "COMPLETED"

    def test_flag_and_confidence_no_duplicate_r2(self):
        # 경계 파일 플래그 + 낮은 신뢰도 동시 → R2는 1건만
        layout, ids = _layout(1)
        report = QualityChecker().check(
            "p_001", layout_result=layout,
            extracted=[_ext(ids[0], flags=["SUBTYPE_UNCERTAIN"], visual_subtype="image",
                            subtype_confidence=0.5)],
            llm_outputs=[_llm(ids[0])],
        )
        assert [r.type for r in report.review_flags] == ["R2"]


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


class TestLostGlyphFlag:
    """글자 소실(폰트 cmap 파손) → R1 (2026-08-02).

    일부 교과서 PDF는 텍스트 레이어에 제어문자가 글자 자리를 대신 차지한다
    (실측 코퍼스 1,131쪽에서 277요소·352자·126쪽). sanitize_for_braille가 점역 전에
    지우므로 쓰레기가 나가진 않지만 **글자가 조용히 사라진다** — 점역사에게 알려야 한다.
    """

    def _ext(self, text):
        import uuid
        from app.schemas.content import ExtractedContent
        return ExtractedContent(element_id=str(uuid.uuid4()), corrected_text=text,
                                ocr_confidence=0.99)

    def _flags(self, text):
        from app.ai.quality.quality_checker import QualityChecker
        rep = QualityChecker().check("p1", layout_result=None, extracted=[self._ext(text)],
                                     llm_outputs=[], braille_outputs=[], line_overflow_rate=0.0)
        return [f for f in rep.review_flags if "글자 소실" in f.message]

    def test_제어문자가_있으면_R1(self):
        f = self._flags("**\x08국 인구는 \x03\x06\x04\x06년까지 증가")
        assert len(f) == 1 and f[0].type == "R1"
        assert "5자" in f[0].message          # \x08 + \x03\x06\x04\x06 = 5자

    def test_정상_텍스트는_발화하지_않는다(self):
        assert self._flags("한국 인구는 2020년까지 증가하였다.") == []

    def test_줄바꿈_탭은_글자_소실이_아니다(self):
        # \n·\t·\r은 정상 서식 문자다 — 여기 걸리면 거의 모든 요소가 오탐이 된다.
        assert self._flags("첫 줄\n둘째 줄\t셋째\r넷째") == []

    def test_신뢰도가_높아도_발화한다(self):
        # 이 요소들은 ocr_confidence가 높게 잡혀 R1 임계(0.85)에 안 걸린다.
        assert len(self._flags("가\x00나")) == 1


class TestC5TagDigitFalsePositive:
    """C5 게이트는 **점역 대상 글자**에만 열린다 (2026-08-10).

    실측(dev+val 839쪽): C5 146건 중 142건(97.3%)이 인라인 태그 이름의 숫자로 열린
    오탐이었다. `<!테두리_아래2>`의 '2'는 테두리 점형으로 치환되니 수표가 나올 수 없다.
    C5는 배포 블로커 신호라 오탐이 쌓이면 제일 중요한 플래그부터 무시하게 된다.
    """

    def _report(self, text, cells):
        layout, ids = _layout(1)
        return QualityChecker().check(
            "p_001", layout_result=layout, extracted=[_ext(ids[0])],
            llm_outputs=[_llm(ids[0], text)],
            braille_outputs=[BrailleOutput(element_id=ids[0], braille_lines=[cells])],
        )

    def test_태그_이름의_숫자는_게이트를_안_연다(self):
        rep = self._report("ㄷ. 소득 분포를 고려하지 않는다.\n<!테두리_아래2><!/테두리_아래2>",
                           "⠇⠚⠽⠀⠿⠶⠶⠶")
        assert not any(c.type == "C5" for c in rep.critical_errors)

    def test_원문자는_수표가_아니라_게이트를_안_연다(self):
        # 제64항 원문자(⠼+내린 숫자)는 수표로 세지 않는다 — number_sign.py 주석.
        rep = self._report(r"세포 $\textcircled{7}$ 상대량", "⠠⠗⠙⠥⠀⠼⠒")
        assert not any(c.type == "C5" for c in rep.critical_errors)

    def test_태그가_있어도_본문_숫자_누락은_잡는다(self):
        rep = self._report("<!테두리_위2><!/테두리_위2>\n정답은 3번", "⠿⠛⠛⠀⠨⠻⠊⠣⠃⠵⠀⠉⠘⠞")
        assert [c.type for c in rep.critical_errors] == ["C5"]


class TestVisualAndTableFlags:
    """AI가 쓴 시각자료 설명(R11)·표(R10) — 2026-08-10 추가.

    근거(dev+val 839쪽, gold 대비 셀 편집): 시각 요소는 80~94%가 크게 틀리고(쪽 평균
    33.2%), 표는 98.7%가 편집을 필요로 하는데 종전 플래그율이 각각 5%·0.8%였다.
    """

    def _layout_typed(self, *types):
        items = [BBoxItem(element_id=uuid4(), type=t, bbox=(0, 0, 10, 10), reading_order=i + 1)
                 for i, t in enumerate(types)]
        return LayoutResult(page_id="p_001", elements=items), [b.element_id for b in items]

    def test_캡셔닝_성공한_시각자료도_R11(self):
        layout, ids = self._layout_typed("image")
        rep = QualityChecker().check("p_001", layout_result=layout,
                                     extracted=[_ext(ids[0])], llm_outputs=[_llm(ids[0])])
        assert [r.type for r in rep.review_flags] == ["R11"]
        assert "AI가 쓴" in rep.review_flags[0].message

    def test_캡셔닝_실패는_R11_한_번만(self):
        layout, ids = self._layout_typed("image")
        rep = QualityChecker().check("p_001", layout_result=layout,
                                     extracted=[_ext(ids[0], flags=["CAPTION_FAILED"])],
                                     llm_outputs=[_llm(ids[0])])
        assert [r.type for r in rep.review_flags] == ["R11"]
        assert "직접 작성" in rep.review_flags[0].message

    def test_표는_R10(self):
        layout, ids = self._layout_typed("table")
        rep = QualityChecker().check("p_001", layout_result=layout,
                                     extracted=[_ext(ids[0])], llm_outputs=[_llm(ids[0])])
        assert [r.type for r in rep.review_flags] == ["R10"]

    def test_본문은_새_플래그_없음(self):
        layout, ids = self._layout_typed("text", "title")
        rep = QualityChecker().check("p_001", layout_result=layout,
                                     extracted=[_ext(i) for i in ids],
                                     llm_outputs=[_llm(i) for i in ids])
        assert rep.review_flags == [] and rep.status == "COMPLETED"


class TestFallbackFlagIsPageLevel:
    """MinerU 폴백은 쪽 전체가 같은 사정 — 요소마다 띄우면 소음이다 (2026-08-10).

    실측: 38쪽에 2,096건(쪽당 55건)이 같은 문구로 쌓여 진짜 신호를 화면 밖으로 밀어냈다.
    """

    def test_요소마다가_아니라_쪽에_한_번(self):
        layout, ids = _layout(3)
        rep = QualityChecker().check(
            "p_001", layout_result=layout,
            extracted=[_ext(i, flags=["C2_FALLBACK"]) for i in ids],
            llm_outputs=[_llm(i) for i in ids],
        )
        fb = [r for r in rep.review_flags if "폴백" in r.message]
        assert len(fb) == 1 and fb[0].element_id == "page" and fb[0].type == "R1"
        assert "3요소" in fb[0].message and "구조가 소실" in fb[0].message
        assert rep.status == "NEEDS_REVIEW"


class TestR13TextRiskySegment:
    """본문 위험 구간 R13 — 2026-08-10 배선.

    근거(dev+val 839쪽·32,310 본문요소, gold 대비 셀 편집): 태그·로마자·숫자가 든 본문은
    수정필요율 83.5%·크게틀림 52.7%로 본문 평균(56.9%·30.8%)의 1.5~1.7배이고, 본문
    편집셀의 58.5%가 여기 몰려 있다. 종전엔 본문에 플래그가 사실상 없어(11.8%) 전체
    재현율이 6.9%였다. 상세·기각한 신호는 quality_checker._r13_reason 주석 참조.
    """

    def _flags(self, text, typ="text"):
        item = BBoxItem(element_id=uuid4(), type=typ, bbox=(0, 0, 10, 10), reading_order=1)
        layout = LayoutResult(page_id="p_001", elements=[item])
        eid = item.element_id
        ext = ExtractedContent(element_id=eid, corrected_text=text, ocr_confidence=1.0,
                               visual_subtype=None, subtype_confidence=None, flags=[])
        rep = QualityChecker().check("p_001", layout_result=layout, extracted=[ext],
                                     llm_outputs=[_llm(eid, text)])
        return rep, [r for r in rep.review_flags if r.type == "R13"]

    def test_순수_한글_산문은_발화하지_않는다(self):
        _, f = self._flags("광합성은 엽록체에서 일어나는 물질대사 과정이다.")
        assert f == []

    def test_로마자가_있으면_발화한다(self):
        _, f = self._flags("ATP는 세포의 에너지 화폐이다.")
        assert len(f) == 1 and "로마자" in f[0].message

    def test_숫자가_있으면_발화한다(self):
        _, f = self._flags("조사 대상은 2024년 기준 350명이다.")
        assert len(f) == 1 and "아라비아 숫자" in f[0].message

    def test_레이아웃_태그가_있으면_발화한다(self):
        _, f = self._flags("<!테두리_위><!/테두리_위>\n다음 자료를 보고 물음에 답하시오.")
        assert len(f) == 1 and "태그" in f[0].message

    def test_태그_이름의_숫자만으로는_숫자_사유가_안_붙는다(self):
        # C5가 밟았던 오탐(태그 이름의 '2')을 R13이 되풀이하면 안 된다.
        _, f = self._flags("<!테두리_아래2><!/테두리_아래2>\n다음을 보시오.")
        assert len(f) == 1 and "아라비아 숫자" not in f[0].message

    def test_로마자_한_자는_발화하지_않는다(self):
        # 임계 2자는 한계정밀도로 골랐다 — 1자까지 내리면 새 플래그의 정밀도가
        # 64.6%로 기준선(58.3%)에 근접해 소음이 된다(_r13_reason 주석).
        _, f = self._flags("가설 A를 검증하여 서술하시오.")
        assert f == []

    def test_표_시각자료에는_안_붙는다(self):
        # R13은 본문 전용 — 표는 R10, 시각자료는 R11 소관이다.
        _, f = self._flags("2024년 인구 350만 명", typ="table")
        assert f == []

    def test_R13만_있으면_쪽은_COMPLETED로_남는다(self):
        # R13은 결함이 아니라 등급이다. 쪽 판정에 넣으면 실측 839쪽에서 COMPLETED가
        # 255→9로 무너져 status가 무정보해진다.
        rep, f = self._flags("ATP는 2024년에 350회 측정되었다.")
        assert len(f) == 1 and rep.status == "COMPLETED"
