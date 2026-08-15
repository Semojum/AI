"""REST 엔드포인트 — 헬스체크·모델 상태 + 마감 조판(/finalize).

점자 '변환'(이미지→점자)은 반드시 gRPC(grpc_server.py)로만 처리한다.
/finalize는 변환이 아니라 **조판(페이지 조립)** 전용 — 점역사가 편집한 블록을
점자 규정(BBPG)대로 페이지로 조립해 회신한다(모델·braillify 미사용, 순수 규칙).
"""

from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel, Field

router = APIRouter()


@router.get("/health")
async def health_check():
    from app.core.health_check import get_health
    return get_health()


@router.get("/models/status")
async def models_status():
    from app.core.health_check import get_models_status
    return get_models_status()


@router.get("/braille/settings/schema")
async def braille_settings_schema():
    """개인 점역 기본값 항목 목록 — **BE가 설정 화면을 만들 때 읽는다.**

    기획서 V11 §7이 "항목 목록은 AI가 스키마로 줍니다"라고 못 박은 자리다. 조판 규칙을
    가진 쪽이 AI라서 값의 범위도 여기서 안다. BE는 저장한 값을
    `BrailleRequest.settings`에 실어 보낸다.

    각 항목의 `wired`가 false면 **저장은 되지만 아직 조판에 반영되지 않는다** —
    사실대로 준다. 안 된 것을 된 것처럼 넘기면 설정 화면만 만들어 놓고 아무 일도
    안 일어난다.
    """
    from app.core.braille_settings import schema_for_be
    return {"items": schema_for_be()}


# ── 마감 조판 (/finalize) ────────────────────────────────────────────────────
# 점역사가 블록 단위로 편집한 점자(이미 32칸 줄)를 받아 BBPG 규정대로 페이지 조립.
# 블록 간 빈 줄(제목 단계별)·25줄 페이지 나눔·페이지행(원본번호·꼬리말·점자번호) 적용.

class FinalizeBlock(BaseModel):
    """점역사 편집 블록 1개 (요소 단위). lines = 32칸으로 조판된 점자 줄.

    ★ 두 형식을 모두 받는다(2026-07-28) — BE는 응답의 `contents`를 그대로 되돌려주면 된다.
      · 줄 배열      ["줄1", "줄2"]        (종전 형식)
      · 요소 1항목   ["줄1\\n줄2"]          (현재 `contents` 형식)
    `normalized_lines()`가 어느 쪽이든 줄 배열로 펴 준다.
    """
    id: str = ""
    type: str = "text"          # text|title|formula|table|image|cartoon|chart_graph|list_item|header_footer|page_number|...
    heading_level: int = 0      # 제목 단계(빈 줄 규칙). 0=본문
    order: int = 0              # 문서 읽기 순서
    lines: list[str] = Field(default_factory=list)  # 점자 줄(U+2800, 각 ≤32칸) 또는 줄바꿈 결합 1항목

    def normalized_lines(self) -> list[str]:
        """`lines`를 줄 배열로 정규화(줄바꿈 결합 항목을 펴 준다)."""
        out: list[str] = []
        for ln in self.lines:
            out.extend(ln.split("\n") if "\n" in ln else [ln])
        return out


class FinalizeRequest(BaseModel):
    job_id: str = ""
    page_no: int = 1            # 이 페이지의 시작 점자 페이지 번호
    total_pages: int = 1
    blocks: list[FinalizeBlock] = Field(default_factory=list)


class BraillePage(BaseModel):
    page_no: int                # 점자 페이지 번호
    lines: list[str]            # 32칸 × 25줄 (페이지행 포함)


class FinalizeResponse(BaseModel):
    job_id: str
    page_number: int            # 요청 시작 페이지 번호
    pages: list[BraillePage]    # 조립된 점자 페이지들(원본 1쪽이 여러 점자쪽이 될 수 있음)
    brf: str                    # 전체 BRF 텍스트(줄바꿈 join) — 파일 저장용


@router.post("/finalize", response_model=FinalizeResponse)
async def finalize_page(req: FinalizeRequest) -> FinalizeResponse:
    """편집 블록 → BBPG 페이지 조립. (점자 변환 아님 — 규칙 기반 조판만.)"""
    from app.ai.braille.layout_braille import LayoutBraille

    pages = LayoutBraille().finalize(
        [{**b.model_dump(), "lines": b.normalized_lines()} for b in req.blocks],
        page_no=req.page_no,
    )
    brf = "\n".join(line for page in pages for line in page)
    return FinalizeResponse(
        job_id=req.job_id,
        page_number=req.page_no,
        pages=[BraillePage(page_no=req.page_no + i, lines=pg) for i, pg in enumerate(pages)],
        brf=brf,
    )
