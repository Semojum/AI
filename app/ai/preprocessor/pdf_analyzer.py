"""전처리 PART 2 — PDF 신뢰도 산출 + 라우팅 티어 결정.

pdf_confidence 공식:
    confidence = (1 - broken_char_ratio) × 0.50
               + text_density           × 0.30
               + korean_ratio           × 0.20

라우팅 티어:
    ZERO     → confidence ≥ 0.92  (PyMuPDF 텍스트 직접 추출, VLM 생략)
    STANDARD → 0.30 ≤ confidence < 0.92  (150 DPI → 전체 파이프라인)
    QUALITY  → confidence < 0.30  (300 DPI + Otsu 이진화, scan_only=True)
"""

from __future__ import annotations

import io
import re
import unicodedata
from typing import Optional

from app.schemas.layout import DocumentMeta

try:
    import fitz  # type: ignore[import]
except ImportError:
    fitz = None

_HANGUL_RE = re.compile(r"[가-힣ᄀ-ᇿ]")
_BROKEN_RE = re.compile(r"[\x00-\x08\x0B-\x0C\x0E-\x1F�]")


def _calc_confidence(broken_ratio: float, density: float, korean_ratio: float) -> float:
    return (1.0 - broken_ratio) * 0.50 + density * 0.30 + korean_ratio * 0.20


def _analyze_text(text: str, page_area: float) -> tuple[float, float, float]:
    if not text:
        return 1.0, 0.0, 0.0
    total = len(text)
    broken = len(_BROKEN_RE.findall(text))
    broken_ratio = min(broken / total, 1.0)
    density = min(total / max(page_area, 1.0) * 10_000, 1.0)
    hangul = len(_HANGUL_RE.findall(text))
    korean_ratio = hangul / total
    return broken_ratio, density, korean_ratio


def _detect_header_footer(page: "fitz.Page") -> tuple[Optional[str], Optional[str]]:
    rect = page.rect
    h = rect.height
    top_band = h * 0.07
    bot_band = h * 0.93
    headers, footers = [], []
    for block in page.get_text("blocks"):
        y0, y1, text = block[1], block[3], block[4].strip()
        if not text:
            continue
        if y1 < top_band:
            headers.append(text)
        elif y0 > bot_band:
            footers.append(text)
    return (" ".join(headers) or None), (" ".join(footers) or None)


def analyze_pdf(
    pdf_data: bytes,
    page_index: int,
    job_id: str,
) -> tuple[DocumentMeta, Optional[str]]:
    """PDF bytes → (DocumentMeta, pdf_text).

    pdf_text는 ZERO Tier에서만 반환 (PyMuPDF 직접 추출 텍스트).
    STANDARD/QUALITY에서는 None 반환 (converter.py로 이미지 변환 필요).
    """
    if fitz is None:
        raise ImportError("PyMuPDF(fitz)가 설치되지 않았습니다: pip install pymupdf")

    doc = fitz.open(stream=io.BytesIO(pdf_data), filetype="pdf")
    try:
        page = doc[page_index]
        area = page.rect.width * page.rect.height
        raw_text = page.get_text("text") or ""
        broken, density, korean = _analyze_text(raw_text, area)
        confidence = _calc_confidence(broken, density, korean)
        header, footer = _detect_header_footer(page)
    finally:
        doc.close()

    if confidence >= 0.92:
        tier = "ZERO"
        pdf_text: Optional[str] = raw_text
    elif confidence >= 0.30:
        tier = "STANDARD"
        pdf_text = None
    else:
        tier = "QUALITY"
        pdf_text = None

    meta = DocumentMeta(
        pdf_confidence=confidence,
        routing_tier=tier,
        scan_only=(tier == "QUALITY"),
        header_pattern=header,
        footer_pattern=footer,
    )
    return meta, pdf_text
