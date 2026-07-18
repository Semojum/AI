"""
merged_layout + 캡셔닝 결과를 읽기 순서대로 병합하여
001_txt_result.json 생성.
debug=True 시 최종 order 기준 layout_viz.jpg를 test/results/page_{no:03d}/에 저장.
"""
import json
import re
import time
from pathlib import Path

import fitz
from PIL import Image, ImageDraw, ImageFont

from app.ai.captioning.captioner import caption
from app.ai.captioning.classifier import classify_with_confidence
from app.utils.logger import get_logger

logger = get_logger(__name__)

_VISUAL_TYPES = {"image", "cartoon", "chart_graph"}
_HF_TYPES = {"header_footer", "page_number"}
_TOP_Y_MAX = 200   # 0~1000 정규화 좌표 기준 상단 헤더 경계

VIZ_COLORS = {
    "title":         (220, 50,  50),
    "text":          (50,  120, 220),
    "formula":       (50,  180, 50),
    "table":         (220, 140, 50),
    "image":         (50,  200, 200),
    "chart":         (200, 100, 200),
    "caption":       (180, 100, 20),
    "list_item":     (180, 50,  180),
    "footnote":      (120, 120, 120),
    "header_footer": (80,  80,  160),
    "page_number":   (160, 160, 80),
}
DEFAULT_COLOR = (100, 100, 100)


def _reorder(elements: list[dict]) -> list[dict]:
    """
    header_footer/page_number를 상단/하단으로 분리.
    - y < _TOP_Y_MAX  → 맨 앞 (y 오름차순)
    - body            → MinerU 읽기 순서 유지
    - y >= _TOP_Y_MAX → 맨 뒤 (y 오름차순)
    """
    top, body, bottom = [], [], []
    for el in elements:
        if el["type"] in _HF_TYPES:
            y1 = el["bbox"][1]
            if y1 < _TOP_Y_MAX:
                top.append(el)
            else:
                bottom.append(el)
        else:
            body.append(el)

    top.sort(key=lambda e: e["bbox"][1])
    bottom.sort(key=lambda e: e["bbox"][1])
    return top + body + bottom


_CLASSIFY_TYPE_MAP = {
    "cartoon": "cartoon",
    "chart": "chart_graph",
    "image": "image",
}


# API 일시 장애(쿼터·타임아웃·네트워크)는 재시도. 그 외(인증·잘못된 이미지)는 즉시 포기.
_TRANSIENT_EXC = {"RateLimitError", "APITimeoutError", "APIConnectionError", "InternalServerError"}
_CAPTION_RETRIES = 2
_CAPTION_BACKOFF = 1.5   # 초, 지수 증가


def _do_caption(el: dict) -> tuple[str, str, bool, float | None]:
    """(캡션, 확정 타입, 성공여부, 세분류 신뢰도).

    ★ 실패 문자열을 본문으로 흘리지 않는다. 예전에는 "[캡셔닝 실패]"를 content로 반환해
    그 다섯 글자가 그대로 점자로 찍혀 학생에게 나갔다(품질검사도 못 잡아 COMPLETED 처리).
    실패는 빈 캡션 + 성공여부 False로만 알리고, 하위 opt가 규정상 '생략' 표기(§6.3.4(2)②)를
    내며 품질검사가 R11로 점역사에게 띄운다.
    세분류 신뢰도(logprob 기반)는 경계 JSON의 subtype_confidence로 나가 R2 판정에 쓰인다.
    """
    img_path = el.get("image_path")
    original_type = el.get("type", "image")
    eid = str(el.get("element_id", ""))[:8]

    if not img_path or not Path(img_path).exists():
        logger.warning("캡셔닝 불가 — 이미지 경로 없음 id=%s path=%r", eid, img_path)
        return "", original_type, False, None

    last: Exception | None = None
    for attempt in range(_CAPTION_RETRIES + 1):
        try:
            image_type, subconf = classify_with_confidence(img_path)
            mapped_type = _CLASSIFY_TYPE_MAP.get(image_type, "image")
            return caption(img_path, image_type), mapped_type, True, subconf
        except Exception as exc:  # noqa: BLE001 — 요소 격리(불변규칙 3)
            last = exc
            if type(exc).__name__ not in _TRANSIENT_EXC or attempt == _CAPTION_RETRIES:
                break
            time.sleep(_CAPTION_BACKOFF * (2 ** attempt))

    # 삼키지 않는다 — 원인(쿼터 소진·인증 실패 등)이 로그에 남아야 운영에서 추적된다.
    logger.error("캡셔닝 실패 id=%s: %s: %s", eid, type(last).__name__, last)
    return "", original_type, False, None


