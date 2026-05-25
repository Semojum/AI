"""파이프라인 진입점.

단계 3 구현: 6-체인 asyncio.gather 병렬 실행

  mode a: PART 2 → 3 → 3-4 → 6-체인-opt      (text_list 반환)
  mode b: source_text → 4-2 → 4-3 → 10        (braille_text_list 반환)
  mode c: PART 2 → 3 → 3-4 → 6-체인 → 10      (양쪽 반환)
"""

from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path
from typing import Optional
from uuid import UUID, uuid4

from app.core.config import config
from app.schemas.content import BrailleOutput, ExtractedContent, LLMOutput
from app.schemas.layout import BBoxItem, DocumentMeta, LayoutResult
from app.schemas.quality import CriticalError, QualityReport
from app.schemas.task import PageTask
from app.utils.logger import get_logger

logger = get_logger(__name__)

# 텍스트 요소 유형 — QwenOCR이 처리하는 요소들
_TEXT_TYPES = {"text", "title", "caption", "list_item", "footnote", "sidebar", "header_footer", "page_number"}

ChainResult = tuple[list[ExtractedContent], list[LLMOutput], list[BrailleOutput]]


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


def _crop_element(page_image: "PIL.Image.Image", elem: BBoxItem) -> "PIL.Image.Image":
    x1, y1, x2, y2 = elem.bbox
    return page_image.crop((x1, y1, x2, y2))


def _placeholder_extracted(elem: BBoxItem, reason: str, flag: str) -> ExtractedContent:
    return ExtractedContent(
        element_id=elem.element_id,
        corrected_text=f"[처리 불가: {reason}]",
        ocr_confidence=0.0,
        flags=[flag],
    )


# ── 6-체인 개별 구현 ─────────────────────────────────────────────────────

async def _run_text_chain(
    layout: LayoutResult,
    page_image: Optional["PIL.Image.Image"],
    doc_meta: Optional[DocumentMeta],
    routing_tier: str,
    task: PageTask,
    include_braille: bool,
    zero_text: Optional[str],
) -> ChainResult:
    text_elems = [e for e in layout.elements if e.type in _TEXT_TYPES]
    # ZERO 티어는 dummy 텍스트 요소를 항상 가지므로 empty 체크는 ZERO 이외에서만 의미있음
    if not text_elems:
        return [], [], []

    # QwenOCR에는 텍스트 타입 요소만 전달 — formula/table/image가 섞이면 다른 체인과 element_id 중복
    text_only_layout = LayoutResult(page_id=layout.page_id, elements=text_elems)

    from app.ai.ocr.qwen_ocr import QwenOCR
    extracted = await QwenOCR().process(text_only_layout, page_image, routing_tier, zero_text)

    from app.ai.llm.text_opt import TextOpt
    llm_outputs = await TextOpt().optimize(extracted, routing_tier, layout)

    braille_outputs: list[BrailleOutput] = []
    if include_braille and llm_outputs:
        from app.ai.braille.text_braille import TextBraille
        braille_outputs = TextBraille().translate(llm_outputs)

    return extracted, llm_outputs, braille_outputs


async def _run_formula_chain(
    layout: LayoutResult,
    page_image: Optional["PIL.Image.Image"],
    routing_tier: str,
    task: PageTask,
    include_braille: bool,
) -> ChainResult:
    formula_elems = [e for e in layout.elements if e.type == "formula"]
    if not formula_elems:
        return [], [], []

    extracted: list[ExtractedContent] = []
    if page_image is not None:
        try:
            from app.ai.ocr.formula_ocr import FormulaOCR
            crops = [(elem, _crop_element(page_image, elem)) for elem in formula_elems]
            extracted = await FormulaOCR().process(crops)
        except Exception as exc:
            logger.warning("FormulaOCR 실패 (fallback): %s", exc)
            extracted = [
                _placeholder_extracted(e, "수식 OCR 오류", "C3_FALLBACK")
                for e in formula_elems
            ]
    else:
        extracted = [
            _placeholder_extracted(e, "수식 이미지 없음", "C3_FALLBACK")
            for e in formula_elems
        ]

    from app.ai.llm.formula_opt import FormulaOpt
    llm_outputs = await FormulaOpt().optimize(extracted, routing_tier)

    braille_outputs: list[BrailleOutput] = []
    if include_braille and llm_outputs:
        from app.ai.braille.formula_braille import FormulaBraille
        braille_outputs = FormulaBraille().translate(llm_outputs)

    return extracted, llm_outputs, braille_outputs


