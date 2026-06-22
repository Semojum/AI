import base64
import binascii
import os
import tempfile
from typing import Optional

import fitz

from app.schemas.layout import DocumentMeta
from app.utils.logger import get_logger

logger = get_logger(__name__)

MIN_TEXT_LENGTH = 10

# PUA(사설영역) 글자 비율이 이 값을 넘으면 텍스트레이어를 신뢰하지 않는다.
# 한컴/HWP 수식 폰트는 수식·도형 글리프를 PUA(U+E000~)로 인코딩 → PyMuPDF가 매핑 없는
# raw 코드포인트로 추출한다. 텍스트는 '있으나' 수식이 글자로 안 읽혀 ZERO로는 점역 불가 →
# STANDARD(MinerU)로 보내 OCR/수식 추출을 거치게 한다.
PUA_RATIO_THRESHOLD = 0.10

# 유효 PDF는 항상 "%PDF-"로 시작한다(앞쪽 일부 공백/BOM 허용).
_PDF_MAGIC = b"%PDF-"


def extract_text_blocks(pdf_data: bytes, page_no: int) -> tuple[list[dict], int, int]:
    """텍스트레이어(ZERO) 추출 — PyMuPDF 블록 단위로 (content, bbox)를 뽑는다.

    반환: (blocks, page_width, page_height). 좌표계 = MinerU와 동일하게 2x 렌더 픽셀
    (PyMuPDF 포인트 × 2). page_width/height도 2x. BE/FE가 bbox/크기 비율로 매핑.
    """
    data = _coerce_pdf_bytes(pdf_data)
    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
            f.write(data)
            tmp_path = f.name
        doc = fitz.open(tmp_path)
        try:
            page_idx = max(0, min(page_no - 1, doc.page_count - 1))
            page = doc[page_idx]
            w, h = page.rect.width, page.rect.height
            blocks: list[dict] = []
            for x0, y0, x1, y1, text, _bno, btype in page.get_text("blocks"):
                if btype != 0:          # 0 = 텍스트 블록, 1 = 이미지 블록(여기선 제외)
                    continue
                t = (text or "").strip()
                if not t:
                    continue
                blocks.append({
                    "content": t,
                    "bbox": [round(x0 * 2), round(y0 * 2), round(x1 * 2), round(y1 * 2)],
                })
        finally:
            doc.close()
    finally:
        if tmp_path:
            os.unlink(tmp_path)
    return blocks, int(round(w * 2)), int(round(h * 2))


def _page_has_visual(page) -> bool:
    """텍스트레이어 페이지에 표·유의미한 이미지가 있으면 True → MinerU(OCR) 라우팅.

    순수 텍스트는 ZERO로 빠르게 처리하되, 표·그림 등 '텍스트 기반 시각자료'는 구조·캡션이
    필요해 MinerU가 처리해야 한다(태민 방침). 작은 장식 로고는 제외(페이지 3% 미만).
    """
    page_area = (page.rect.width * page.rect.height) or 1.0
    try:
        for info in page.get_image_info():
            bb = info.get("bbox")
            if bb and (bb[2] - bb[0]) * (bb[3] - bb[1]) > 0.03 * page_area:
                return True
    except Exception:  # noqa: BLE001
        pass
    try:
        if page.find_tables().tables:   # 선이 있는 표 감지
            return True
    except Exception:  # noqa: BLE001
        pass
    return False


def _pua_ratio(text: str) -> float:
    """비공백 글자 중 PUA(U+E000~U+F8FF, 보충 PUA) 비율."""
    chars = [c for c in text if not c.isspace()]
    if not chars:
        return 0.0
    pua = sum(
        1 for c in chars
        if 0xE000 <= ord(c) <= 0xF8FF or 0xF0000 <= ord(c) <= 0x10FFFD
    )
    return pua / len(chars)


class InvalidPDFError(ValueError):
    """도착한 pdf_data가 유효 PDF가 아닐 때. 메시지는 BE 디버깅용 진단을 담는다."""


