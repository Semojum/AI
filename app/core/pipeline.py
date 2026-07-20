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
import os
import re
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
from app.utils.req_log import (
    api_summary,
    breakdown_lines,
    elapsed,
    set_hcxt_budget,
    stage,
    start_request,
)

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

# 판권·러닝헤드 보일러플레이트 — 정답 BRL 전수조사(1131p)에서 출현 0%: 점역사는 전부
# 제거한다. 요소 content "전체"가 패턴일 때만 드롭(본문 문장 속 언급은 보존).
_BOILERPLATE_RES = (
    re.compile(r"^(?:https?://)?www\.[\w-]+(?:\.[\w-]+)+\S*$", re.IGNORECASE),  # URL 단독 요소
    re.compile(r"^EBS$"),                                # 출판사 로고 텍스트
    re.compile(r"^EBS\s*수능특강"),                       # 러닝헤드(과목·단원 접미 포함)
    re.compile(r"^(?:ⓒ|©|Copyright\b)", re.IGNORECASE),  # 저작권 고지
)


def _is_boilerplate(content: str) -> bool:
    c = content.strip()
    return bool(c) and any(p.match(c) for p in _BOILERPLATE_RES)


# ── 인쇄 러닝풋(가구) 억제 — header_footer 전용 ─────────────────────────────
# 4분류: ① 규칙 미비 — 도서 관행(점자책은 인쇄 장식 러닝풋을 옮기지 않음) 미구현.
# 실측(2026-07-20, dev 36p·val 951p 코퍼스 채점기 대조): 아래 패턴의 header_footer는
# gold BRF에 재현되지 않는다(억제 대상 166요소 중 gold 존재 2건뿐 — '테스트' 4셀 우연
# 부분일치). 반대로 gold가 유지하는 헤더는 목록에 넣지 않는다:
#   · 'Level N ○○연습'(수학2)·'PartⅡ/Ⅲ ○○편'(외국어) — 섹션 배너로 재현됨(억제 시 CER 악화)
#   · '수능 기본 문제'·'Exercises' 등 반복 배너 — 매 등장이 섹션 시작이라 gold 유지
#   · 장 표제(Ⅱ. …) 반복 — 도서별 관행이 갈림(사회문화=장 시작 1회, 세계사=매 페이지
#     유지). 잡-반복 억제(첫 등장만 유지)는 세계사에서 손해라 기각, 패턴 목록만 쓴다.
# header_footer 타입에만 적용 — 본문(text 등)의 동일 문자열은 건드리지 않는다.
_RUNNING_FOOT_RES = (
    re.compile(r"science", re.IGNORECASE),  # 생물 러닝풋 배너(OCR 변형 '수능 SCIENCE 29 테 스트' 포함)
    re.compile(r"^테스트$"),                 # 생물 러닝풋 단독 배너(전체 일치만)
    re.compile(r"^中$"),                    # 사회문화·세계사 러닝풋 장식의 OCR 노이즈
    re.compile(r"^\d{1,3}\s*\|"),           # 생물 강 러닝헤더 '04 | 혈액의 구성과 혈액형'
)
_HF_TAG_RE = re.compile(r"<!/?[^>]+>")      # 러닝풋 판정 전 <!드러냄> 등 인라인 태그 제거


def _is_running_foot(content: str) -> bool:
    """header_footer 요소가 인쇄 전용 러닝풋인가(실측 패턴 목록 기반)."""
    c = re.sub(r"\s+", " ", _HF_TAG_RE.sub("", content or "")).strip()
    if not c:
        return False
    # ebsi URL 러닝풋 — OCR이 글자를 흩뿌린 변형('www e b si co k r'·'w w w e b s i c o k r'
    # ·'www. e b s i . co . k r')이 많아 공백·구두점을 걷어낸 평탄형으로 대조한다.
    flat = re.sub(r"[\s.·]", "", c).lower()
    if "wwwebsicokr" in flat or "ebsicokr" in flat:
        return True
    return any(p.search(c) for p in _RUNNING_FOOT_RES)


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
                message=f"{config.page_timeout_seconds:.0f}초 타임아웃 초과 ({elapsed_ms}ms)",
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
    """ZERO 폴백: 블록 추출이 비면 텍스트를 줄 단위 요소로(좌표 없음)."""
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


