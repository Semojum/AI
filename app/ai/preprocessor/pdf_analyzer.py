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

# ── ZERO 티어 어절 경계 복원 ────────────────────────────────────────────────
# 교과서 PDF 다수가 공백 글리프 없이 글자 위치(커닝)로만 어절을 띄운다 → PyMuPDF
# get_text()가 한국어를 통째로 붙여 추출("다음은가정환경…") → 점자 띄어쓰기 전멸.
# 글자 bbox 간격은 이중분포(어절 경계 ≈ +0.2×폰트크기 vs 글자 내 ≈ -0.1×폰트크기)라
# 줄별 기준 간격(중앙값) 대비 확실히 벌어진 지점에만 공백을 복원한다(rule-based).
_WORD_GAP_RATIO = 0.12   # 어절 경계 판정: 기준 간격 + max(이 비율×폰트크기, 1.0pt)
_WORD_GAP_MIN_PT = 1.0
_MIN_GAP_SAMPLES = 4     # 줄에 간격 표본이 이보다 적으면 판단 보류(원문 유지)


def _is_hangul(ch: str) -> bool:
    return "가" <= ch <= "힣" or "ㄱ" <= ch <= "ㅣ"


# ── 밑줄(드러냄표) 감지 ──────────────────────────────────────────────────────
# 한국 점자 규정 제56항: 밑줄·드러냄표로 강조된 글자체는 ⠠⠤…⠤⠄로 적는다.
# 정답 도서는 이걸 1204회 쓰는데(수능 문항 "밑줄 친 ㉠~㉤") 우리는 0회였다 — 밑줄이
# 폰트 속성이 아니라 **벡터 선**으로 그려져 있어 텍스트 추출만으로는 안 보였기 때문.
# 글자 바로 아래(0~6pt)에 깔린 얇은 가로선을 찾아 그 위 글자들을 강조로 본다.
_UL_MAX_H = 2.0          # 선 두께 상한(pt) — 이보다 두꺼우면 밑줄이 아니라 도형/음영
_UL_MIN_W = 4.0          # 너무 짧은 선(점·기호)은 제외
_UL_GAP_MAX = 6.0        # 글자 아랫변에서 선까지 허용 거리(pt)
_UL_GAP_MIN = -1.5       # 글자와 살짝 겹치는 밑줄도 허용
_UL_PAGE_W_RATIO = 0.8   # 페이지 폭의 이 비율을 넘는 선은 머리말 구분선 등 → 제외
_UL_COVER = 0.5          # 글자 폭이 선과 이만큼 겹쳐야 밑줄로 인정
_UL_OPEN, _UL_CLOSE = "<!드러냄>", "<!/드러냄>"


def underline_rects(page) -> list:
    """페이지의 밑줄 후보 선(표시 좌표계 Rect)."""
    rot = page.rotation_matrix
    page_w = page.rect.width
    out = []
    for g in page.get_drawings():
        r = fitz.Rect(g["rect"]) * rot
        if r.height <= _UL_MAX_H and _UL_MIN_W <= r.width <= page_w * _UL_PAGE_W_RATIO:
            out.append(r)
    return out


def _is_underlined(cb, underlines) -> bool:
    """글자 bbox(표시 좌표)가 밑줄 위에 있는가."""
    w = cb.x1 - cb.x0
    if w <= 0:
        return False
    for u in underlines:
        gap = u.y0 - cb.y1
        if not (_UL_GAP_MIN <= gap <= _UL_GAP_MAX):
            continue
        overlap = min(cb.x1, u.x1) - max(cb.x0, u.x0)
        if overlap / w >= _UL_COVER:
            return True
    return False


