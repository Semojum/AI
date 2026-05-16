"""PART 3 — IoU 병합 + caption_ref 연결 + reading_order 배정.

Qwen3-VL 결과(주) + YOLO 결과(보조)를 IoU 기준으로 병합하여
LayoutResult를 생성하고 merged_layout.json을 저장한다.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from uuid import uuid4

from app.schemas.layout import BBoxItem, LayoutResult

_IOU_THRESHOLD = 0.5
_CAPTION_Y_MARGIN = 60  # px
_CAPTION_RE = re.compile(r"(그림|표|Fig\.?|Table)\s*\d+", re.IGNORECASE)


def _iou(a: list[int], b: list[int]) -> float:
    ax1, ay1, ax2, ay2 = a
    bx1, by1, bx2, by2 = b
    ix1 = max(ax1, bx1); iy1 = max(ay1, by1)
    ix2 = min(ax2, bx2); iy2 = min(ay2, by2)
    inter = max(0, ix2 - ix1) * max(0, iy2 - iy1)
    if inter == 0:
        return 0.0
    area_a = (ax2 - ax1) * (ay2 - ay1)
    area_b = (bx2 - bx1) * (by2 - by1)
    return inter / (area_a + area_b - inter)


def _assign_reading_order(items: list[dict], img_width: int) -> list[dict]:
    """2단 레이아웃 판별 후 reading_order 할당."""
    if not items:
        return items
    col_mid = img_width / 2
    left = [b for b in items if b["bbox"][0] < col_mid * 0.6]
    right = [b for b in items if b["bbox"][0] >= col_mid * 0.6]
    if left and right and len(right) > 1:
        ordered = sorted(left, key=lambda b: b["bbox"][1]) + sorted(right, key=lambda b: b["bbox"][1])
    else:
        ordered = sorted(items, key=lambda b: b["bbox"][1])
    for i, item in enumerate(ordered, start=1):
        item["reading_order"] = i
    return ordered


def _link_captions(items: list[dict]) -> list[dict]:
    """캡션 요소를 nearest image/table 요소에 caption_ref로 연결."""
    captions = [i for i in items if i["type"] == "caption"]
    targets  = [i for i in items if i["type"] in ("image", "table", "formula")]
    for cap in captions:
        cy_center = (cap["bbox"][1] + cap["bbox"][3]) / 2
        best, best_dist = None, float("inf")
        for tgt in targets:
            ty_center = (tgt["bbox"][1] + tgt["bbox"][3]) / 2
            dist = abs(cy_center - ty_center)
            if dist < best_dist and dist < 300:
                best, best_dist = tgt, dist
        if best:
            cap["caption_ref"] = best["element_id"]
    return items


class LayoutMerger:
    def merge(
        self,
        qwen_items: list[dict],
        yolo_hints: list[dict],
        job_id: str,
        page_no: int,
        img_width: int = 1240,
        img_height: int = 1754,
    ) -> LayoutResult:
        # 모든 항목에 element_id 부여
        for item in qwen_items:
            item.setdefault("element_id", str(uuid4()))
        for hint in yolo_hints:
            hint.setdefault("element_id", str(uuid4()))

        # IoU 기반 중복 제거: YOLO 힌트 중 Qwen 결과와 IoU > threshold인 것 스킵
        merged = list(qwen_items)
        for hint in yolo_hints:
            duplicate = any(_iou(hint["bbox"], q["bbox"]) > _IOU_THRESHOLD for q in qwen_items)
            if not duplicate:
                merged.append(hint)

        merged = _assign_reading_order(merged, img_width)
        merged = _link_captions(merged)

        elements = []
        for item in merged:
            bbox_raw = item["bbox"]
            bbox = tuple(int(x) for x in bbox_raw[:4])
            caption_ref_str = item.get("caption_ref")
            from uuid import UUID
            try:
                caption_ref = UUID(caption_ref_str) if caption_ref_str else None
            except ValueError:
                caption_ref = None

            flags: list[str] = []
            if item.get("type") == "text" and item.get("scan_only"):
                flags.append("SCAN_DOCUMENT")
            x1, y1, x2, y2 = bbox
            w, h = max(x2 - x1, 1), max(y2 - y1, 1)
            if (w / h) < 0.3:
                flags.append("VERTICAL_TEXT")

            elements.append(BBoxItem(
                element_id=item.get("element_id") and __import__("uuid").UUID(item["element_id"]),
                type=item.get("type", "text"),
                bbox=bbox,
                reading_order=item.get("reading_order", 9999),
                heading_level=item.get("heading_level"),
                caption_ref=caption_ref,
                flags=flags,
            ))

        page_id = f"p_{page_no:03d}"
        layout = LayoutResult(page_id=page_id, elements=elements)

        # 중간 산출물 저장
        out_dir = Path(f"storage/jobs/{job_id}/temp/page_{page_no:03d}/layout")
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "merged_layout.json").write_text(
            json.dumps(
                [{"element_id": str(e.element_id), "type": e.type,
                  "bbox": list(e.bbox), "reading_order": e.reading_order,
                  "heading_level": e.heading_level,
                  "caption_ref": str(e.caption_ref) if e.caption_ref else None,
                  "flags": e.flags}
                 for e in elements],
                ensure_ascii=False, indent=2
            ),
            encoding="utf-8"
        )
        return layout
