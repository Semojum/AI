"""
merged_layout + 캡셔닝 결과를 읽기 순서대로 병합하여
001_txt_result.json 생성.
debug=True 시 최종 order 기준 layout_viz.jpg를 test/results/page_{no:03d}/에 저장.
"""
import json
from pathlib import Path

import fitz
from PIL import Image, ImageDraw, ImageFont

from app.ai.captioning.captioner import caption
from app.ai.captioning.classifier import classify

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


def _do_caption(el: dict) -> tuple[str, str]:
    img_path = el.get("image_path")
    original_type = el.get("type", "image")
    if not img_path or not Path(img_path).exists():
        return "[이미지 경로 없음]", original_type
    try:
        image_type = classify(img_path)
        mapped_type = _CLASSIFY_TYPE_MAP.get(image_type, "image")
        return caption(img_path, image_type), mapped_type
    except Exception:
        return "[캡셔닝 실패]", original_type


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

    elements = []
    order = 1
    for el in ordered:
        if el["type"] in _VISUAL_TYPES:
            content, el_type = _do_caption(el)
        else:
            content = el.get("content", "")
            el_type = el["type"]

        if not content.strip():
            continue

        # element_id를 그대로 사용 (새 UUID 생성 안 함)
        # bbox는 픽셀 좌표(bbox_px, 2x 렌더 기준)로 BE에 전달 — 없으면 0~1000 정규화 bbox.
        bbox_px = el.get("bbox_px") or el.get("bbox")
        elements.append({
            "id": el["element_id"],
            "order": order,
            "type": el_type,
            "content": content,
            "bbox": [int(round(v)) for v in bbox_px] if bbox_px else None,
            "caption_ref": "",   # 아래 _link_captions가 채움
        })

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
