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

    @classmethod
    def from_proto(cls, req) -> "PageTask":
        """grpc BrailleRequest 메시지 → PageTask 변환."""
        return cls(
            job_id=req.job_id,
            page_no=req.page_no,
            total_pages=req.total_pages or 1,
            pdf_data=req.pdf_data,
            mode=req.mode.lower() if req.mode else "c",
            source_text=req.source_text,
        )
