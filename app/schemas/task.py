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
    # 문항코드 자리 꼴(원장 C-107): "X" `01 [코드] 발문` · "Y" 코드 윗줄 · "off" 종전. 빈 값이면 서버 기본(X).
    #   점역사가 책마다 고르는 설정이다(대표 결재 2026-10-04). proto 필드가 생기면 그대로 받는다.
    item_code_form: str = ""

    @classmethod
    def from_proto(cls, req) -> "PageTask":
        """grpc BrailleRequest 메시지 → PageTask 변환."""
        return cls(
            job_id=req.job_id,
            page_no=req.page_no,
            total_pages=req.total_pages or 1,
            pdf_data=req.pdf_data,
            advanced_ai=bool(getattr(req, "advanced_ai", False)),
            item_code_form=str(getattr(req, "item_code_form", "") or ""),
            mode=req.mode.lower() if req.mode else "c",
            source_text=req.source_text,
        )
