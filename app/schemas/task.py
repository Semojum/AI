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
            pdf_data=req.pdf_data or _image_pdf(getattr(req, "image_data", b"")),
            advanced_ai=bool(getattr(req, "advanced_ai", False)),
            korean_grade1=_grade(getattr(req, "korean_grade", 0)) == 1,
            english_grade1=_grade(getattr(req, "english_grade", 0)) == 1,
            choices_one_per_line=bool(getattr(req, "split_choices", False)),
            mode=req.mode.lower() if req.mode else "c",
            source_text=getattr(req, "text_data", "") or "",
        )


def _image_pdf(data: bytes) -> bytes:
    """쪽 이미지(V4 정본 8, png · jpeg) → 한 쪽 PDF(#1384). 빈 값은 빈 값이다.

    mode a 소비처(텍스트 층 · 라우팅 · MinerU · 환각 검사 등 15곳)는 전부 `pdf_data` 를 제 DPI 로 렌더하므로
    감싸기만 하면 고치지 않고 돈다. 텍스트 층이 없으니 스캔 쪽 길(MinerU)을 탄다. 품질도 스캔 PDF 수준이다.
    MinerU 의 이미지 입력(`images_bytes_to_pdf_bytes`)과 같은 꼴로 감싼다: 사진 방향(EXIF)을 바로잡고
    200 DPI(MinerU 렌더 DPI 와 같아 1:1) · JPEG 95 로 적는다. 못 푸는 바이트는 예외 → 서버가 "요청 파싱 실패".
    ⚠ fitz 의 `convert_to_pdf()` 로 바꾸지 말 것. EXIF 방향을 무시하고, DPI 가 없으면 96 으로 봐 쪽이 약 2배가 된다.
    """
    if not data:
        return b""
    from io import BytesIO

    from PIL import Image, ImageOps

    buf = BytesIO()
    ImageOps.exif_transpose(Image.open(BytesIO(data))).convert("RGB").save(
        buf, format="PDF", resolution=200, quality=95, subsampling=0)
    return buf.getvalue()


def _grade(v: int) -> int:
    """proto 급수(1 정자 · 2 약자 · 0 = 서버 기본 2). 그 밖의 값은 계약 밖이라 거절한다(조용히 약자로 돌지 않게)."""
    if v not in (0, 1, 2):
        raise ValueError(f"급수는 0 · 1 · 2 여야 한다: {v}")
    return v or 2
