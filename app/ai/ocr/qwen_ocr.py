"""PART 4-1 — Qwen3-VL-8B 텍스트 OCR (GPU 0).

ZERO Tier  → pdf_text 직접 사용, Qwen 호출 없음
STANDARD/QUALITY → bbox 크롭 이미지 → Qwen3-VL-8B OCR → NFC 정규화 → symbol_rules 치환
"""

from __future__ import annotations

import asyncio
import io
import logging
import unicodedata
from typing import TYPE_CHECKING

from app.core.model_manager import model_manager
from app.schemas.content import ExtractedContent
from app.schemas.layout import BBoxItem, LayoutResult

if TYPE_CHECKING:
    from PIL import Image as PILImage

logger = logging.getLogger(__name__)

_OCR_TYPES = frozenset({"text", "title", "caption", "footnote", "sidebar", "list_item"})

_OCR_PROMPT = """OCR this text region image. Return ONLY the extracted Korean/English text.
Do NOT explain, do NOT add punctuation that is not visible.
If the text is vertical (rotated), read it top-to-bottom."""


def _crop(image: "PILImage", bbox: tuple) -> "PILImage":
    x1, y1, x2, y2 = bbox
    x1, y1 = max(0, x1), max(0, y1)
    x2, y2 = min(image.width, x2), min(image.height, y2)
    return image.crop((x1, y1, x2, y2))


def _qwen_ocr_sync(crop_img: "PILImage") -> tuple[str, float]:
    import torch
    model = model_manager.qwen_model
    processor = model_manager.qwen_processor
    messages = [{"role": "user", "content": [
        {"type": "image", "image": crop_img},
        {"type": "text",  "text": _OCR_PROMPT},
    ]}]
    text_input = processor.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
    inputs = processor(text=[text_input], images=[crop_img], return_tensors="pt").to("cuda:0")
    with torch.no_grad():
        output = model.generate(
            **inputs,
            max_new_tokens=512,
            do_sample=False,
            temperature=None,
            top_p=None,
            output_scores=True,
            return_dict_in_generate=True,
        )
    generated = output.sequences[0][inputs["input_ids"].shape[1]:]
    text = processor.decode(generated, skip_special_tokens=True).strip()

    if output.scores:
        import torch.nn.functional as F
        probs = [
            F.softmax(s[0], dim=-1)[tok.item()].item()
            for s, tok in zip(output.scores, generated)
            if tok.item() != processor.tokenizer.eos_token_id
        ]
        confidence = sum(probs) / max(len(probs), 1)
        confidence = min(max(confidence, 0.0), 1.0)
    else:
        confidence = 0.75
    return text, confidence


class QwenOCR:
    """LayoutResult + PIL.Image → ExtractedContent 목록."""

    async def process(
        self,
        layout: LayoutResult,
        page_image: "PILImage",
        routing_tier: str,
        zero_tier_text: str | None = None,
    ) -> list[ExtractedContent]:
        from app.ai.braille.symbol_rules import substitute_symbols

        target_elems = [e for e in layout.elements if e.type in _OCR_TYPES]
        results: list[ExtractedContent] = []

        if routing_tier == "ZERO" and zero_tier_text is not None:
            # ZERO Tier: 전체 페이지 텍스트를 첫 번째 요소에 할당
            for i, elem in enumerate(target_elems):
                results.append(ExtractedContent(
                    element_id=elem.element_id,
                    corrected_text=substitute_symbols(zero_tier_text) if i == 0 else "",
                    ocr_confidence=1.0,
                ))
            return results

        for elem in target_elems:
            result = await self._process_element(elem, page_image)
            results.append(result)
        return results

    async def _process_element(
        self, elem: BBoxItem, page_image: "PILImage"
    ) -> ExtractedContent:
        from app.ai.braille.symbol_rules import substitute_symbols
        flags: list[str] = []
        x1, y1, x2, y2 = elem.bbox
        w, h = max(x2 - x1, 1), max(y2 - y1, 1)
        if w / h < 0.3:
            flags += ["VERTICAL_TEXT", "R7"]

        try:
            crop_img = await asyncio.to_thread(_crop, page_image, elem.bbox)
            text, confidence = await asyncio.to_thread(_qwen_ocr_sync, crop_img)
        except Exception as exc:
            logger.warning("OCR 실패 element_id=%s: %s", elem.element_id, exc)
            return ExtractedContent(
                element_id=elem.element_id,
                corrected_text="[처리 불가: OCR 실패]",
                ocr_confidence=0.0,
                flags=["C2_FALLBACK"] + flags,
            )

        text = unicodedata.normalize("NFC", text)
        text = substitute_symbols(text)

        return ExtractedContent(
            element_id=elem.element_id,
            corrected_text=text or None,
            ocr_confidence=confidence,
            flags=flags,
        )