def _render_page(pdf_path: str, page_no: int) -> Image.Image:
    doc = fitz.open(str(pdf_path))
    # pdf_data는 단일 페이지 PDF(proto 계약). page_no는 원본 페이지 번호이므로
    # 페이지 수에 맞게 클램프(단일=0, 멀티=page_no-1) — 범위 초과 방지.
    page_idx = max(0, min(page_no - 1, doc.page_count - 1))
    pix = doc[page_idx].get_pixmap(matrix=fitz.Matrix(2, 2))
    img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
    doc.close()
    return img


def _viz_page(page_img: Image.Image, elements: list[dict]) -> Image.Image:
    img = page_img.copy().convert("RGB")
    draw = ImageDraw.Draw(img, "RGBA")
    try:
        font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 13)
    except Exception:
        font = ImageFont.load_default()

    for el in elements:
        bb = el.get("bbox_px", el["bbox"])
        color = VIZ_COLORS.get(el["type"], DEFAULT_COLOR)
        draw.rectangle(bb, fill=(*color, 35), outline=(*color, 200), width=2)
        lbl = f"{el['final_order']} {el['type']}"[:14]
        tx, ty = bb[0] + 2, max(0, bb[1] - 15)
        draw.rectangle([tx - 1, ty - 1, tx + len(lbl) * 7 + 2, ty + 14], fill=(*color, 170))
        draw.text((tx, ty), lbl, fill=(255, 255, 255), font=font)
    return img


_TEXTUAL_TYPES = {"text", "title", "list_item", "caption", "footnote", "sidebar"}
# 문항 번호는 큰 글씨/색 상자로 조판돼 있어 MinerU가 **앞 문항 본문 끝**에 붙여 내보낸다
# ("…고른 것은?\n02"). 그대로 두면 번호가 엉뚱한 문항에 붙어 점역된다 → 다음 텍스트 요소 앞으로
# 옮긴다(정답 배치 = "02. 다음은…"). dev 18p에서 14건.
_TRAILING_QNUM_RE = re.compile(r"\n\s*(\d{1,2})\s*$")


def _move_trailing_qnum(ordered: list[dict]) -> None:
    """앞 요소 끝에 붙은 다음 문항 번호를 다음 텍스트 요소 앞으로 옮긴다(제자리 수정)."""
    for i, el in enumerate(ordered[:-1]):
        if el.get("type") not in _TEXTUAL_TYPES:
            continue
        text = (el.get("content") or "").rstrip()
        m = _TRAILING_QNUM_RE.search(text)
        if not m or len(text) < 10:
            continue
        nxt = ordered[i + 1]
        if nxt.get("type") not in _TEXTUAL_TYPES:
            continue
        el["content"] = text[: m.start()].rstrip()
        nxt["content"] = f"{m.group(1)}\n{(nxt.get('content') or '').lstrip()}"


_CAPTIONABLE = _VISUAL_TYPES | {"table"}   # 캡션이 가리킬 수 있는 시각요소


def _link_captions(elements: list[dict]) -> None:
    """caption 요소 → 가장 가까운 시각요소(그림/표/차트)에 caption_ref 연결(공간 근접).

    캡션은 보통 대상 그림/표 바로 아래·위에 붙는다. bbox 세로 중심 거리가 가장 가까운
    시각요소를 대상으로 본다. bbox 없거나 시각요소 없으면 빈 값 유지.
    """
    visuals = [e for e in elements if e["type"] in _CAPTIONABLE and e.get("bbox")]
    if not visuals:
        return
    for cap in elements:
        if cap["type"] != "caption" or not cap.get("bbox"):
            continue
        cb = cap["bbox"]
        cy = (cb[1] + cb[3]) / 2
        best, best_d = None, float("inf")
        for v in visuals:
            vb = v["bbox"]
            d = abs(cy - (vb[1] + vb[3]) / 2)
            if d < best_d:
                best, best_d = v, d
        if best:
            cap["caption_ref"] = best["id"]