async def _run_table_chain(
    layout: LayoutResult,
    page_image: Optional["PIL.Image.Image"],
    routing_tier: str,
    task: PageTask,
    include_braille: bool,
) -> ChainResult:
    table_elems = [e for e in layout.elements if e.type == "table"]
    if not table_elems:
        return [], [], []

    extracted: list[ExtractedContent] = []
    try:
        from app.ai.captioning.table_cap import TableCap
        crops = [(elem, _crop_element(page_image, elem)) for elem in table_elems] if page_image else []
        extracted = await TableCap().process(crops, routing_tier)
    except (ImportError, AttributeError):
        # table_cap.py 미구현(현주 T3-5) — 플레이스홀더
        extracted = [
            _placeholder_extracted(e, "표 캡셔닝 미구현", "C4_FALLBACK")
            for e in table_elems
        ]
    except Exception as exc:
        logger.warning("TableCap 실패: %s", exc)
        extracted = [
            _placeholder_extracted(e, "표 캡셔닝 오류", "C4_FALLBACK")
            for e in table_elems
        ]

    from app.ai.llm.table_opt import TableOpt
    llm_outputs = await TableOpt().optimize(extracted, routing_tier, layout)

    braille_outputs: list[BrailleOutput] = []
    if include_braille and llm_outputs:
        from app.ai.braille.table_braille import TableBraille
        braille_outputs = TableBraille().translate(llm_outputs)

    return extracted, llm_outputs, braille_outputs


async def _run_image_chain(
    layout: LayoutResult,
    page_image: Optional["PIL.Image.Image"],
    routing_tier: str,
    task: PageTask,
    include_braille: bool,
) -> ChainResult:
    # PART 3-4 이후 type이 "image"로 확정된 요소만 처리
    # (cartoon/chart_graph로 분류된 요소는 해당 체인이 담당)
    image_elems = [e for e in layout.elements if e.type == "image"]
    if not image_elems:
        return [], [], []

    extracted: list[ExtractedContent] = []
    try:
        from app.ai.captioning.image_cap import ImageCap
        crops = [(elem, _crop_element(page_image, elem)) for elem in image_elems] if page_image else []
        extracted = await ImageCap().process(crops)
    except (ImportError, AttributeError):
        extracted = [
            _placeholder_extracted(e, "이미지 캡셔닝 미구현", "C2_FALLBACK")
            for e in image_elems
        ]
    except Exception as exc:
        logger.warning("ImageCap 실패: %s", exc)
        extracted = [
            _placeholder_extracted(e, "이미지 캡셔닝 오류", "C2_FALLBACK")
            for e in image_elems
        ]

    from app.ai.llm.image_opt import ImageOpt
    llm_outputs = await ImageOpt().optimize(extracted, routing_tier, layout)

    braille_outputs: list[BrailleOutput] = []
    if include_braille and llm_outputs:
        from app.ai.braille.image_braille import ImageBraille
        braille_outputs = ImageBraille().translate(llm_outputs)

    return extracted, llm_outputs, braille_outputs


