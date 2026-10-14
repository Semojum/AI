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
    source_text: str = ""   # mode b 전용. proto 이름은 `text_data`(V4 정본 6)
    # 고급 교열 — 켜면 MinerU 대신 LLM 이 쪽 이미지를 직접 읽는다(대표 결정 2026-09-01).
    advanced_ai: bool = False
    # 문항코드 자리 꼴(원장 C-107): "X" `01 [코드] 발문` · "Y" 코드 윗줄 · "off" 종전. 빈 값이면 서버 기본(X).
    #   V4 정본 proto 에는 이 칸이 없다(11 은 english_grade, #1380). 요청으로는 못 바꾸고 늘 서버 기본이다.
    item_code_form: str = ""
    # 한글 · 영어 정자(1급, #1191 · #1189) — 점역사가 업로드 때 고르는 낱값(대표 결재 2026-10-08).
    #   `pipeline.run` 이 `constants.KOREAN_GRADE1` · `ENGLISH_GRADE1` 문맥 값으로 놓는다. 기본 False = 약자.
    #   proto 는 급수 정수다(V4 정본 10 · 11: 1 정자 · 2 약자 · 0 = 서버 기본 2). `from_proto` 가 1 일 때만 참으로 옮긴다.
    korean_grade1: bool = False
    english_grade1: bool = False
    # 선택지 한 줄에 하나(#1238, 원장 C-166) — 켜면 짧은 선택지도 합치지 않는다(「점자 도서 제작 지침」 3장 3절 2. 4)(3)④).
    #   proto 이름은 `split_choices`(V4 정본 12, 뜻 같음).
    #   `pipeline.run` 이 `constants.CHOICES_ONE_PER_LINE` 문맥 값으로 놓는다. 기본 False = 3-2 · 2-2-1 로 합친다.
    choices_one_per_line: bool = False

    @classmethod
    def from_proto(cls, req) -> "PageTask":
        """grpc BrailleRequest 메시지 → PageTask 변환."""
        return cls(
            job_id=req.job_id,
            page_no=req.page_no,
            total_pages=req.total_pages or 1,
            pdf_data=req.pdf_data,
            advanced_ai=bool(getattr(req, "advanced_ai", False)),
            korean_grade1=_grade(getattr(req, "korean_grade", 0)) == 1,
            english_grade1=_grade(getattr(req, "english_grade", 0)) == 1,
            choices_one_per_line=bool(getattr(req, "split_choices", False)),
            mode=req.mode.lower() if req.mode else "c",
            source_text=getattr(req, "text_data", "") or "",
        )


def _grade(v: int) -> int:
    """proto 급수(1 정자 · 2 약자 · 0 = 서버 기본 2). 그 밖의 값은 계약 밖이라 거절한다(조용히 약자로 돌지 않게)."""
    if v not in (0, 1, 2):
        raise ValueError(f"급수는 0 · 1 · 2 여야 한다: {v}")
    return v or 2
