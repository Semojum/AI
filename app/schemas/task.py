from __future__ import annotations

from pydantic import BaseModel, Field


class PageTask(BaseModel):
    """gRPC BrailleRequest → 파이프라인 내부 표현.

    pipeline.py 는 이 타입을 받아 PART 1~9를 실행한다.
    pdf_layer_confidence 는 요청에 포함되지 않으며,
    PART 1 (Preprocessor)이 pdf_data에서 직접 산출한다.
    """

    job_id: str
    page_no: int
    total_pages: int = 1
    pdf_data: bytes = b""
    mode: str  # "a" | "b" | "c"
    source_text: str = ""   # mode b 전용
    # 고급 점역 — 켜면 MinerU 대신 LLM 이 쪽 이미지를 직접 읽는다(대표 결정 2026-09-01).
    advanced_ai: bool = False
    # LLM 캐시 격리 열쇠. 빈 값이면 job_id 로 대체한다(`pipeline.run`).
    customer_id: str = ""
    # 요청이 아니라 **결과**다. 고급 점역이 실제로 돈 자리에서 파이프라인이 켠다
    # (지면 추출 LLM_VISION · 본문 OCR 교정 LLM). 응답 processing_meta 로 나간다.
    advanced_ai_applied: bool = False

    @classmethod
    def from_proto(cls, req) -> "PageTask":
        """grpc BrailleRequest 메시지 → PageTask 변환."""
        return cls(
            job_id=req.job_id,
            page_no=req.page_no,
            total_pages=req.total_pages or 1,
            pdf_data=req.pdf_data,
            advanced_ai=bool(getattr(req, "advanced_ai", False)),
            customer_id=getattr(req, "customer_id", "") or "",
            mode=req.mode.lower() if req.mode else "c",
            source_text=req.source_text,
        )
