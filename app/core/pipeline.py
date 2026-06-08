"""파이프라인 진입점.

단계 3·4 구조: 현주 추출 → data/NNN_txt_result.json → 태민 분해/점역 → 단계별 json → 최종 결과

  공통 경계 파일: storage/jobs/{job}/temp/page_{no:03d}/data/{no:03d}_txt_result.json
    형식 {meta:{job_id,page_no,extraction_method}, elements:[{id,order,type,content}]}
    - 현주 파트(PART 2/3/4-1/5-1 등)가 생성. 이미 존재하면 그대로 사용(핸드오프).
    - 태민 파트가 읽어서 6-체인(현재 text/formula 동작)으로 분해→opt→braille.

  mode a: 현주추출 → 파일 → text_list 반환
  mode b: source_text → 4-2 → 4-3 → 10 (braille_text_list 반환)
  mode c: 현주추출 → 파일 → 6-체인 → 10 (양쪽 반환)

단계 4(시각자료: table/image/cartoon/chart_graph)는 파일에 해당 요소가 있을 때 동작.
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

# 텍스트 요소 유형 — text 체인이 처리하는 요소들
_TEXT_TYPES = {"text", "title", "caption", "list_item", "footnote", "sidebar", "header_footer", "page_number"}

# 현주 type 값 → 태민/plan type 값 매핑 (현주는 chart 사용)
# 도표(§6.6 개념도·흐름도)는 단일 diagram 체인으로 라우팅하고, 하위유형은 visual_subtype로 보존한다.
_TYPE_ALIAS = {
    "chart": "chart_graph",
    "도표": "diagram", "diagram": "diagram",
    "concept_map": "diagram", "개념도": "diagram",
    "flowchart": "diagram", "흐름도": "diagram",
    "org_chart": "diagram", "조직도": "diagram",
    "family_tree": "diagram", "가계도": "diagram",
    "timeline": "diagram", "연대표": "diagram",
    "form": "diagram", "양식": "diagram",
    "screen_image": "diagram", "화면이미지": "diagram", "화면 이미지": "diagram",
    "slide": "diagram", "발표슬라이드": "diagram", "발표용 슬라이드": "diagram", "슬라이드": "diagram",
}
# 현주 type 값이 도표 하위유형을 직접 가리킬 때 visual_subtype로 보존(§6.6 하위유형 구분).
_SUBTYPE_FROM_TYPE = {
    "concept_map": "concept_map", "개념도": "concept_map",
    "flowchart": "flowchart", "흐름도": "flowchart",
    "org_chart": "org_chart", "조직도": "org_chart",
    "family_tree": "family_tree", "가계도": "family_tree",
    "timeline": "timeline", "연대표": "timeline",
    "form": "form", "양식": "form",
    "screen_image": "screen_image", "화면이미지": "screen_image", "화면 이미지": "screen_image",
    "slide": "slide", "발표슬라이드": "slide", "발표용 슬라이드": "slide", "슬라이드": "slide",
}

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
        json.dumps(data, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
    )


# ── 경계 파일 (현주 ↔ 태민) ───────────────────────────────────────────────

def _page_dir(task: PageTask) -> Path:
    return Path(f"storage/jobs/{task.job_id}/temp/page_{task.page_no:03d}")


def _txt_result_path(task: PageTask) -> Path:
    return _page_dir(task) / "data" / f"{task.page_no:03d}_txt_result.json"


def _write_txt_result(task: PageTask, extraction: dict) -> None:
    p = _txt_result_path(task)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(extraction, ensure_ascii=False, indent=2), encoding="utf-8")


def _read_txt_result(task: PageTask) -> dict:
    return json.loads(_txt_result_path(task).read_text(encoding="utf-8"))


def _write_stage(task: PageTask, dir_name: str, filename: str, objs: list) -> None:
    """태민 단계별 산출물 기록: temp/page_NNN/type/{dir}/{filename}."""
    d = _page_dir(task) / "type" / dir_name
    d.mkdir(parents=True, exist_ok=True)
    payload = [o.model_dump() for o in objs]
    (d / filename).write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
    )


# ── 현주 추출 (Phase 1) — data/NNN_txt_result.json 생성 ────────────────────

def _blocks_from_text(pdf_text: Optional[str]) -> list[dict]:
    """ZERO Tier: PyMuPDF 직접 추출 텍스트를 줄 단위 요소로 변환.

    현주 PART2 ZERO 추출의 임시 구현(줄 단위). 현주 모듈이 type/order를 정밀
    부여하도록 완성되면 이 함수 대신 그 출력을 사용한다.
    """
    elements: list[dict] = []
    order = 0
    for raw_line in (pdf_text or "").split("\n"):
        line = raw_line.strip()
        if not line:
            continue
        order += 1
        etype = "page_number" if line.isdigit() else "text"
        elements.append({"id": str(uuid4()), "order": order, "type": etype, "content": line})
    if not elements:
        elements.append({"id": str(uuid4()), "order": 1, "type": "text", "content": (pdf_text or "").strip()})
    return elements


async def _extract_via_models(task: PageTask, doc_meta: DocumentMeta) -> list[dict]:
    """non-ZERO Tier: 현주 모델 모듈(레이아웃·OCR) 호출. 미탑재/실패 시 빈 결과로 격리."""
    try:
        from app.ai.preprocessor.converter import convert_page
        from app.ai.layout.layout_merger import LayoutMerger
        from app.ai.layout.qwen_layout import QwenLayout
        from app.ai.layout.yolo_layout import YoloLayout
        from app.ai.ocr.qwen_ocr import QwenOCR

        page_image = await asyncio.to_thread(
            convert_page, task.pdf_data, task.page_no - 1,
            doc_meta.routing_tier, task.job_id, task.page_no,
        )
        qwen_items, yolo_hints = await asyncio.gather(
            asyncio.to_thread(QwenLayout().detect, page_image),
            asyncio.to_thread(YoloLayout().detect, page_image),
        )
        layout = await asyncio.to_thread(
            LayoutMerger().merge, qwen_items, yolo_hints,
            task.job_id, task.page_no, page_image.width, page_image.height,
        )
        text_layout = LayoutResult(
            page_id=f"p_{task.page_no:03d}",
            elements=[e for e in layout.elements if e.type in _TEXT_TYPES],
        )
        extracted = await QwenOCR().process(text_layout, page_image, doc_meta.routing_tier, None)
        ex_by_id = {x.element_id: x for x in extracted}
        elements: list[dict] = []
        for e in layout.elements:
            ex = ex_by_id.get(e.element_id)
            elements.append({
                "id": str(e.element_id),
                "order": e.reading_order,
                "type": e.type,
                "content": (ex.corrected_text if ex else "") or "",
            })
        return elements
    except Exception as exc:
        logger.warning("현주 모델 추출 실패(빈 결과로 격리): %s", exc)
        return []


async def _extract_with_hyunju(task: PageTask) -> tuple[DocumentMeta, dict]:
    """현주 추출 단계: analyze_pdf + (ZERO 텍스트 | non-ZERO 모델) → 경계 dict."""
    from app.ai.preprocessor.pdf_analyzer import analyze_pdf

    doc_meta, pdf_text = await asyncio.to_thread(
        analyze_pdf, task.pdf_data, task.page_no - 1, task.job_id
    )
    if doc_meta.routing_tier == "ZERO":
        method = "TEXT_NATIVE"
        elements = _blocks_from_text(pdf_text)
    else:
        method = "OCR"
        elements = await _extract_via_models(task, doc_meta)

    extraction = {
        "meta": {
            "job_id": task.job_id,
            "page_no": task.page_no,
            "extraction_method": method,
        },
        "elements": elements,
    }
    return doc_meta, extraction


# ── 태민 분해 (Phase 2) — 경계 파일 → LayoutResult + ExtractedContent ───────

def _parse_txt_result(
    extraction: dict, page_id: str
) -> tuple[LayoutResult, dict[UUID, ExtractedContent], str]:
    method = extraction.get("meta", {}).get("extraction_method", "OCR")
    conf = 1.0 if method == "TEXT_NATIVE" else 0.95

    bbox_items: list[BBoxItem] = []
    ext_map: dict[UUID, ExtractedContent] = {}

    for idx, el in enumerate(extraction.get("elements", []), start=1):
        try:
            eid = UUID(str(el.get("id")))
        except (ValueError, TypeError):
            eid = uuid4()
        orig_type = el.get("type", "text")
        etype = _TYPE_ALIAS.get(orig_type, orig_type)
        vsub = el.get("visual_subtype") or _SUBTYPE_FROM_TYPE.get(orig_type)
        order = int(el.get("order", idx))
        content = el.get("content", "") or ""
        # heading_level: 현주 핸드오프가 주면 그 값, 없으면 title은 1단계 기본(PART 10 조판용)
        hlevel = el.get("heading_level")
        if hlevel in (None, 0) and etype == "title":
            hlevel = 1

        bbox_items.append(BBoxItem(
            element_id=eid, type=etype, bbox=(0, 0, 0, 0), reading_order=order,
            heading_level=hlevel,
        ))
        if etype == "formula":
            ext_map[eid] = ExtractedContent(
                element_id=eid, latex_string=content, corrected_text=content,
                ocr_confidence=conf,
            )
        else:
            # 현주 구조화 입력(계약): structure(만화 panels·차트 axes 등)·table_structure 전달.
            # 없으면 None → 각 opt가 corrected_text(caption) 폴백.
            ext_map[eid] = ExtractedContent(
                element_id=eid, corrected_text=content, ocr_confidence=conf,
                visual_subtype=vsub,
                structure=el.get("structure"),
                table_structure=el.get("table_structure"),
            )

    layout = LayoutResult(page_id=page_id, elements=bbox_items)
    return layout, ext_map, method


# ── 6-체인 (Phase 2: 태민 opt → braille, 단계별 json 기록) ──────────────────

async def _run_text_chain(
    extracted: list[ExtractedContent],
    layout: LayoutResult,
    routing_tier: str,
    task: PageTask,
    include_braille: bool,
) -> ChainResult:
    if not extracted:
        return [], [], []
    _write_stage(task, "text", "text_ocr.json", extracted)

    from app.ai.llm.text_opt import TextOpt
    llm_outputs = await TextOpt().optimize(extracted, routing_tier, layout)
    _write_stage(task, "text", "text_opt.json", llm_outputs)

    braille_outputs: list[BrailleOutput] = []
    if include_braille and llm_outputs:
        from app.ai.braille.text_braille import TextBraille
        braille_outputs = TextBraille().translate(llm_outputs)
        _write_stage(task, "text", "text_braille.json", braille_outputs)

    return extracted, llm_outputs, braille_outputs


async def _run_formula_chain(
    extracted: list[ExtractedContent],
    routing_tier: str,
    task: PageTask,
    include_braille: bool,
) -> ChainResult:
    if not extracted:
        return [], [], []
    _write_stage(task, "formula", "formula_ocr.json", extracted)

    from app.ai.llm.formula_opt import FormulaOpt
    llm_outputs = await FormulaOpt().optimize(extracted, routing_tier)
    _write_stage(task, "formula", "formula_opt.json", llm_outputs)

    braille_outputs: list[BrailleOutput] = []
    if include_braille and llm_outputs:
        from app.ai.braille.formula_braille import FormulaBraille
        braille_outputs = FormulaBraille().translate(llm_outputs)
        _write_stage(task, "formula", "formula_braille.json", braille_outputs)

    return extracted, llm_outputs, braille_outputs


async def _run_table_chain(
    extracted: list[ExtractedContent],
    layout: LayoutResult,
    routing_tier: str,
    task: PageTask,
    include_braille: bool,
) -> ChainResult:
    if not extracted:
        return [], [], []
    _write_stage(task, "table", "table_cap.json", extracted)

    from app.ai.llm.table_opt import TableOpt
    llm_outputs = await TableOpt().optimize(extracted, routing_tier, layout)
    _write_stage(task, "table", "table_opt.json", llm_outputs)

    braille_outputs: list[BrailleOutput] = []
    if include_braille and llm_outputs:
        from app.ai.braille.table_braille import TableBraille
        braille_outputs = TableBraille().translate(llm_outputs)
        _write_stage(task, "table", "table_braille.json", braille_outputs)

    return extracted, llm_outputs, braille_outputs


async def _run_image_chain(
    extracted: list[ExtractedContent],
    layout: LayoutResult,
    routing_tier: str,
    task: PageTask,
    include_braille: bool,
) -> ChainResult:
    if not extracted:
        return [], [], []
    _write_stage(task, "image", "image_cap.json", extracted)

    from app.ai.llm.image_opt import ImageOpt
    llm_outputs = await ImageOpt().optimize(extracted, routing_tier, layout)
    _write_stage(task, "image", "image_opt.json", llm_outputs)

    braille_outputs: list[BrailleOutput] = []
    if include_braille and llm_outputs:
        from app.ai.braille.image_braille import ImageBraille
        braille_outputs = ImageBraille().translate(llm_outputs)
        _write_stage(task, "image", "image_braille.json", braille_outputs)

    return extracted, llm_outputs, braille_outputs


async def _run_cartoon_chain(
    extracted: list[ExtractedContent],
    layout: LayoutResult,
    routing_tier: str,
    task: PageTask,
    include_braille: bool,
) -> ChainResult:
    if not extracted:
        return [], [], []
    _write_stage(task, "cartoon", "cartoon_cap.json", extracted)

    from app.ai.llm.cartoon_opt import CartoonOpt
    llm_outputs = await CartoonOpt().optimize(extracted, routing_tier, layout)
    _write_stage(task, "cartoon", "cartoon_opt.json", llm_outputs)

    braille_outputs: list[BrailleOutput] = []
    if include_braille and llm_outputs:
        from app.ai.braille.cartoon_braille import CartoonBraille
        braille_outputs = CartoonBraille().translate(llm_outputs)
        _write_stage(task, "cartoon", "cartoon_braille.json", braille_outputs)

    return extracted, llm_outputs, braille_outputs


async def _run_chart_graph_chain(
    extracted: list[ExtractedContent],
    layout: LayoutResult,
    routing_tier: str,
    task: PageTask,
    include_braille: bool,
) -> ChainResult:
    if not extracted:
        return [], [], []
    _write_stage(task, "chart_graph", "cg_cap.json", extracted)

    from app.ai.llm.chart_graph_opt import ChartGraphOpt
    llm_outputs = await ChartGraphOpt().optimize(extracted, routing_tier, layout)
    _write_stage(task, "chart_graph", "cg_opt.json", llm_outputs)

    braille_outputs: list[BrailleOutput] = []
    if include_braille and llm_outputs:
        from app.ai.braille.chart_graph_braille import ChartGraphBraille
        braille_outputs = ChartGraphBraille().translate(llm_outputs)
        _write_stage(task, "chart_graph", "cg_braille.json", braille_outputs)

    return extracted, llm_outputs, braille_outputs


async def _run_diagram_chain(
    extracted: list[ExtractedContent],
    layout: LayoutResult,
    routing_tier: str,
    task: PageTask,
    include_braille: bool,
) -> ChainResult:
    """도표(§6.6 개념도·흐름도) 체인 — rule-based 골격 조립(opt→braille)."""
    if not extracted:
        return [], [], []
    _write_stage(task, "diagram", "diagram_cap.json", extracted)

    from app.ai.llm.diagram_opt import DiagramOpt
    llm_outputs = await DiagramOpt().optimize(extracted, routing_tier, layout)
    _write_stage(task, "diagram", "diagram_opt.json", llm_outputs)

    braille_outputs: list[BrailleOutput] = []
    if include_braille and llm_outputs:
        from app.ai.braille.diagram_braille import DiagramBraille
        braille_outputs = DiagramBraille().translate(llm_outputs)
        _write_stage(task, "diagram", "diagram_braille.json", braille_outputs)

    return extracted, llm_outputs, braille_outputs


# ── 파이프라인 실행 ──────────────────────────────────────────────────────

def _collect(layout: LayoutResult, ext_map: dict[UUID, ExtractedContent], types: set[str]) -> list[ExtractedContent]:
    return [ext_map[e.element_id] for e in layout.elements if e.type in types and e.element_id in ext_map]


async def _run_pipeline(task: PageTask) -> dict:
    page_id = f"p_{task.page_no:03d}"

    doc_meta: Optional[DocumentMeta] = None
    image_width = 0
    image_height = 0

    # ── mode b: source_text 단일 텍스트 체인 ───────────────────────────
    if task.mode == "b":
        source_elem_id = uuid4()
        layout_result = LayoutResult(
            page_id=page_id,
            elements=[BBoxItem(element_id=source_elem_id, type="text", bbox=(0, 0, 0, 0), reading_order=1)],
        )
        extracted_texts = [ExtractedContent(
            element_id=source_elem_id,
            corrected_text=task.source_text or "",
            ocr_confidence=1.0,
        )]
        ext, llm_outputs, braille_outputs = await _run_text_chain(
            extracted_texts, layout_result, "ZERO", task, include_braille=True,
        )
        overflow_rate = 0.0
        if braille_outputs:
            from app.ai.braille.layout_braille import LayoutBraille
            overflow_rate = LayoutBraille().layout(
                braille_outputs, task.page_no, task.job_id,
                layout_result=layout_result,
            )
        return _build_response(
            task, page_id, doc_meta, "ZERO", image_width, image_height,
            layout_result, ext, llm_outputs, braille_outputs,
            line_overflow_rate=overflow_rate,
        )

    # ── mode a, c ──────────────────────────────────────────────────────
    # Phase 1 (현주): 경계 파일이 없으면 현주 추출로 생성. 있으면 그대로 사용.
    if _txt_result_path(task).exists():
        extraction = _read_txt_result(task)
        logger.info("기존 추출 파일 사용 job=%s page=%d", task.job_id, task.page_no)
    else:
        doc_meta, extraction = await _extract_with_hyunju(task)
        _write_txt_result(task, extraction)
        _debug_dump(task, "02_doc_meta", doc_meta.model_dump())

    # Phase 2 (태민): 경계 파일 → 분해 → 6-체인
    layout_result, ext_map, method = _parse_txt_result(extraction, page_id)
    routing_tier = (
        doc_meta.routing_tier if doc_meta
        else ("ZERO" if method == "TEXT_NATIVE" else "STANDARD")
    )
    include_braille = task.mode == "c"

    chain_results = await asyncio.gather(
        _run_text_chain(_collect(layout_result, ext_map, _TEXT_TYPES), layout_result, routing_tier, task, include_braille),
        _run_formula_chain(_collect(layout_result, ext_map, {"formula"}), routing_tier, task, include_braille),
        _run_table_chain(_collect(layout_result, ext_map, {"table"}), layout_result, routing_tier, task, include_braille),
        _run_image_chain(_collect(layout_result, ext_map, {"image"}), layout_result, routing_tier, task, include_braille),
        _run_cartoon_chain(_collect(layout_result, ext_map, {"cartoon"}), layout_result, routing_tier, task, include_braille),
        _run_chart_graph_chain(_collect(layout_result, ext_map, {"chart_graph"}), layout_result, routing_tier, task, include_braille),
        _run_diagram_chain(_collect(layout_result, ext_map, {"diagram"}), layout_result, routing_tier, task, include_braille),
        return_exceptions=True,
    )

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
    overflow_rate = 0.0
    if include_braille and all_braille:
        from app.ai.braille.layout_braille import LayoutBraille
        overflow_rate = LayoutBraille().layout(
            all_braille, task.page_no, task.job_id,
            layout_result=layout_result,
        )

    return _build_response(
        task, page_id, doc_meta, routing_tier, image_width, image_height,
        layout_result, all_extracted, all_llm, all_braille,
        line_overflow_rate=overflow_rate,
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
    line_overflow_rate: float = 0.0,
) -> dict:
    elem_by_id = {e.element_id: e for e in layout_result.elements}
    braille_by_id = {b.element_id: b for b in braille_outputs}

    # 응답 리스트는 문서 읽기 순서로 정렬한다. (6체인 gather 결과는 type별로 묶여 있어
    # 그대로 내보내면 본문 위 그림 등에서 순서가 뒤바뀐다 — FE가 order로 렌더 가능하도록.)
    _order_of = {e.element_id: e.reading_order for e in layout_result.elements}
    llm_outputs = sorted(llm_outputs, key=lambda o: _order_of.get(o.element_id, 1_000_000))

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
            page_id=page_id, status="COMPLETED",
            line_overflow_rate=line_overflow_rate,
        ).model_dump(),
    }

    if task.mode in ("a", "c"):
        response["image_width"] = image_width
        response["image_height"] = image_height
        response["bounding_box_list"] = [
            {
                "id": str(e.element_id),
                "x": e.bbox[0],
                "y": e.bbox[1],
                "x2": e.bbox[2],
                "y2": e.bbox[3],
                "type": e.type,
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
                "heading_level": getattr(
                    elem_by_id.get(o.element_id), "heading_level", None
                ) or 0,
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
                "selected_idx": (
                    braille_by_id[o.element_id].selected_idx
                    if o.element_id in braille_by_id else 0
                ),
                "drafts": [
                    {
                        "text": d.text,
                        "label": d.label,
                        "contents": d.braille_lines,
                    }
                    for d in (
                        braille_by_id[o.element_id].drafts
                        if o.element_id in braille_by_id else []
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