def build(
    merged_layout: list[dict],
    job_id: str,
    page_no: int,
    extraction_method: str,
    debug: bool = False,
    pdf_path: str | None = None,
) -> dict:
    """
    merged_layout: mineru_runner.run() 반환값 (bbox_px 포함)
    반환: 001_txt_result.json 내용 (dict)
    """
    ordered = _reorder(list(merged_layout))
    _move_trailing_qnum(ordered)

    elements = []
    order = 1
    for el in ordered:
        caption_failed = False
        subconf: float | None = None
        if el["type"] in _VISUAL_TYPES:
            # 시각요소별 캡셔닝(GPT-4o 분류+설명) 소요시간 로깅 — "이미지당 몇 초" 디버깅용.
            _t = time.monotonic()
            content, el_type, ok, subconf = _do_caption(el)
            caption_failed = not ok
            logger.info("    캡셔닝 %s(%s→%s) %.1fs%s", str(el.get("element_id", ""))[:8],
                        el["type"], el_type, time.monotonic() - _t, "" if ok else " [실패]")
        else:
            content = el.get("content", "")
            el_type = el["type"]

        # ★ 캡셔닝이 실패한 시각요소는 버리지 않는다. 요소째 사라지면 학생은 거기 그림이
        # 있었다는 사실조차 모른다(불변규칙 1 빈 결과 금지). 빈 캡션 + CAPTION_FAILED로
        # 넘기면 opt가 '생략' 표기를 내고 품질검사가 R11로 점역사에게 띄운다.
        if not content.strip() and not caption_failed:
            continue

        # element_id를 그대로 사용 (새 UUID 생성 안 함)
        # ★경계 bbox는 0~1000 정규화로 통일(2026-07-19). 구판이 rect×2 픽셀(bbox_px)을
        #   "bbox"로 저장해, 0~1000을 가정하는 소비처(수식 crop·opus_extract·caption 링크)가
        #   전부 어긋났다 — 수학2 p008 실측: 원본 y=556이 820으로 저장돼 crop이 다른 수식을
        #   가리킴. MinerU 경로(bbox_px 존재)는 원본 정규화 bbox를 쓰고, 그 외 경로는 종전 유지.
        if el.get("bbox_px") and el.get("bbox"):
            bbox_out = el["bbox"]                    # 0~1000 원본
        else:
            bbox_out = el.get("bbox_px") or el.get("bbox")
        entry = {
            "id": el["element_id"],
            "order": order,
            "type": el_type,
            "content": content,
            "bbox": [int(round(v)) for v in bbox_out] if bbox_out else None,
            "caption_ref": "",   # 아래 _link_captions가 채움
            "flags": ["CAPTION_FAILED"] if caption_failed else [],
        }
        if subconf is not None:
            entry["subtype_confidence"] = subconf
        elements.append(entry)

        if debug:
            el["final_order"] = order  # viz용 임시 필드

        order += 1

    _link_captions(elements)

    # 페이지 크기(2x 렌더 픽셀) — 요소들이 공유. bbox와 같은 좌표계로 BE/FE 매핑용.
    page_w = next((el.get("page_width") for el in ordered if el.get("page_width")), 0)
    page_h = next((el.get("page_height") for el in ordered if el.get("page_height")), 0)

    if debug and pdf_path:
        debug_dir = Path("storage") / "jobs" / job_id / "temp" / f"page_{page_no:03d}"
        debug_dir.mkdir(parents=True, exist_ok=True)
        page_img = _render_page(pdf_path, page_no)
        viz = _viz_page(page_img, ordered)
        viz.save(debug_dir / "layout_viz.jpg", quality=90)

    result = {
        "meta": {
            "job_id": job_id,
            "page_no": page_no,
            "extraction_method": extraction_method,
            "image_width": page_w,
            "image_height": page_h,
        },
        "elements": elements,
    }

    out_path = (
        Path("storage") / "jobs" / job_id / "temp"
        / f"page_{page_no:03d}" / "data" / f"{page_no:03d}_txt_result.json"
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    print(f"[result_builder] {out_path} 저장 ({len(elements)}개 요소)")
    return result