async def _run_cartoon_chain(
    layout: LayoutResult,
    page_image: Optional["PIL.Image.Image"],
    routing_tier: str,
    task: PageTask,
    include_braille: bool,
) -> ChainResult:
    cartoon_elems = [e for e in layout.elements if e.type == "cartoon"]
    if not cartoon_elems:
        return [], [], []

    extracted: list[ExtractedContent] = []
    try:
        from app.ai.captioning.cartoon_cap import CartoonCap
        crops = [(elem, _crop_element(page_image, elem)) for elem in cartoon_elems] if page_image else []
        extracted = await CartoonCap().process(crops)
    except (ImportError, AttributeError):
        extracted = [
            _placeholder_extracted(e, "만화 캡셔닝 미구현", "C2_FALLBACK")
            for e in cartoon_elems
        ]
    except Exception as exc:
        logger.warning("CartoonCap 실패: %s", exc)
        extracted = [
            _placeholder_extracted(e, "만화 캡셔닝 오류", "C2_FALLBACK")
            for e in cartoon_elems
        ]

    from app.ai.llm.cartoon_opt import CartoonOpt
    llm_outputs = await CartoonOpt().optimize(extracted, routing_tier, layout)

    braille_outputs: list[BrailleOutput] = []
    if include_braille and llm_outputs:
        from app.ai.braille.cartoon_braille import CartoonBraille
        braille_outputs = CartoonBraille().translate(llm_outputs)

    return extracted, llm_outputs, braille_outputs


async def _run_chart_graph_chain(
    layout: LayoutResult,
    page_image: Optional["PIL.Image.Image"],
    routing_tier: str,
    task: PageTask,
    include_braille: bool,
) -> ChainResult:
    chart_elems = [e for e in layout.elements if e.type == "chart_graph"]
    if not chart_elems:
        return [], [], []

    extracted: list[ExtractedContent] = []
    try:
        from app.ai.captioning.chart_graph_cap import ChartGraphCap
        crops = [(elem, _crop_element(page_image, elem)) for elem in chart_elems] if page_image else []
        extracted = await ChartGraphCap().process(crops)
    except (ImportError, AttributeError):
        extracted = [
            _placeholder_extracted(e, "차트 캡셔닝 미구현", "C2_FALLBACK")
            for e in chart_elems
        ]
    except Exception as exc:
        logger.warning("ChartGraphCap 실패: %s", exc)
        extracted = [
            _placeholder_extracted(e, "차트 캡셔닝 오류", "C2_FALLBACK")
            for e in chart_elems
        ]

    from app.ai.llm.chart_graph_opt import ChartGraphOpt
    llm_outputs = await ChartGraphOpt().optimize(extracted, routing_tier, layout)

    braille_outputs: list[BrailleOutput] = []
    if include_braille and llm_outputs:
        from app.ai.braille.chart_graph_braille import ChartGraphBraille
        braille_outputs = ChartGraphBraille().translate(llm_outputs)

    return extracted, llm_outputs, braille_outputs


# ── 파이프라인 실행 ──────────────────────────────────────────────────────

