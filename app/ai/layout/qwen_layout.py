"""PART 3 — Qwen3-VL-8B 레이아웃 감지 (GPU 0).

11종 요소를 JSON 배열로 반환:
text | title | caption | table | image | formula |
list_item | header_footer | page_number | footnote | sidebar
"""

from __future__ import annotations

import json
import logging
import re
from typing import TYPE_CHECKING

from app.core.model_manager import model_manager

if TYPE_CHECKING:
    from PIL import Image as PILImage

logger = logging.getLogger(__name__)

_VALID_TYPES = frozenset({
    "text", "title", "caption", "table", "image", "formula",
    "list_item", "header_footer", "page_number", "footnote", "sidebar",
})

_LAYOUT_PROMPT = """Analyze this Korean textbook page image. Return ALL elements as a JSON array.
For each element provide:
- type: one of text|title|caption|table|image|formula|list_item|header_footer|page_number|footnote|sidebar
- bbox: [x1, y1, x2, y2] in pixels
- heading_level: 1, 2, or 3 for title elements, null otherwise

Return ONLY a valid JSON array. No explanation. No markdown.
Example: [{"type":"title","bbox":[10,20,500,60],"heading_level":1},{"type":"text","bbox":[10,70,500,200],"heading_level":null}]"""


def _parse_json(raw: str) -> list[dict]:
    raw = raw.strip()
    raw = re.sub(r"```(?:json)?", "", raw).strip("` \n")
    start, end = raw.find("["), raw.rfind("]")
    if start == -1 or end == -1:
        return []
    try:
        return json.loads(raw[start:end + 1])
    except json.JSONDecodeError:
        return []


def _run_inference(image: "PILImage", prompt: str) -> str:
    import torch
    model = model_manager.qwen_model
    processor = model_manager.qwen_processor
    messages = [{"role": "user", "content": [
        {"type": "image", "image": image},
        {"type": "text",  "text": prompt},
    ]}]
    text_input = processor.apply_chat_template(
        messages, tokenize=False, add_generation_prompt=True
    )
    inputs = processor(text=[text_input], images=[image], return_tensors="pt").to("cuda:0")
    with torch.no_grad():
        out = model.generate(**inputs, max_new_tokens=2048, do_sample=False,
                             temperature=None, top_p=None)
    generated = out[0][inputs["input_ids"].shape[1]:]
    return processor.decode(generated, skip_special_tokens=True)


class QwenLayout:
    """페이지 이미지 → raw 레이아웃 항목 목록."""

    def detect(self, image: "PILImage") -> list[dict]:
        raw = _run_inference(image, _LAYOUT_PROMPT)
        items = _parse_json(raw)
        if not items:
            logger.warning("QwenLayout: JSON 파싱 실패. 재시도.")
            raw = _run_inference(image, _LAYOUT_PROMPT)
            items = _parse_json(raw)
        if not items:
            raise ValueError("QwenLayout 탐지 결과 없음 — C1 처리 필요")

        validated = []
        for item in items:
            t = item.get("type", "text")
            if t not in _VALID_TYPES:
                t = "text"
            bbox_raw = item.get("bbox", [0, 0, 100, 100])
            bbox = [int(x) for x in bbox_raw[:4]]
            if len(bbox) < 4:
                bbox = [0, 0, 100, 100]
            validated.append({
                "type": t,
                "bbox": bbox,
                "heading_level": item.get("heading_level"),
            })
        return validated
