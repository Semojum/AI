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
    # 요소-로컬 좌표(조판 후) — 좌표계 = 이 블록의 contents 배열.
    # FE는 contents[line_no][col_start:col_end]만 하이라이트(계산 없음). line_no=-1 → 요소 전체.
    line_no: int = -1    # contents 줄 인덱스(0-based). -1 = 요소 전체
    col_start: int = 0   # 줄 안의 시작 칸(0-based)
    col_end: int = 0     # 끝 칸(미포함). 점 태그는 col_start==col_end. line_no=-1이면 무시
    tag: str = ""        # 변환 지점 태그 (number_sign / contraction / symbol / line_wrap ...)


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
    # 시각자료 구조화 입력(현주 계약). 유형별: cartoon=panels/title, chart=axes/data_points,
    # image=visual_type_label/ocr_texts 등. 없으면 corrected_text(caption) 폴백.
    structure: Optional[dict] = None
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
    braille_lines: list[str] = Field(default_factory=list)  # braille 단계에서 채움(조판 후 32칸)
    break_points: list[list[int]] = Field(default_factory=list)  # 음절 줄바꿈 offset(layout 조판용)
    rule_trail: list[RuleApplication] = Field(default_factory=list)


class LLMOutput(BaseModel):
    """점역 최적화 LLM 출력 (PART 4-2 / 5-2 / 6-2 / ...).

    routing_tier:
        ZERO     → 모델 없음 (PyMuPDF 직접 추출, 변환 없음)
        STANDARD → HyperCLOVA X SEED Think 14B (요소당 상한 = config.hcxt_element_timeout_seconds)
        QUALITY  → HyperCLOVA X SEED Think 14B (요소당 상한 = config.hcxt_quality_timeout_seconds)
        FALLBACK → GPT-4o API (45s 제한). HCXT 타임아웃·페이지 예산 소진 시 병렬 폴백.
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
    # 줄별 들여쓰기(칸). 규정 골격(만화 5칸 장면/3칸 대사·시각자료 제목 5칸)을 rule-based로
    # 조립한 요소에서 logical 줄 수와 같게 채운다. None이면 layout 기본(첫 줄만 들여).
    line_indents: Optional[list[int]] = None
    # 표 제목(전사). 도서 제작 지침 제3장 5): 표 제목은 5칸에서 시작하고 위 테두리 앞 줄에 적는다.
    # table_braille가 위 테두리(격자) 앞에 5칸 들여 렌더한다. 표 외 요소는 None(제목은 골격에 포함).
    table_title: Optional[str] = None
    # 중첩 시각자료(점역사 QnA Q11). 테두리 태그가 든 보조 narrative를 본 요소 점자 끝에 덧붙인다.
    #   그림 안 그래프 → 그래프 설명을 테두리로 묶음 / 표 안 그림 → 그림을 글상자처럼 1단 풀어쓰기.
    # braille 모듈이 translate 후 braille_lines·box_borders에 append한다. 없으면 None.
    nested_text: Optional[str] = None


class BoxBorder(BaseModel):
    """글상자 테두리 메타 (BBPG-1.2.5). layout이 위계·제목 배치로 재렌더한다.

    translator는 점자 스트림에 인라인 32칸 테두리 줄을 위치 마커로 남기고(제어문자 없음),
    제목 전체(클립 전)·위계를 이 메타로 순서대로 전달한다. layout이 마커 줄을 순서대로
    이 메타와 짝지어 재렌더(위계별 테두리 + 제목 배치 중간7칸/윗줄5칸 + 위아래 빈 줄).
    """

    kind: str           # "top" | "bottom"
    level: int = 1      # 위계 1~3 (현재 1만 발생; 구조는 확장 가능)
    title: str = ""     # 점자화된 제목 (top만, 클립 전 전체)


class BrailleOutput(BaseModel):
    """점자 변환 출력 (PART 4-3 / 5-3 / 6-3 / ...)."""

    element_id: UUID
    braille_lines: list[str]  # 논리 줄(개행 단위). 32칸 줄바꿈은 PART 10 layout이 수행
    # 줄별 음절 줄바꿈 허용 offset(BBPG-1.2.1) — layout이 32칸 줄바꿈에 사용, 응답엔 미노출.
    # braille_lines와 길이가 같다(줄 i의 허용 offset 목록). 비면 layout이 어절 단위로 분리.
    break_points: list[list[int]] = Field(default_factory=list)
    rule_trail: list[RuleApplication] = Field(default_factory=list)
    box_borders: list[BoxBorder] = Field(default_factory=list)  # 글상자 테두리(BBPG-1.2.5), layout 재렌더용
    # 복수 초안 각각의 점역 결과 (BE/FE 노출용). 단일안은 빈 리스트.
    drafts: list[Draft] = Field(default_factory=list)
    selected_idx: int = 0
    # 줄별 들여쓰기(칸) — braille_lines와 길이 동일. 규정 골격 요소(만화·시각자료 제목)에서
    # layout이 줄마다 이 칸수로 들여쓴다(첫 줄만 들이는 기본 동작을 대체). None이면 기본.
    line_indents: Optional[list[int]] = None