def _blocks_with_bbox(blocks: list[dict]) -> list[dict]:
    """ZERO Tier: PyMuPDF 블록(content+bbox) → 경계 요소(bbox 포함)."""
    elements: list[dict] = []
    for order, b in enumerate(blocks, start=1):
        content = b.get("content", "").strip()
        if not content:
            continue
        etype = "page_number" if content.isdigit() else "text"
        elements.append({
            "id": str(uuid4()), "order": order, "type": etype,
            "content": content, "bbox": b.get("bbox"),
        })
    return elements


async def _extract_via_models(task: PageTask, doc_meta: DocumentMeta) -> tuple[list[dict], int, int]:
    """non-ZERO Tier(스캔 PDF): MinerU2.5-Pro 통합 추출 → (elements, page_w, page_h).
    result_builder가 이미지 분류·캡셔닝까지 거쳐 경계 elements(bbox 포함)를 만든다.
    MinerU 미설치/실패/타임아웃 시: 텍스트레이어가 있으면 PyMuPDF 폴백으로 본문을
    살리고(표·그림 구조 손실 → 요소 R1 플래그), 스캔 전용이면 빈 결과로 격리."""
    import os
    import tempfile
    try:
        from app.ai.parser.mineru_runner import run as mineru_run
        from app.ai.builder.result_builder import build as build_result

        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
            f.write(task.pdf_data)
            tmp_path = f.name
        try:
            merged = await asyncio.to_thread(
                mineru_run, tmp_path, task.page_no, task.job_id, "OCR",
                timeout=config.mineru_timeout_resolved,
            )
            result = await asyncio.to_thread(
                build_result, merged, task.job_id, task.page_no, "OCR",
            )
        finally:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
        m = result.get("meta", {})
        return result.get("elements", []), int(m.get("image_width") or 0), int(m.get("image_height") or 0)
    except Exception as exc:
        logger.warning("MinerU 추출 실패: %s", exc)
        return await _fallback_text_layer(task, doc_meta)


async def _fallback_text_layer(task: PageTask, doc_meta: DocumentMeta) -> tuple[list[dict], int, int]:
    """MinerU 실패/타임아웃 폴백: 텍스트레이어가 있으면 PyMuPDF로 본문만 추출.

    C9(무거운 페이지)의 페이지 전체 BLOCKED 대신 부분 초안을 살린다. 표·그림
    구조는 잃으므로 각 요소에 C2_FALLBACK 플래그 → QualityChecker가 R1로 승격
    → 페이지 NEEDS_REVIEW(점역사 확인). 스캔 전용(텍스트레이어 없음)은 빈 결과."""
    if doc_meta.scan_only:
        return [], 0, 0
    try:
        from app.ai.preprocessor.pdf_analyzer import extract_text_blocks
        blocks, w, h = await asyncio.to_thread(extract_text_blocks, task.pdf_data, task.page_no)
        elements = _blocks_with_bbox(blocks)
        for el in elements:
            el["flags"] = ["C2_FALLBACK"]
        if elements:
            logger.warning(
                "텍스트레이어 폴백으로 %d요소 추출 — 표·그림 구조 손실, NEEDS_REVIEW (page=%d)",
                len(elements), task.page_no,
            )
        return elements, w, h
    except Exception as exc:
        logger.warning("텍스트레이어 폴백도 실패(빈 결과로 격리): %s", exc)
        return [], 0, 0


def _page_image_path(task: PageTask):
    """Opus 폴백용 페이지 이미지 — 저장분(input/page_NNN.jpg) 우선, 없으면 즉석 렌더."""
    from pathlib import Path
    p = Path(f"storage/jobs/{task.job_id}/input/page_{task.page_no:03d}.jpg")
    if p.exists():
        return p
    try:
        import fitz
        d = fitz.open(stream=task.pdf_data, filetype="pdf")
        idx = min(max(task.page_no - 1, 0), len(d) - 1)
        pix = d[idx].get_pixmap(matrix=fitz.Matrix(150 / 72, 150 / 72))
        p.parent.mkdir(parents=True, exist_ok=True)
        pix.save(str(p))
        d.close()
        return p
    except Exception as exc:  # noqa: BLE001 — 렌더 실패면 폴백 생략(원 추출 유지)
        logger.warning("Opus 폴백용 렌더 실패: %s", exc)
        return None


