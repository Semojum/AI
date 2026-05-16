from __future__ import annotations

from pydantic import BaseModel, Field


class CriticalError(BaseModel):
    """Critical 오류 — 해당 요소 BLOCKED 처리 필요.

    C1: 전체 OCR 실패         → 페이지 전체 BLOCKED
    C2: 콘텐츠 블록 소실       → 해당 요소 BLOCKED
    C3: 수식 파손             → 해당 요소 BLOCKED
    C4: 표 완전 실패           → 해당 요소 BLOCKED
    C5: 점자 숫자 오류         → 배포 전 테스트 차단 (런타임 발생 불가)
    C6: 32칸 초과율 > 30%     → 페이지 NEEDS_REVIEW
    C7: 180초 타임아웃 초과    → 페이지 전체 BLOCKED
    """

    type: str       # C1~C7
    element_id: str
    message: str


class ReviewFlag(BaseModel):
    """검토 권고 플래그 — 결과물은 사용 가능하나 점역사 확인 필요.

    R1: LOW_CONFIDENCE           R7: VERTICAL_TEXT
    R2: SUBTYPE_UNCERTAIN        R8: FOOTNOTE_POSITION_UNCERTAIN
    R3: IRREGULAR_TABLE          R9: SIDEBAR_CONTEXT_UNCLEAR
    R4: HALLUCINATION_SUSPECTED  R10: TABLE_FORMULA_COMPLEX
    R5: TN_INCOMPLETE            R11: IMAGE_TEXT_MISSING
    R6: DIAGRAM_SUBTYPE_UNKNOWN  R12: FOOTNOTE_SIDEBAR_MIXED
    """

    type: str       # R1~R12
    element_id: str
    message: str


class QualityReport(BaseModel):
    """PART 9 품질 검증 결과."""

    page_id: str
    status: str  # OK | NEEDS_REVIEW | BLOCKED
    ocr_confidence_avg: float = 0.0
    line_overflow_rate: float = 0.0
    critical_errors: list[CriticalError] = Field(default_factory=list)
    review_flags: list[ReviewFlag] = Field(default_factory=list)
