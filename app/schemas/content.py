from __future__ import annotations

from typing import Optional
from uuid import UUID

from pydantic import BaseModel, Field


class RuleApplication(BaseModel):
    """적용된 점자 규정 출처 메타데이터 (rule_trail 구성 단위)."""

    rule_id: str
    source: str
    section: str
    title: str
    excerpt: str
    priority: str = "primary"  # "primary" | "secondary"


class ExtractedContent(BaseModel):
    """OCR / 전처리 출력 공통 스키마.

    - qwen_ocr.py (PART 4-1): corrected_text, ocr_confidence
    - formula_ocr.py (PART 5-1): latex_string, ocr_confidence
    - table_cap.py (PART 6-1): table_structure
    - classifier.py (PART 3-4): visual_subtype, subtype_confidence
    """

    element_id: UUID
    corrected_text: Optional[str] = None
    latex_string: Optional[str] = None
    ocr_confidence: float = 0.0
    visual_subtype: Optional[str] = None
    subtype_confidence: Optional[float] = None
    table_structure: Optional[dict] = None
    flags: list[str] = Field(default_factory=list)
    # 플래그: C2_FALLBACK, C3_FALLBACK, C4_FALLBACK, VERTICAL_TEXT, SUBTYPE_UNCERTAIN


class Draft(BaseModel):
    """점역사주 복수 초안 1개 (시각 요소 전용).

    표·차트·이미지·만화 opt는 서로 다른 3안을 생성한다. 분류·차이 축은
    `code/prompts/stage4_complex.md` 'T4-2 공통 규약' 절이 단일 출처.
    텍스트·수식은 단일안이라 drafts를 쓰지 않는다.
    """

    option: int                          # 1-based, 1 = default(selected_idx 0)
    text: str                            # 점역사주 원문 (점역 대상)
    render_mode: str = "narrative"       # table_grid|transposed|linear|narrative|...
    label: str = ""                      # 방식명 (예: "행↔열 전치", "위치 중심", "요약")
    braille_lines: list[str] = Field(default_factory=list)  # braille 단계에서 채움
    rule_trail: list[RuleApplication] = Field(default_factory=list)


class LLMOutput(BaseModel):
    """점역 최적화 LLM 출력 (PART 4-2 / 5-2 / 6-2 / ...).

    routing_tier:
        ZERO     → 모델 없음 (PyMuPDF 직접 추출, 변환 없음)
        STANDARD → HyperCLOVA X SEED Think 14B (15s 제한)
        QUALITY  → HyperCLOVA X SEED Think 14B (30s 제한)
        FALLBACK → GPT-5.x / o3 API (45s 제한, 비율 < 15% 목표)
    """

    element_id: UUID
    corrected_text: str
    render_mode: str = "text_only"  # text_only|table_grid|transposed|linear|narrative|formula_block|formula_inline
    tn_text: Optional[str] = None
    routing_tier: str  # ZERO|STANDARD|QUALITY|FALLBACK
    processing_time_ms: int = 0
    rule_trail: list[RuleApplication] = Field(default_factory=list)
    # 시각 요소(표·차트·이미지·만화) 전용 복수 초안. 텍스트·수식은 빈 리스트.
    drafts: list[Draft] = Field(default_factory=list)
    selected_idx: int = 0  # corrected_text == drafts[selected_idx].text (drafts 있을 때)


class BrailleOutput(BaseModel):
    """점자 변환 출력 (PART 4-3 / 5-3 / 6-3 / ...)."""

    element_id: UUID
    braille_lines: list[str]  # 선택 초안의 점자 줄 목록 (PART 10 조판용)
    rule_trail: list[RuleApplication] = Field(default_factory=list)
    # 복수 초안 각각의 점역 결과 (BE/FE 노출용). 단일안은 빈 리스트.
    drafts: list[Draft] = Field(default_factory=list)
    selected_idx: int = 0