async def _extract_with_hyunju(task: PageTask) -> tuple[DocumentMeta, dict]:
    """현주 추출 단계: analyze_pdf + (ZERO 텍스트 | non-ZERO 모델) → 경계 dict(크기·bbox 포함)."""
    from app.ai.preprocessor.pdf_analyzer import analyze_pdf, extract_text_blocks

    # analyze_pdf의 page_no는 1-indexed(0 이하만 내부 보정). 빼기 1을 넘기면
    # 2페이지부터 한 장씩 밀리므로 task.page_no를 그대로 전달한다(현주 계약).
    doc_meta, pdf_text = await asyncio.to_thread(
        analyze_pdf, task.pdf_data, task.page_no, task.job_id
    )
    image_width = image_height = 0
    if doc_meta.routing_tier == "ZERO":
        method = "TEXT_NATIVE"
        blocks, image_width, image_height = await asyncio.to_thread(
            extract_text_blocks, task.pdf_data, task.page_no
        )
        elements = _blocks_with_bbox(blocks) or _blocks_from_text(pdf_text)
    else:
        method = "OCR"
        elements, image_width, image_height = await _extract_via_models(task, doc_meta)

    # Opus 비전 폴백(D-05, 기본 off — OPUS_EXTRACT_FALLBACK=1 opt-in): 추출이 빈약한
    # 페이지만 claude-opus-4-8이 직접 읽는다. 실측상 저품질 페이지에서만 유효(3~4배),
    # 중간 품질은 득실 반반이라 빈약 신호(요소 수·글자수)일 때만 트리거.
    from app.ai.parser import opus_fallback
    if opus_fallback.enabled() and opus_fallback.is_meager(elements):
        img = _page_image_path(task)
        if img:
            better = await asyncio.to_thread(opus_fallback.extract, str(img))
            if better and not opus_fallback.is_meager(better):
                logger.warning("Opus 추출 폴백 채택: %d→%d요소 (page=%d)",
                               len(elements), len(better), task.page_no)
                elements, method = better, "OPUS_VISION"

    extraction = {
        "meta": {
            "job_id": task.job_id,
            "page_no": task.page_no,
            "extraction_method": method,
            "image_width": image_width,
            "image_height": image_height,
        },
        "elements": elements,
    }
    return doc_meta, extraction


# ── 태민 분해 (Phase 2) — 경계 파일 → LayoutResult + ExtractedContent ───────

# 읽기순서 재배정 모드. off=원순서(MinerU content_list) | geom=순수 기하 위→아래(H1, 폐기)
#   | sidebar=max-gap 사이드바 머지(H2, 폐기) | col=열 클러스터링(H3, 운영 기본).
# dev 18p A/B(텍스트공간 τ, 2026-07-13): off 0.805 · sidebar 0.832 · col 0.965, off 대비 회귀 0건.
# sidebar(H2)는 x0 최대간격 분할이라 분할선이 본문/사이드바를 관통하는 페이지에서 오발동·미발동
# (세계사 p086 관통, p106 임계 3px 미달)이 잦아 col로 대체.
_REORDER_MODE = os.environ.get("READING_ORDER_MODE", "col")


def _valid_bbox(b: BBoxItem) -> bool:
    return b.bbox[2] > b.bbox[0] and b.bbox[3] > b.bbox[1]