def _line_text_with_word_gaps(line: dict, matrix=None, underlines=None) -> str:
    """rawdict 한 줄 → 글자 간격으로 어절 경계를 복원한 텍스트.

    공백 글리프가 실제로 있는 자리는 그대로 두고, 한글이 낀 글자쌍에서만
    '기준 간격(중앙값) + 임계'보다 벌어진 지점에 공백을 삽입한다.
    자간이 고르게 넓은 제목(트래킹)은 기준 간격 자체가 커져 오분리되지 않는다.

    matrix: 회전된 페이지의 rotation_matrix. rawdict 좌표는 회전 전 기준이라 270° 페이지에서는
    글자들이 세로로 늘어서 x 간격이 무의미해진다(어절 복원이 전멸). 표시 좌표로 옮겨서 잰다.
    """
    chars: list[tuple[str, float, float, float, bool]] = []  # (ch, x0, x1, size, underlined)
    for span in line.get("spans", []):
        size = float(span.get("size") or 0.0)
        for c in span.get("chars", []):
            bbox = c.get("bbox") or (0, 0, 0, 0)
            if matrix is not None:
                bbox = fitz.Rect(bbox) * matrix
            else:
                bbox = fitz.Rect(bbox)
            ul = bool(underlines) and _is_underlined(bbox, underlines)
            chars.append((c.get("c", ""), float(bbox[0]), float(bbox[2]), size, ul))
    if not chars:
        return ""

    # 간격 표본: 공백이 아닌 인접 글자쌍의 (다음 x0 - 이전 x1)
    gaps: list[float] = []
    for i in range(1, len(chars)):
        if chars[i - 1][0].isspace() or chars[i][0].isspace():
            continue
        gaps.append(chars[i][1] - chars[i - 1][2])
    have_base = len(gaps) >= _MIN_GAP_SAMPLES
    base = sorted(gaps)[len(gaps) // 2] if have_base else 0.0

    out: list[str] = []
    in_ul = False
    for i, (ch, x0, _x1, size, ul) in enumerate(chars):
        # 밑줄 구간 여닫이 (규정 제56항) — 공백에서 열지 않는다(마커가 어절 밖으로 새는 것 방지)
        if ul and not in_ul and not ch.isspace():
            out.append(_UL_OPEN)
            in_ul = True
        elif in_ul and not ul:
            out.append(_UL_CLOSE)
            in_ul = False
        if i and have_base:
            prev_ch, _px0, px1, _psize, _pul = chars[i - 1]
            if not ch.isspace() and not prev_ch.isspace() and (_is_hangul(ch) or _is_hangul(prev_ch)):
                threshold = base + max(_WORD_GAP_RATIO * (size or 10.0), _WORD_GAP_MIN_PT)
                if (x0 - px1) > threshold:
                    out.insert(len(out) - 1 if (ul and not _pul) else len(out), " ")
        out.append(ch)
    if in_ul:
        out.append(_UL_CLOSE)
    return "".join(out)


def _page_text_blocks_spaced(page) -> list[dict]:
    """페이지 텍스트 블록 추출(어절 경계 복원 포함) — get_text('blocks') 대체.

    반환 요소: {"content": str, "bbox": [x0,y0,x1,y1] (PyMuPDF 포인트)}.
    """
    raw = page.get_text("rawdict")
    rot = page.rotation_matrix
    uls = underline_rects(page)
    blocks: list[dict] = []
    for b in raw.get("blocks", []):
        if b.get("type") != 0:      # 0 = 텍스트 블록
            continue
        lines = [_line_text_with_word_gaps(ln, rot, uls) for ln in b.get("lines", [])]
        text = "\n".join(ln for ln in lines if ln).strip()
        if not text:
            continue
        blocks.append({"content": text, "bbox": list(b.get("bbox") or (0, 0, 0, 0))})
    return blocks


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
            for b in _page_text_blocks_spaced(page):
                x0, y0, x1, y1 = b["bbox"]
                blocks.append({
                    "content": b["content"],
                    "bbox": [round(x0 * 2), round(y0 * 2), round(x1 * 2), round(y1 * 2)],
                })
        finally:
            doc.close()
    finally:
        if tmp_path:
            os.unlink(tmp_path)
    return blocks, int(round(w * 2)), int(round(h * 2))


# 벡터 그림 판정(교과서 지도·도표·그래프는 임베디드 이미지가 아니라 벡터로 그려진다).
# 드로잉 프리미티브를 격자로 뭉친 덩어리가 아래 둘을 모두 넘으면 그림으로 본다.
# 실측 근거(세계사 p022 지도 2개 / 사회문화 p035·외국어 p012 그림 없음, 렌더 확인):
#   지도    = 4350개·면적 5.0% , 2669개·면적 3.4%
#   장식    = 글상자 둥근모서리·머리말 배너 → 덩어리 없음 또는 225개·면적 1.7%
_VEC_MIN_PRIMS = 200      # 덩어리 내 선/곡선 프리미티브 수
_VEC_MIN_AREA = 0.03      # 덩어리가 덮는 페이지 면적 비율
_VEC_GRID = 24            # 덩어리 병합용 격자 해상도


def _has_vector_figure(page) -> bool:
    """벡터로 그려진 그림(지도·도표·그래프)이 있으면 True.

    ★ 이게 없으면 교과서 지도가 통째로 사라진다. 지도는 임베디드 이미지가 아니라 벡터라
    get_image_info() 검사를 통과하지 못하고 ZERO(PyMuPDF)로 빠지는데, 그러면 (1) 그림이
    시각자료로 잡히지 않아 캡션도 대체텍스트도 없고 (2) 지도 안 라벨(황해·흉노 등)이 본문
    텍스트로 쏟아져 읽기순서를 흩뜨린다(세계사 order_tau 0.54의 주원인).

    장식(머리말 배너·둥근 글상자)과 구분하려고 '덩어리 크기 + 면적'을 함께 본다 — 장식은
    프리미티브가 적거나(<200) 면적이 작다(<3%).
    """
    W, H = page.rect.width, page.rect.height
    page_area = (W * H) or 1.0
    try:
        drawings = page.get_drawings()
    except Exception:  # noqa: BLE001
        return False
    if len(drawings) < 8:            # 밑줄·표선 몇 개는 그림이 아니다
        return False

    # 격자 셀별로 프리미티브 수와 bbox를 모은다.
    cells: dict[tuple[int, int], list] = {}
    for dr in drawings:
        n = len(dr.get("items", []))
        if not n:
            continue
        r = dr["rect"]
        key = (int((r[0] + r[2]) / 2 / W * _VEC_GRID), int((r[1] + r[3]) / 2 / H * _VEC_GRID))
        cell = cells.setdefault(key, [0, [1e9, 1e9, -1.0, -1.0]])
        cell[0] += n
        bb = cell[1]
        bb[0] = min(bb[0], r[0]); bb[1] = min(bb[1], r[1])
        bb[2] = max(bb[2], r[2]); bb[3] = max(bb[3], r[3])

    # 인접 셀을 이어붙여(8방향) 덩어리 단위로 판정.
    seen: set[tuple[int, int]] = set()
    for start in cells:
        if start in seen:
            continue
        stack, comp = [start], []
        while stack:
            c = stack.pop()
            if c in seen or c not in cells:
                continue
            seen.add(c)
            comp.append(c)
            x, y = c
            stack.extend([(x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1),
                          (x + 1, y + 1), (x - 1, y - 1), (x + 1, y - 1), (x - 1, y + 1)])
        prims = sum(cells[c][0] for c in comp)
        if prims < _VEC_MIN_PRIMS:
            continue
        bb = [1e9, 1e9, -1.0, -1.0]
        for c in comp:
            b = cells[c][1]
            bb[0] = min(bb[0], b[0]); bb[1] = min(bb[1], b[1])
            bb[2] = max(bb[2], b[2]); bb[3] = max(bb[3], b[3])
        if (bb[2] - bb[0]) * (bb[3] - bb[1]) > _VEC_MIN_AREA * page_area:
            return True
    return False


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
    return _has_vector_figure(page)     # 벡터 지도·도표·그래프


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
            # ZERO 후보면 어절 경계 복원 텍스트로 교체(공백 글리프 없는 교과서 PDF 대응)
            if len(text) >= MIN_TEXT_LENGTH and not has_visual:
                spaced = "\n".join(b["content"] for b in _page_text_blocks_spaced(page)).strip()
                text = spaced or text
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
