import os
import tempfile
from typing import Optional

import fitz

from app.schemas.layout import DocumentMeta

MIN_TEXT_LENGTH = 10


def analyze_pdf(
    pdf_path: str | bytes,
    page_no: int,
    job_id: Optional[str] = None,
) -> tuple[DocumentMeta, str]:
    """
    pdf_path : str(파일 경로) 또는 bytes(PDF 데이터)
    page_no  : 1-indexed. 0 이하가 들어오면 +1 보정.
    job_id   : 미사용 — pipeline.py 호환용
    반환     : (DocumentMeta, page_text)
               TEXT_NATIVE → routing_tier="ZERO",     page_text=페이지 전체 텍스트
               OCR         → routing_tier="STANDARD", page_text=""
    """
    if page_no < 1:
        page_no += 1

    tmp_path = None
    try:
        if isinstance(pdf_path, bytes):
            with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
                f.write(pdf_path)
                tmp_path = f.name
            open_path = tmp_path
        else:
            open_path = str(pdf_path)

        doc = fitz.open(open_path)
        try:
            page = doc[page_no - 1]
            text = page.get_text().strip()
        finally:
            doc.close()
    finally:
        if tmp_path:
            os.unlink(tmp_path)

    if len(text) >= MIN_TEXT_LENGTH:
        return DocumentMeta(pdf_confidence=1.0, routing_tier="ZERO", scan_only=False), text
    else:
        return DocumentMeta(pdf_confidence=0.5, routing_tier="STANDARD", scan_only=False), ""
