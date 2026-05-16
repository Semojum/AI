"""파이프라인 진입점.

단계 2 구현: PART 2 → 3 → 4-1 → 4-2 → 4-3 → 10

  mode a: PART 2 → 3 → 4-1 → 4-2          (text_list 반환)
  mode b: source_text → 4-2 → 4-3 → 10    (braille_text_list 반환)
  mode c: PART 2 → 3 → 4-1 → 4-2 → 4-3 → 10  (양쪽 반환)
"""

from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path
from uuid import uuid4

from app.core.config import config
from app.schemas.content import BrailleOutput, ExtractedContent, LLMOutput
from app.schemas.layout import BBoxItem, DocumentMeta, LayoutResult
from app.schemas.quality import CriticalError, QualityReport
from app.schemas.task import PageTask
from app.utils.logger import get_logger

logger = get_logger(__name__)


# ── 응답 빌더 ─────────────────────────────────────────────────────────────

def _build_timeout_response(task: PageTask, elapsed_ms: int) -> dict:
    return {
        "job_id": task.job_id,
        "status": "BLOCKED",
        "page_number": task.page_no,
        "processing_meta": {
            "processing_time_ms": elapsed_ms,
            "pdf_layer_confidence": 0.0,
            "routing_tier_used": "UNKNOWN",
            "scan_only": False,
        },
        "quality_report": QualityReport(
            page_id=f"p_{task.page_no:03d}",
            status="BLOCKED",
            critical_errors=[CriticalError(
                type="C7",
                element_id="page",
                message=f"180초 타임아웃 초과 ({elapsed_ms}ms)",
            )],
        ).model_dump(),
    }


def _build_exception_response(task: PageTask, elapsed_ms: int, exc: Exception) -> dict:
    return {
        "job_id": task.job_id,
        "status": "BLOCKED",
        "page_number": task.page_no,
        "processing_meta": {
            "processing_time_ms": elapsed_ms,
            "pdf_layer_confidence": 0.0,
            "routing_tier_used": "UNKNOWN",
            "scan_only": False,
        },
        "quality_report": QualityReport(
            page_id=f"p_{task.page_no:03d}",
            status="BLOCKED",
            critical_errors=[CriticalError(
                type="C1",
                element_id="page",
                message=f"파이프라인 예외: {type(exc).__name__}: {exc}",
            )],
        ).model_dump(),
    }


def _debug_dump(task: PageTask, part_name: str, data: dict | list) -> None:
    if not config.is_debug:
        return
    dump_dir = Path(f"storage/jobs/{task.job_id}/temp/page_{task.page_no:03d}")
    dump_dir.mkdir(parents=True, exist_ok=True)
    (dump_dir / f"{part_name}.json").write_text(
        json.dumps(data, ensure_ascii=False, indent=2, default=str)
    )


# ── 파이프라인 실행 ──────────────────────────────────────────────────────

