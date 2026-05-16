"""PART 2 — PDF 페이지 → PIL.Image 변환.

STANDARD : 150 DPI JPG
QUALITY  : 300 DPI → Otsu 이진화 → deskew → JPG

변환된 이미지는 storage/jobs/{job_id}/input/page_{no:03d}.jpg 에 저장.
"""

from __future__ import annotations

import io
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from PIL import Image as PILImage

try:
    import fitz  # type: ignore[import]
except ImportError:
    fitz = None

try:
    import cv2
    import numpy as np
except ImportError:
    cv2 = None
    np = None


def convert_page(
    pdf_data: bytes,
    page_index: int,
    routing_tier: str,
    job_id: str,
    page_no: int = 1,
) -> "PILImage":
    """PDF 페이지를 PIL.Image로 변환하고 디스크에 저장.

    routing_tier:
        STANDARD → 150 DPI
        QUALITY  → 300 DPI + Otsu 이진화 + deskew
    """
    if fitz is None:
        raise ImportError("PyMuPDF(fitz)가 설치되지 않았습니다: pip install pymupdf")

    from PIL import Image

    dpi = 300 if routing_tier == "QUALITY" else 150
    scale = dpi / 72.0

    doc = fitz.open(stream=io.BytesIO(pdf_data), filetype="pdf")
    try:
        page = doc[page_index]
        mat = fitz.Matrix(scale, scale)
        pix = page.get_pixmap(matrix=mat, colorspace=fitz.csRGB)
        img_bytes = pix.tobytes("png")
    finally:
        doc.close()

    img = Image.open(io.BytesIO(img_bytes)).convert("RGB")

    if routing_tier == "QUALITY":
        img = _binarize_and_deskew(img)

    # 디스크 저장
    out_dir = Path(f"storage/jobs/{job_id}/input")
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"page_{page_no:03d}.jpg"
    img.save(str(out_path), format="JPEG", quality=95)

    return img


def _binarize_and_deskew(img: "PILImage") -> "PILImage":
    """Otsu 이진화 + deskew 보정."""
    if cv2 is None or np is None:
        return img  # OpenCV 미설치 시 원본 반환

    from PIL import Image

    arr = np.array(img.convert("L"))
    _, binary = cv2.threshold(arr, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)

    # deskew: Hough 변환 기반 기울기 보정
    coords = np.column_stack(np.where(binary < 128))
    if len(coords) > 50:
        angle = cv2.minAreaRect(coords)[-1]
        if angle < -45:
            angle = 90 + angle
        if abs(angle) > 0.5:
            h, w = binary.shape
            center = (w // 2, h // 2)
            M = cv2.getRotationMatrix2D(center, angle, 1.0)
            binary = cv2.warpAffine(binary, M, (w, h), flags=cv2.INTER_CUBIC,
                                    borderMode=cv2.BORDER_REPLICATE)

    return Image.fromarray(binary).convert("RGB")
