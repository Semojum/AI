from __future__ import annotations

from typing import Optional
from uuid import UUID, uuid4

from pydantic import BaseModel, Field


class BBoxItem(BaseModel):
    """레이아웃 탐지 결과의 개별 요소."""

    element_id: UUID = Field(default_factory=uuid4)
    type: str  # 11종: text|title|caption|table|image|formula|list_item|header_footer|page_number|footnote|sidebar
    bbox: tuple[int, int, int, int]  # (x1, y1, x2, y2)
    reading_order: int
    heading_level: Optional[int] = None  # title 타입만 사용 (1|2|3)
    caption_ref: Optional[UUID] = None   # 캡션이 참조하는 요소의 element_id
    flags: list[str] = Field(default_factory=list)


class LayoutResult(BaseModel):
    """한 페이지의 전체 레이아웃 탐지 결과."""

    page_id: str
    elements: list[BBoxItem] = Field(default_factory=list)


class DocumentMeta(BaseModel):
    """전처리 결과 메타데이터 (PART 2 출력).

    routing_tier 구간:
        ZERO     → confidence ≥ 0.92 (PyMuPDF 직접 추출, VLM 생략)
        STANDARD → 0.30 ≤ confidence < 0.92 (150 DPI 전체 파이프라인)
        QUALITY  → confidence < 0.30 (300 DPI + Otsu 이진화, scan_only=True)
    """

    pdf_confidence: float
    routing_tier: str  # ZERO | STANDARD | QUALITY
    scan_only: bool = False
    page_image_path: Optional[str] = None
    header_pattern: Optional[str] = None
    footer_pattern: Optional[str] = None