def _reorder_by_geometry(items: list[BBoxItem]) -> None:
    """다단/사이드바 페이지의 읽기순서를 보정. 모드는 _REORDER_MODE.

    배경: MinerU content_list 순서는 좁은 좌측 사이드바(보충설명)를 본문보다 먼저 방출해
    읽기순서를 흩뜨린다(세계사 p086/p106). bbox 유효 요소가 과반인 MinerU 페이지만 손대고,
    bbox (0,0,0,0)인 ZERO/TEXT_NATIVE는 원순서를 보존한다.
    """
    if _REORDER_MODE == "off":
        return
    valid = [b for b in items if _valid_bbox(b)]
    if len(valid) < max(3, len(items) * 0.5):
        return  # 기하정보 부족 → 원순서 유지

    if _REORDER_MODE == "geom":
        # H1(폐기): 전체를 위→아래·행내 좌→우로 정렬. MinerU가 옳던 페이지를 망가뜨림.
        heights = sorted(b.bbox[3] - b.bbox[1] for b in valid)
        band = max(1.0, heights[len(heights) // 2] * 0.5)
        big = 10 ** 9
        key = lambda b: ((round(b.bbox[1] / band), b.bbox[0]) if _valid_bbox(b)
                         else (big, b.reading_order))
        for i, b in enumerate(sorted(items, key=key), start=1):
            b.reading_order = i
        return

    if _REORDER_MODE == "sidebar":
        _reorder_sidebar(items, valid)
        return

    if _REORDER_MODE == "col":
        _reorder_columns(items)


def _reorder_sidebar(items: list[BBoxItem], valid: list[BBoxItem]) -> None:
    """H2: 좌측 사이드바 컬럼만 본문 흐름에 y 위치로 끼워넣는다. 각 스트림 내부 순서는
    MinerU 순서 그대로 보존(머지). 단일단 페이지는 사이드바 미검출 → 무변경(회귀 최소)."""
    page_w = max(b.bbox[2] for b in valid)
    # 좌측 컬럼 경계 = x_left 정렬 중 최대 간격(페이지폭 15% 이상). 없으면 사이드바 없음.
    xs = sorted(b.bbox[0] for b in valid)
    gap, split_x = 0.0, None
    for a, c in zip(xs, xs[1:]):
        if c - a > gap:
            gap, split_x = c - a, (a + c) / 2
    if split_x is None or gap < 0.15 * page_w:
        return
    # 사이드바 = split_x 완전 왼쪽(우변도 왼쪽). 머리말/쪽번호는 본문 스트림에 둬 y로 자연배치.
    sidebar, main = [], []
    for b in items:
        if _valid_bbox(b) and b.bbox[2] <= split_x and b.type not in ("header_footer", "page_number"):
            sidebar.append(b)
        else:
            main.append(b)
    if not sidebar or not main:
        return
    # 사이드바 = 좁은 보충설명 열(소수). "사이드바" 스트림이 다수면 본문을 사이드바로
    # 오인한 것(우측 보조열 페이지에서 split이 본문 오른쪽에 잡히는 경우) → 무변경.
    if len(sidebar) >= len(main):
        return
    # 두 스트림(원순서 보존)을 y_top 기준 머지.
    merged, i, j = [], 0, 0
    while i < len(sidebar) and j < len(main):
        if sidebar[i].bbox[1] <= main[j].bbox[1]:
            merged.append(sidebar[i]); i += 1
        else:
            merged.append(main[j]); j += 1
    merged.extend(sidebar[i:]); merged.extend(main[j:])
    for k, b in enumerate(merged, start=1):
        b.reading_order = k


def _reorder_columns(items: list[BBoxItem]) -> None:
    """H3: 열 클러스터링 읽기순서. 정답 BRL 관찰(2026-07-13)에 근거한 세 규칙:

    (1) 점역사는 좁은 용어설명 열을 본문 뒤에 둔다 — MinerU가 이 열을 본문 앞에
        통째로(연속 순번) 방출하는 것이 주 실패 양상(세계사 p086·p106).
        반대로 순번이 본문 사이에 흩어진 좁은 요소(문항별 포인트 라벨 등)는
        MinerU의 의도 배치 → 보존(세계사 p160).
    (2) 대등한 2단 본문은 MinerU가 열 단위로 옳게 방출 — y-정렬하면 두 열이 섞여
        파괴되므로, MinerU 순서가 y-흐름을 심하게 거스를 때만 열 내부를 y-정렬
        (사회문화 p035: MinerU 순서 자체가 뒤죽박죽인 페이지).
    (3) 페이지행 요소(header_footer/page_number)·빈 bbox는 원래 순번 슬롯 유지.
    """
    body = [b for b in items if _valid_bbox(b) and b.type not in ("header_footer", "page_number")]
    if len(body) < 3:
        return

    # 1) x-구간 겹침(좁은 쪽 폭 50% 이상) union-find → 열 클러스터
    parent = list(range(len(body)))

    def _find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for i, a in enumerate(body):
        for j in range(i + 1, len(body)):
            c = body[j]
            ov = min(a.bbox[2], c.bbox[2]) - max(a.bbox[0], c.bbox[0])
            w = min(a.bbox[2] - a.bbox[0], c.bbox[2] - c.bbox[0])
            if w > 0 and ov >= 0.5 * w:
                parent[_find(i)] = _find(j)
    clusters: dict[int, list[BBoxItem]] = {}
    for i, b in enumerate(body):
        clusters.setdefault(_find(i), []).append(b)

    # 2) main = 최대 클러스터(동수면 총면적). main 헐과 자기 폭 50% 이상 겹치는
    #    클러스터(선지 ①②③ 조각 등)는 흡수.
    main_key = max(clusters, key=lambda k: (len(clusters[k]),
                                            sum((b.bbox[2] - b.bbox[0]) * (b.bbox[3] - b.bbox[1])
                                                for b in clusters[k])))
    main = clusters.pop(main_key)
    hull0, hull1 = min(b.bbox[0] for b in main), max(b.bbox[2] for b in main)
    sides: list[list[BBoxItem]] = []
    for cl in clusters.values():
        c0, c1 = min(b.bbox[0] for b in cl), max(b.bbox[2] for b in cl)
        if min(hull1, c1) - max(hull0, c0) >= 0.5 * (c1 - c0):
            main.extend(cl)
        else:
            sides.append(cl)

    # 3) 연속 순번 + 좁은 폭(본문 헐의 절반 이하) 사이드 열만 본문 뒤로 이동
    body_rank = {id(b): r for r, b in
                 enumerate(sorted(body, key=lambda b: b.reading_order), start=1)}
    deferred: list[list[BBoxItem]] = []
    for cl in sides:
        ranks = sorted(body_rank[id(b)] for b in cl)
        contiguous = ranks[-1] - ranks[0] == len(ranks) - 1
        narrow = (max(b.bbox[2] for b in cl) - min(b.bbox[0] for b in cl)) \
            <= 0.5 * (hull1 - hull0)
        if contiguous and narrow:
            deferred.append(cl)
        else:
            main.extend(cl)
    hull0, hull1 = min(b.bbox[0] for b in main), max(b.bbox[2] for b in main)

    # 4) main: MinerU 순서가 y-흐름을 2회 넘게 거스를 때만 y-밴드 정렬.
    #    위반 = y가 2밴드 이상 되돌아가는데 오른쪽 열 점프(2단 전환)도 아닌 연속 쌍.
    heights = sorted(b.bbox[3] - b.bbox[1] for b in main)
    band = max(1.0, heights[len(heights) // 2] * 0.5)

    def _ykey(b: BBoxItem) -> tuple:
        return (round(b.bbox[1] / band), b.bbox[0])

    by_mineru = sorted(main, key=lambda b: b.reading_order)
    viol = sum(
        1 for a, c in zip(by_mineru, by_mineru[1:])
        if c.bbox[1] < a.bbox[1] - 2 * band and c.bbox[0] < a.bbox[0] + 0.3 * (hull1 - hull0)
    )
    main = sorted(main, key=_ykey) if viol > 1 else by_mineru

    # 5) 새 본문 순서 = main → 이동 열(x0 순, 각 y-정렬). 비본문은 원 슬롯 유지.
    deferred.sort(key=lambda cl: min(b.bbox[0] for b in cl))
    new_body = main + [b for cl in deferred for b in sorted(cl, key=lambda x: x.bbox[1])]
    body_ids = {id(b) for b in body}
    it = iter(new_body)
    seq = [next(it) if id(b) in body_ids else b
           for b in sorted(items, key=lambda b: b.reading_order)]
    for k, b in enumerate(seq, start=1):
        b.reading_order = k


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
        if etype in _TEXT_TYPES and _is_boilerplate(content):
            logger.info("보일러플레이트 드롭(%s): %.60s", etype, content)
            continue
        if etype == "header_footer" and _is_running_foot(content):
            logger.info("러닝풋 억제(header_footer): %.60s", content)
            continue
        # heading_level: 현주 핸드오프가 주면 그 값, 없으면 title은 1단계 기본(PART 10 조판용)
        hlevel = el.get("heading_level")
        if hlevel in (None, 0) and etype == "title":
            hlevel = 1
        # bbox: 현주 레이아웃 좌표 → BoundingBox(x,y,x2,y2)로 BE 전달. 없거나 깨지면 (0,0,0,0).
        raw_bbox = el.get("bbox")
        try:
            bbox = (int(raw_bbox[0]), int(raw_bbox[1]), int(raw_bbox[2]), int(raw_bbox[3]))
        except (TypeError, IndexError, ValueError):
            bbox = (0, 0, 0, 0)
        # caption_ref: 캡션→대상(그림/표) 연결. UUID 문자열만 수용, 그 외 None.
        raw_cref = el.get("caption_ref")
        try:
            caption_ref = UUID(str(raw_cref)) if raw_cref else None
        except (ValueError, TypeError):
            caption_ref = None
        flags = [str(f) for f in (el.get("flags") or [])]
        # ocr_confidence: 요소별 값이 오면 사용, 없으면 추출방식 기준값(conf).
        raw_conf = el.get("ocr_confidence")
        econf = float(raw_conf) if isinstance(raw_conf, (int, float)) else conf

        bbox_items.append(BBoxItem(
            element_id=eid, type=etype, bbox=bbox, reading_order=order,
            heading_level=hlevel, caption_ref=caption_ref, flags=flags,
        ))
        if etype == "formula":
            ext_map[eid] = ExtractedContent(
                element_id=eid, latex_string=content, corrected_text=content,
                ocr_confidence=econf, flags=flags,
            )
        else:
            # 현주 구조화 입력(계약): structure(만화 panels·차트 axes 등)·table_structure 전달.
            # 없으면 None → 각 opt가 corrected_text(caption) 폴백.
            raw_subconf = el.get("subtype_confidence")
            ext_map[eid] = ExtractedContent(
                element_id=eid, corrected_text=content, ocr_confidence=econf,
                visual_subtype=vsub,
                subtype_confidence=float(raw_subconf) if isinstance(raw_subconf, (int, float)) else None,
                structure=el.get("structure"),
                table_structure=el.get("table_structure"),
                flags=flags,
            )

    _reorder_by_geometry(bbox_items)
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


def _type_breakdown(layout: LayoutResult) -> str:
    """요소 유형별 개수 요약(진행 로그 note용). 예: '텍스트18·수식2·표1'."""
    from collections import Counter
    label = {"formula": "수식", "table": "표", "image": "그림",
             "cartoon": "만화", "chart_graph": "차트", "diagram": "도표"}
    c: Counter = Counter()
    for e in layout.elements:
        c["텍스트" if e.type in _TEXT_TYPES else label.get(e.type, e.type)] += 1
    return "·".join(f"{k}{v}" for k, v in c.items())


_chain_done = 0  # 완료 체인 카운터(진행도 [n/total] 표기용, 요청 내 단일 루프라 안전)


async def _run_chain_logged(label: str, elems: list, factory, idx: int, total: int) -> ChainResult:
    """한 체인을 실행하며 세부 파트 진행도·소요시간을 로그로 남긴다(요소 있는 체인만 호출).

    체인은 asyncio.gather로 동시 실행되므로 [n/total]은 '완료 순서'다. 예외는 gather가
    return_exceptions=True로 잡도록 그대로 올린다(요소 격리 정책 유지).
    """
    global _chain_done
    if idx == 0:
        _chain_done = 0
    from app.utils.req_log import step
    t0 = time.monotonic()
    try:
        result = await factory(elems)
    except Exception as exc:
        _chain_done += 1
        logger.error("    [%d/%d] %s 실패(%.1fs): %s", _chain_done, total, label,
                     time.monotonic() - t0, exc)
        raise
    _chain_done += 1
    n_llm = len(result[1]) if isinstance(result, tuple) else 0
    step(_chain_done, total, label, f"{len(elems)}요소→{n_llm}블록 {time.monotonic() - t0:.1f}s")
    return result


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
    with stage("추출") as st:
        if _txt_result_path(task).exists():
            extraction = _read_txt_result(task)
            st.note = "캐시 재사용"
        else:
            doc_meta, extraction = await _extract_with_hyunju(task)
            _write_txt_result(task, extraction)
            _debug_dump(task, "02_doc_meta", doc_meta.model_dump())
        method0 = extraction.get("meta", {}).get("extraction_method", "?")
        st.note = f"{len(extraction.get('elements', []))}요소 · {method0}"

    # 원본 페이지 크기(경계 meta) → 응답 image_width/height. bbox와 같은 좌표계(2x 픽셀).
    _meta0 = extraction.get("meta", {})
    image_width = int(_meta0.get("image_width") or 0)
    image_height = int(_meta0.get("image_height") or 0)

    # Phase 2 (태민): 경계 파일 → 분해 → 6-체인
    layout_result, ext_map, method = _parse_txt_result(extraction, page_id)
    routing_tier = (
        doc_meta.routing_tier if doc_meta
        else ("ZERO" if method == "TEXT_NATIVE" else "STANDARD")
    )
    include_braille = task.mode == "c"

    # 체인 팩토리(라벨 → coroutine). _run_formula_chain만 layout 인자가 없어 시그니처가 달라
    # 람다로 통일한다. 요소가 있는 체인만 활성화해 로그·연산을 줄인다.
    _factory = {
        "텍스트": (_TEXT_TYPES, lambda e: _run_text_chain(e, layout_result, routing_tier, task, include_braille)),
        "수식": ({"formula"}, lambda e: _run_formula_chain(e, routing_tier, task, include_braille)),
        "표": ({"table"}, lambda e: _run_table_chain(e, layout_result, routing_tier, task, include_braille)),
        "그림": ({"image"}, lambda e: _run_image_chain(e, layout_result, routing_tier, task, include_braille)),
        "만화": ({"cartoon"}, lambda e: _run_cartoon_chain(e, layout_result, routing_tier, task, include_braille)),
        "차트": ({"chart_graph"}, lambda e: _run_chart_graph_chain(e, layout_result, routing_tier, task, include_braille)),
        "도표": ({"diagram"}, lambda e: _run_diagram_chain(e, layout_result, routing_tier, task, include_braille)),
    }
    active = [(label, _collect(layout_result, ext_map, types), fn)
              for label, (types, fn) in _factory.items()
              if _collect(layout_result, ext_map, types)]

    # HCXT(단일 GPU 직렬)가 페이지 예산을 독점하지 못하게 누적 상한을 건다. 남은 페이지 시간
    # (추출 경과 반영)과 config 비율 중 작은 값. 초과분 요소는 GPT-4o(병렬)로 폴백.
    _remaining = config.page_timeout_seconds - elapsed() - 5.0   # 조판·응답 여유 5s
    set_hcxt_budget(min(config.page_timeout_seconds * config.hcxt_page_budget_ratio, _remaining))

    with stage("점역", gpu=True) as st:
        st.note = _type_breakdown(layout_result)
        chain_results = await asyncio.gather(
            *(_run_chain_logged(label, elems, fn, i, len(active))
              for i, (label, elems, fn) in enumerate(active)),
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
        with stage("조판"):
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
    ext_by_id = {e.element_id: e for e in extracted}

    def _meta_fields(eid) -> dict:
        """proto TextElement 부가 필드 — 수식 latex·시각자료 subtype(추출에서 가져옴)."""
        e = ext_by_id.get(eid)
        return {
            "latex_string": (e.latex_string or "") if e else "",
            "visual_subtype": (e.visual_subtype or "") if e else "",
            "subtype_confidence": float(e.subtype_confidence)
            if e and e.subtype_confidence is not None else 0.0,
        }

    # 응답 리스트는 문서 읽기 순서로 정렬한다. (6체인 gather 결과는 type별로 묶여 있어
    # 그대로 내보내면 본문 위 그림 등에서 순서가 뒤바뀐다 — FE가 order로 렌더 가능하도록.)
    _order_of = {e.element_id: e.reading_order for e in layout_result.elements}
    llm_outputs = sorted(llm_outputs, key=lambda o: _order_of.get(o.element_id, 1_000_000))

    # PART 11: 품질 판정 — C/R 감지 후 status 결정 (COMPLETED|NEEDS_REVIEW|BLOCKED)
    from app.ai.quality.quality_checker import QualityChecker
    quality_report = QualityChecker().check(
        page_id,
        layout_result=layout_result,
        extracted=extracted,
        llm_outputs=llm_outputs,
        braille_outputs=braille_outputs,
        line_overflow_rate=line_overflow_rate,
    )

    response: dict = {
        "job_id": task.job_id,
        "status": quality_report.status,
        "page_number": task.page_no,
        "processing_meta": {
            "processing_time_ms": 0,
            "pdf_layer_confidence": doc_meta.pdf_confidence if doc_meta else 0.0,
            "routing_tier_used": routing_tier,
            "scan_only": doc_meta.scan_only if doc_meta else False,
        },
        "quality_report": quality_report.model_dump(),
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
                **_meta_fields(o.element_id),
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
                # opt(텍스트)뿐 아니라 braille 단계 실패(요소 격리 placeholder)도 블록으로 집계.
                "is_blocked": (
                    "[처리 불가" in o.corrected_text
                    or any("[처리 불가" in ln for ln in (
                        braille_by_id[o.element_id].braille_lines
                        if o.element_id in braille_by_id else []
                    ))
                ),
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
                **_meta_fields(o.element_id),
            }
            for i, o in enumerate(llm_outputs)
        ]

    # 요소별 검수 등급 — 점역사가 어디부터 볼지 정하는 신호(정답 없이 런타임 계산).
    # HIGH도 실측 정확도 88.7%라 "확인 불필요"가 아니다 — 순서·주의 표시 용도다.
    try:
        from app.ai.quality import confidence as _conf
        from app.utils.braille_back import decode as _decode
        _srcs = {t.get("id"): t for t in (response.get("text_list") or [])}
        _conf.annotate(response.get("braille_text_list") or [], _srcs, _decode)
        # 페이지 수준 '내용 누락 의심' 고지(R11) — gold 없이 런타임 계산, 셀 출력 불변
        # 메타데이터라 KPI에 영향 없음. 시각자료·표에 내용이 몰린 페이지를 저오탐으로 짚음.
        _risk = _conf.page_content_risk(response.get("braille_text_list") or [])
        if _risk and "quality_report" in response:
            response["quality_report"].setdefault("review_flags", []).append(
                {"type": "R11", "element_id": "page", "message": _risk})
    except Exception as exc:  # noqa: BLE001 — 등급 실패가 점역 결과를 막지 않는다
        logger.warning("검수 등급 산출 실패(무시): %s", exc)

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
    """파이프라인 진입점. 300초 하드 타임아웃 강제."""
    start_request()   # 요청 단위 API 카운터 초기화
    logger.info("━━ job=%s page=%d/%d mode=%s 처리 시작 ━━",
                task.job_id, task.page_no, task.total_pages, task.mode)
    start = time.monotonic()
    try:
        result = await asyncio.wait_for(
            _run_pipeline(task),
            timeout=config.page_timeout_seconds,
        )
        elapsed_ms = int((time.monotonic() - start) * 1000)
        result["processing_meta"]["processing_time_ms"] = elapsed_ms
        n_braille = len(result.get("braille_text_list") or [])
        logger.info(
            "✅ %s  총 %.1fs · API %s · 점자 %d줄  (job=%s page=%d mode=%s)",
            result.get("status"), elapsed_ms / 1000, api_summary(), n_braille,
            task.job_id, task.page_no, task.mode,
        )
        for _line in breakdown_lines():   # 파트별 LLM 사용 내역(디버깅·비용 추적)
            logger.info(_line)
        _record_metrics(result, elapsed_ms)
        return result

    except asyncio.TimeoutError:
        elapsed_ms = int((time.monotonic() - start) * 1000)
        logger.warning("⛔ BLOCKED(타임아웃) %.1fs · API %s  (job=%s page=%d)",
                       elapsed_ms / 1000, api_summary(), task.job_id, task.page_no)
        result = _build_timeout_response(task, elapsed_ms)
        _record_metrics(result, elapsed_ms)
        return result

    except Exception as exc:
        elapsed_ms = int((time.monotonic() - start) * 1000)
        logger.exception("⛔ BLOCKED(예외) %.1fs job=%s page=%d: %s",
                         elapsed_ms / 1000, task.job_id, task.page_no, exc)
        result = _build_exception_response(task, elapsed_ms, exc)
        _record_metrics(result, elapsed_ms)
        return result


def _record_metrics(result: dict, elapsed_ms: int) -> None:
    """PART 11 후반: 페이지 메트릭 기록. 실패해도 응답에 영향 금지."""
    try:
        from app.ai.quality.metrics_collector import MetricsCollector
        MetricsCollector().record(result, elapsed_ms=elapsed_ms)
    except Exception as exc:
        logger.warning("메트릭 수집 실패(무시): %s", exc)