async def _run_pipeline(task: PageTask) -> dict:
    page_id = f"p_{task.page_no:03d}"

    doc_meta: Optional[DocumentMeta] = None
    page_image = None
    layout_result: Optional[LayoutResult] = None
    image_width = 0
    image_height = 0
    zero_text: Optional[str] = None

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

        # PART 3-4: 이미지 세분류 (GPT-4o, 현주 T3-8)
        try:
            from app.ai.captioning.classifier import ImageClassifier
            layout_result = await ImageClassifier().classify(layout_result, page_image)
            _debug_dump(task, "03_4_layout_classified", layout_result.model_dump())
        except (ImportError, AttributeError):
            pass  # 미구현 시 이미지 요소는 type="image" 그대로 유지

    # ── mode b: source_text → 가상 요소 구성 ────────────────────────────
    elif task.mode == "b":
        dummy = BBoxItem(
            element_id=uuid4(), type="text",
            bbox=(0, 0, 1240, 1754), reading_order=1,
        )
        layout_result = LayoutResult(page_id=page_id, elements=[dummy])

    routing_tier = doc_meta.routing_tier if doc_meta else "STANDARD"
    include_braille = task.mode in ("b", "c")

    # ── mode b: 텍스트 단일 체인 ─────────────────────────────────────
    if task.mode == "b":
        assert layout_result is not None
        source_elem = layout_result.elements[0]
        extracted_texts = [ExtractedContent(
            element_id=source_elem.element_id,
            corrected_text=task.source_text or "",
            ocr_confidence=1.0,
        )]
        from app.ai.llm.text_opt import TextOpt
        llm_outputs = await TextOpt().optimize(extracted_texts, routing_tier, layout_result)

        braille_outputs: list[BrailleOutput] = []
        if llm_outputs:
            from app.ai.braille.text_braille import TextBraille
            from app.ai.braille.layout_braille import LayoutBraille
            braille_outputs = TextBraille().translate(llm_outputs)
            LayoutBraille().layout(braille_outputs, task.page_no, task.job_id)

        return _build_response(
            task, page_id, doc_meta, routing_tier, image_width, image_height,
            layout_result, extracted_texts, llm_outputs, braille_outputs,
        )

    # ── mode a, c: 6-체인 병렬 실행 ─────────────────────────────────
    assert layout_result is not None
    chain_results = await asyncio.gather(
        _run_text_chain(layout_result, page_image, doc_meta, routing_tier, task, include_braille, zero_text),
        _run_formula_chain(layout_result, page_image, routing_tier, task, include_braille),
        _run_table_chain(layout_result, page_image, routing_tier, task, include_braille),
        _run_image_chain(layout_result, page_image, routing_tier, task, include_braille),
        _run_cartoon_chain(layout_result, page_image, routing_tier, task, include_braille),
        _run_chart_graph_chain(layout_result, page_image, routing_tier, task, include_braille),
        return_exceptions=True,
    )

    # 체인 결과 병합 (예외 발생 체인은 빈 결과로 처리)
    all_extracted: list[ExtractedContent] = []
    all_llm: list[LLMOutput] = []
    all_braille: list[BrailleOutput] = []

    for i, result in enumerate(chain_results):
        if isinstance(result, Exception):
            logger.error("체인 %d 실패 (계속 진행): %s", i, result)
            continue
        ext_list, llm_list, br_list = result
        all_extracted.extend(ext_list)
        all_llm.extend(llm_list)
        all_braille.extend(br_list)

    _debug_dump(task, "04_all_ocr", [e.model_dump() for e in all_extracted])
    _debug_dump(task, "05_all_opt", [o.model_dump() for o in all_llm])

    # PART 10: 레이아웃 조판
    if include_braille and all_braille:
        from app.ai.braille.layout_braille import LayoutBraille
        LayoutBraille().layout(all_braille, task.page_no, task.job_id)

    return _build_response(
        task, page_id, doc_meta, routing_tier, image_width, image_height,
        layout_result, all_extracted, all_llm, all_braille,
    )


# ── 응답 조립 ────────────────────────────────────────────────────────────

def _build_response(
    task: PageTask,
    page_id: str,
    doc_meta: Optional[DocumentMeta],
    routing_tier: str,
    image_width: int,
    image_height: int,
    layout_result: LayoutResult,
    extracted: list[ExtractedContent],
    llm_outputs: list[LLMOutput],
    braille_outputs: list[BrailleOutput],
) -> dict:
    elem_by_id = {e.element_id: e for e in layout_result.elements}
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
            for e in layout_result.elements
        ]
        response["text_list"] = [
            {
                "id": str(o.element_id),
                "type": elem_by_id.get(o.element_id, _DUMMY_ELEM).type,
                "order": i + 1,
                "heading_level": getattr(
                    elem_by_id.get(o.element_id), "heading_level", None
                ) or 0,
                "ocr_confidence": _get_ocr_confidence(o.element_id, extracted),
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
                "ocr_confidence": _get_ocr_confidence(o.element_id, extracted),
                "tn_text": o.tn_text or "",
                "is_blocked": "[처리 불가" in o.corrected_text,
                "render_mode": o.render_mode,
                "contents": (
                    braille_by_id[o.element_id].braille_lines
                    if o.element_id in braille_by_id else []
                ),
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

def _get_ocr_confidence(element_id: UUID, extracted: list[ExtractedContent]) -> float:
    for e in extracted:
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
