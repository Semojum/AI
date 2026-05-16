"""PART 3 — DocLayout-YOLO v2 보조 감지 (GPU 0).

신뢰도 0.5 이상 탐지 결과를 bbox 힌트로 반환.
YOLO 모델 미로드 시 빈 목록 반환 (보조 역할이므로 파이프라인 계속).
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from app.core.model_manager import model_manager

if TYPE_CHECKING:
    from PIL import Image as PILImage

logger = logging.getLogger(__name__)

_CONF_THRESHOLD = 0.5

_YOLO_TYPE_MAP = {
    0: "title", 1: "text", 2: "header_footer", 3: "figure_caption",
    4: "formula", 5: "table", 6: "list_item", 7: "image",
}


class YoloLayout:
    """페이지 이미지 → YOLO bbox 힌트 목록."""

    def detect(self, image: "PILImage") -> list[dict]:
        yolo = model_manager.yolo_model
        if yolo is None:
            return []
        try:
            import numpy as np
            arr = np.array(image)
            results = yolo(arr, device="cuda:0", verbose=False)
            hints = []
            for r in results:
                for box in r.boxes:
                    if float(box.conf) < _CONF_THRESHOLD:
                        continue
                    cls_id = int(box.cls)
                    elem_type = _YOLO_TYPE_MAP.get(cls_id, "text")
                    # caption → caption, figure_caption → caption
                    if elem_type == "figure_caption":
                        elem_type = "caption"
                    x1, y1, x2, y2 = [int(v) for v in box.xyxy[0].tolist()]
                    hints.append({"type": elem_type, "bbox": [x1, y1, x2, y2],
                                  "conf": float(box.conf)})
            return hints
        except Exception as exc:
            logger.warning("YoloLayout 감지 실패 (계속 진행): %s", exc)
            return []