async def _run_pipeline(task: PageTask) -> dict:
    page_id = f"p_{task.page_no:03d}"

    doc_meta: DocumentMeta | None = None
    page_image = None
    layout_result: LayoutResult | None = None
    extracted_texts: list[ExtractedContent] = []
    llm_outputs: list[LLMOutput] = []
    braille_outputs: list[BrailleOutput] = []
    image_width = 0
    image_height = 0
    zero_text: str | None = None

    # ── mode a, c: VLM 전체 파이프라인 ─────────────────────────────────
    if task.mode in ("a", "c"):

        # PART 2: 전처리 — 신뢰도 산출 + 라우팅 티어 결정
        from app.ai.preprocessor.pdf_analyzer import analyze_pdf
        from app.ai.preprocessor.converter import convert_page

        doc_meta, zero_text = await asyncio.to_thread(
            analyze_pdf, task.pdf_data, task.page_no - 1, task.job_id
        )
        _debug_dump(task, "02_doc_meta", doc_meta.model_dump())

        if doc_meta.routing_tier != "ZERO":
            page_image = await asyncio.to_thread(
                convert_page,
                task.pdf_data, task.page_no - 1,
                doc_meta.routing_tier, task.job_id, task.page_no,
            )
            image_width = page_image.width
            image_height = page_image.height

        # PART 3: 레이아웃 탐지 + 병합
        if doc_meta.routing_tier == "ZERO":
            dummy = BBoxItem(
                element_id=uuid4(), type="text",
                bbox=(0, 0, 1240, 1754), reading_order=1,
            )
            layout_result = LayoutResult(page_id=page_id, elements=[dummy])
        else:
            from app.ai.layout.qwen_layout import QwenLayout
            from app.ai.layout.yolo_layout import YoloLayout
            from app.ai.layout.layout_merger import LayoutMerger

            qwen_items, yolo_hints = await asyncio.gather(
                asyncio.to_thread(QwenLayout().detect, page_image),
                asyncio.to_thread(YoloLayout().detect, page_image),
            )
            layout_result = await asyncio.to_thread(
                LayoutMerger().merge,
                qwen_items, yolo_hints, task.job_id, task.page_no,
                image_width or 1240, image_height or 1754,
            )
            layout_result.page_id = page_id
            _debug_dump(task, "03_layout", layout_result.model_dump())

        # PART 4-1: OCR
        from app.ai.ocr.qwen_ocr import QwenOCR

        extracted_texts = await QwenOCR().process(
            layout_result, page_image, doc_meta.routing_tier, zero_text
        )
        _debug_dump(task, "04_ocr", [e.model_dump() for e in extracted_texts])

    # ── mode b: source_text → 가상 요소 구성 ────────────────────────────
    elif task.mode == "b":
        dummy = BBoxItem(
            element_id=uuid4(), type="text",
            bbox=(0, 0, 1240, 1754), reading_order=1,
        )
        layout_result = LayoutResult(page_id=page_id, elements=[dummy])
        extracted_texts = [ExtractedContent(
            element_id=dummy.element_id,
            corrected_text=task.source_text or "",
            ocr_confidence=1.0,
        )]

    # ── PART 4-2: 텍스트 점역 최적화 ─────────────────────────────────
    routing_tier = doc_meta.routing_tier if doc_meta else "STANDARD"
    if extracted_texts:
        from app.ai.llm.text_opt import TextOpt

        llm_outputs = await TextOpt().optimize(extracted_texts, routing_tier, layout_result)
        _debug_dump(task, "04_text_opt", [o.model_dump() for o in llm_outputs])

    # ── PART 4-3 + 10: 점자 변환 + 조판 ─────────────────────────────
    if task.mode in ("b", "c") and llm_outputs:
        from app.ai.braille.text_braille import TextBraille
        from app.ai.braille.layout_braille import LayoutBraille

        braille_outputs = TextBraille().translate(llm_outputs)
        _debug_dump(task, "04_braille", [b.model_dump() for b in braille_outputs])

        LayoutBraille().layout(braille_outputs, task.page_no, task.job_id)

    # ── 응답 조립 ─────────────────────────────────────────────────────
    elem_by_id = {
        e.element_id: e
        for e in (layout_result.elements if layout_result else [])
    }
    braille_by_id = {b.element_id: b for b in braille_outputs}

    response: dict = {
        "job_id": task.job_id,
        "status": "COMPLETED",
        "page_number": task.page_no,
        "processing_meta": {
            "processing_time_ms": 0,
            "pdf_layer_confidence": doc_meta.pdf_confidence if doc_meta else 0.0,
            "routing_tier_used": routing_tier,
            "scan_only": doc_meta.scan_only if doc_meta else False,
        },
        "quality_report": QualityReport(
            page_id=page_id, status="COMPLETED"
        ).model_dump(),
    }

    if task.mode in ("a", "c"):
        response["image_width"] = image_width
        response["image_height"] = image_height
        response["bounding_box_list"] = [
            {
                "id": str(e.element_id),
                "type": e.type,
                "bbox": list(e.bbox),
                "reading_order": e.reading_order,
                "heading_level": e.heading_level or 0,
                "caption_ref": str(e.caption_ref) if e.caption_ref else "",
                "flags": e.flags,
            }
            for e in (layout_result.elements if layout_result else [])
        ]
        response["text_list"] = [
            {
                "id": str(o.element_id),
                "type": elem_by_id.get(o.element_id, _DUMMY_ELEM).type,
                "order": i + 1,
                "heading_level": getattr(
                    elem_by_id.get(o.element_id), "heading_level", None
                ) or 0,
                "ocr_confidence": _get_ocr_confidence(o.element_id, extracted_texts),
                "tn_text": o.tn_text or "",
                "is_blocked": "[처리 불가" in o.corrected_text,
                "render_mode": o.render_mode,
                "contents": [o.corrected_text],
                "rule_trail": [r.model_dump() for r in o.rule_trail],
            }
            for i, o in enumerate(llm_outputs)
        ]

    if task.mode in ("b", "c") and llm_outputs:
        response["braille_text_list"] = [
            {
                "id": str(o.element_id),
                "type": elem_by_id.get(o.element_id, _DUMMY_ELEM).type,
                "order": i + 1,
                "heading_level": 0,
                "ocr_confidence": _get_ocr_confidence(o.element_id, extracted_texts),
                "tn_text": o.tn_text or "",
                "is_blocked": "[처리 불가" in o.corrected_text,
                "render_mode": "text_only",
                "contents": braille_by_id[o.element_id].braille_lines
                if o.element_id in braille_by_id else [],
                "rule_trail": [
                    r.model_dump()
                    for r in (
                        braille_by_id[o.element_id].rule_trail
                        if o.element_id in braille_by_id
                        else o.rule_trail
                    )
                ],
            }
            for i, o in enumerate(llm_outputs)
        ]

    return response


# ── 유틸 ─────────────────────────────────────────────────────────────────

def _get_ocr_confidence(element_id, extracted_texts: list[ExtractedContent]) -> float:
    for e in extracted_texts:
        if e.element_id == element_id:
            return e.ocr_confidence
    return 0.0


class _DummyElem:
    type = "text"
    heading_level = None


_DUMMY_ELEM = _DummyElem()


# ── 파이프라인 진입점 ─────────────────────────────────────────────────────

async def run(task: PageTask) -> dict:
    """파이프라인 진입점. 180초 하드 타임아웃 강제."""
    start = time.monotonic()
    try:
        result = await asyncio.wait_for(
            _run_pipeline(task),
            timeout=config.page_timeout_seconds,
        )
        elapsed_ms = int((time.monotonic() - start) * 1000)
        result["processing_meta"]["processing_time_ms"] = elapsed_ms
        logger.info(
            "pipeline completed job=%s page=%d mode=%s elapsed=%dms",
            task.job_id, task.page_no, task.mode, elapsed_ms,
        )
        return result

    except asyncio.TimeoutError:
        elapsed_ms = int((time.monotonic() - start) * 1000)
        logger.warning("pipeline timeout job=%s page=%d elapsed=%dms",
                       task.job_id, task.page_no, elapsed_ms)
        return _build_timeout_response(task, elapsed_ms)

    except Exception as exc:
        elapsed_ms = int((time.monotonic() - start) * 1000)
        logger.exception("pipeline error job=%s page=%d: %s",
                         task.job_id, task.page_no, exc)
        return _build_exception_response(task, elapsed_ms, exc)
