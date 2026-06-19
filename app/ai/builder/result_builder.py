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

_VISUAL_TYPES = {"image", "cartoon", "chart"}
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


def _do_caption(el: dict) -> str:
    img_path = el.get("image_path")
    if not img_path or not Path(img_path).exists():
        return "[이미지 경로 없음]"
    try:
        image_type = classify(img_path)
        return caption(img_path, image_type)
    except Exception:
        return "[캡셔닝 실패]"


def _render_page(pdf_path: str, page_no: int) -> Image.Image:
    doc = fitz.open(str(pdf_path))
    pix = doc[page_no - 1].get_pixmap(matrix=fitz.Matrix(2, 2))
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
            content = _do_caption(el)
        else:
            content = el.get("content", "")

        if not content.strip():
            continue

        # element_id를 그대로 사용 (새 UUID 생성 안 함)
        elements.append({
            "id": el["element_id"],
            "order": order,
            "type": el["type"],
            "content": content,
        })

        if debug:
            el["final_order"] = order  # viz용 임시 필드

        order += 1

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