def diagnose_pdf_bytes(data: bytes) -> Optional[str]:
    """도착 바이트가 유효 PDF인지 진단. 문제가 없으면 None, 있으면 사유 문자열.

    BE↔AI 전송 시 흔한 변질(base64 인코딩, 경로 문자열, 텍스트 모드, 빈/잘린 데이터)을
    사람이 읽을 수 있는 진단으로 변환해 C1 BLOCKED 메시지에 실어 보낸다.
    """
    if not data:
        return "도착 데이터 길이 0 — BE가 빈 bytes를 전송(파일 핸들/경로 누락 의심)."
    head = data[:64].lstrip(b"\x00\r\n\t \xef\xbb\xbf")  # 선행 공백/BOM 제거
    if head[:5] == _PDF_MAGIC:
        return None
    # base64로 인코딩된 PDF인가? (%PDF- → 'JVBER...')
    if head[:5] == b"JVBER":
        return "base64로 인코딩된 PDF로 보임 — proto pdf_data는 raw bytes여야 함(base64 금지)."
    # 파일 경로 문자열을 그대로 bytes로 넣었는가?
    try:
        as_text = data[:256].decode("utf-8", errors="strict")
        if as_text.startswith(("/", "./", "../", "~")) or as_text[1:3] == ":\\":
            return f"PDF 바이트가 아니라 파일 경로 문자열로 보임: {as_text[:80]!r}"
    except UnicodeDecodeError:
        as_text = None
    return (
        f"PDF 매직(%PDF-) 없음 — 길이 {len(data)}B, 첫 8바이트 {data[:8]!r}. "
        "전송 중 변질이거나 BE 적재 오류(텍스트 모드/인코딩/압축 의심)."
    )


def _coerce_pdf_bytes(data: bytes) -> bytes:
    """가능하면 흔한 변질을 복구한다. 복구 불가하면 InvalidPDFError.

    - base64-of-PDF: 디코드해 사용(경고 로그). BE 버그지만 파이프라인은 진행시킨다.
    - 그 외 비-PDF: 진단 메시지와 함께 InvalidPDFError.
    """
    problem = diagnose_pdf_bytes(data)
    if problem is None:
        return data
    head = data[:16].lstrip(b"\x00\r\n\t \xef\xbb\xbf")
    if head[:5] == b"JVBER":
        try:
            decoded = base64.b64decode(data, validate=False)
        except (binascii.Error, ValueError):
            decoded = b""
        if decoded[:5] == _PDF_MAGIC:
            logger.warning("pdf_data가 base64로 도착 — 디코드해 복구함(BE는 raw bytes 전송 필요)")
            return decoded
    raise InvalidPDFError(problem)


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
            # 도착 바이트 진단 로그(전송 변질 추적용) + 흔한 변질 복구/거부
            logger.info(
                "pdf_data 도착: page=%s len=%dB head=%r",
                page_no, len(pdf_path), pdf_path[:8],
            )
            pdf_bytes = _coerce_pdf_bytes(pdf_path)
            with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
                f.write(pdf_bytes)
                tmp_path = f.name
            open_path = tmp_path
        else:
            open_path = str(pdf_path)

        doc = fitz.open(open_path)
        try:
            # proto 계약상 pdf_data는 '단일 페이지' PDF다(BE가 페이지마다 1장씩 전송).
            # page_no는 원본 문서의 페이지 번호(헤더/푸터·저장경로용)일 뿐이므로,
            # 도착 PDF 인덱스로 그대로 쓰면(예: page_no=2 → doc[1]) 단일 페이지에서
            # IndexError가 난다. 페이지 수에 맞게 클램프(단일=0, 멀티=page_no-1).
            page_idx = max(0, min(page_no - 1, doc.page_count - 1))
            page = doc[page_idx]
            text = page.get_text().strip()
            has_visual = _page_has_visual(page) if len(text) >= MIN_TEXT_LENGTH else False
        finally:
            doc.close()
    finally:
        if tmp_path:
            os.unlink(tmp_path)

    if len(text) >= MIN_TEXT_LENGTH:
        pua = _pua_ratio(text)
        if pua >= PUA_RATIO_THRESHOLD:
            # 텍스트는 있으나 PUA 글리프 과다 → 텍스트레이어 비신뢰 → MinerU 경로.
            logger.info(
                "PUA 비율 %.1f%% (≥%.0f%%) → 텍스트레이어 비신뢰, STANDARD 라우팅 page=%s",
                pua * 100, PUA_RATIO_THRESHOLD * 100, page_no,
            )
            return DocumentMeta(pdf_confidence=0.5, routing_tier="STANDARD", scan_only=False), ""
        if has_visual:
            # 텍스트레이어지만 표·그림 등 시각자료 포함 → 구조·캡션 위해 MinerU OCR.
            logger.info("표·그림 포함 → STANDARD(MinerU) 라우팅 page=%s", page_no)
            return DocumentMeta(pdf_confidence=0.7, routing_tier="STANDARD", scan_only=False), ""
        # 순수 텍스트 → ZERO(빠른 직접추출).
        return DocumentMeta(pdf_confidence=1.0, routing_tier="ZERO", scan_only=False), text
    else:
        return DocumentMeta(pdf_confidence=0.5, routing_tier="STANDARD", scan_only=False), ""
