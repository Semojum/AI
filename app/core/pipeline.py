"""파이프라인 진입점.

단계 3·4 구조: 현주 추출 → data/NNN_txt_result.json → 태민 분해/점역 → 단계별 json → 최종 결과

  공통 경계 파일: storage/jobs/{job}/temp/page_{no:03d}/data/{no:03d}_txt_result.json
    형식 {meta:{job_id,page_no,extraction_method,image_width,image_height,bbox_space},
          elements:[{id,order,type,content,bbox}]}
      · bbox_space: "pixel"(2x 렌더 픽셀) | "norm1000"(0~1000). 생산자가 적고 소비자가 읽는다.
    - 현주 파트(PART 2/3/4-1/5-1 등)가 생성. 이미 존재하면 그대로 사용(핸드오프).
    - 태민 파트가 읽어서 6-체인(현재 text/formula 동작)으로 분해→opt→braille.

  mode a: 현주추출 → 파일 → text_list 반환
  mode b: source_text → 4-2 → 4-3 → 10 (braille_text_list 반환)
  mode c: 현주추출 → 파일 → 6-체인 → 10 (양쪽 반환)

단계 4(시각자료: table/image/cartoon/chart_graph)는 파일에 해당 요소가 있을 때 동작.
"""

from __future__ import annotations

from contextvars import ContextVar
import asyncio
import hashlib
import json
import os
import re
import time
from functools import lru_cache
from pathlib import Path
from typing import Optional
from uuid import UUID, uuid4, uuid5

from app.core.config import config, process_env
from app.ai import gates
from app.schemas.content import BrailleOutput, ExtractedContent, LLMOutput
from app.schemas.layout import BBoxItem, DocumentMeta, LayoutResult
from app.schemas.quality import CriticalError, QualityReport
from app.core.limits import run_braille
from app.schemas.task import PageTask
from app.utils import llm_cache
from app.utils.logger import get_logger
from app.utils.req_log import (
    api_summary,
    breakdown_lines,
    elapsed,
    llm_counter_line,
    review_signal_line,
    set_hcxt_budget,
    stage,
    start_request,
    usage_report,
)

logger = get_logger(__name__)

# 텍스트 요소 유형 — text 체인이 처리하는 요소들
_TEXT_TYPES = {"text", "title", "caption", "list_item", "footnote", "sidebar", "header_footer", "page_number"}

# 시각 요소 유형 — 그림 회수 판정(_extract_with_hyunju)과 읽기순서(_reorder_columns)가 공유
_VISUAL_TYPES = {"image", "chart_graph", "cartoon", "diagram", "figure", "table"}

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
    re.compile(r"^(?:©|Copyright\b)", re.IGNORECASE),    # 저작권 고지(라틴 기호)
    # ⓒ(U+24D2)는 한국 교과서에서 **보기 표시 문자**(ⓐⓑⓒⓓ)로도 쓴다. 종전 패턴
    # `^(?:ⓒ|©|Copyright\b)`는 그 보기 항목을 고지로 보고 **요소를 통째로 버렸다**
    # (아래 _parse_txt_result의 `continue`). 점역사가 가장 발견하기 어려운 결함이다 —
    # ⓐⓑ 다음에 ⓓ가 나오는 것은 묵자와 나란히 놓고 대조해야 보인다.
    # 실측(코퍼스 1,180쪽·요소 28,083개 전수, 2026-09-07): ⓒ로 시작하는 요소는 **5개뿐이고
    # 다섯 다 정답 점자책에 있는 본문**(614셀, gold 일치도 0.86~0.98)이다. ⓒ가 진짜 고지를
    # 잡은 건 **0건**이고, `©`·`Copyright`로 시작하는 요소도 0건이다.
    # 그래서 ⓒ는 발행처·고지 문구가 같이 있을 때만 고지로 본다(회귀 케이스
    # "ⓒ EBS 한국교육방송공사"는 그대로 걸린다).
    re.compile(r"^ⓒ\s*(?=.{0,40}(?:EBS|한국교육방송|All\s*rights|Copyright|무단|저작권))",
               re.IGNORECASE),
    # 무단복제 금지 고지 — 판권 문구의 한국어 판본. 위 ⓒ 패턴과 같은 부류인데 'EBS 허락없이…'로
    # 시작해 걸리지 않았다. 실측(dev+val 1,131p): 10요소 전부 문장 하나짜리 단독 요소이고
    # 정답 도서 출현 0건. 본문 문장이 우연히 걸리지 않도록 고지문 통째(끝맺음까지)를 요구한다.
    re.compile(r"^\S{0,12}\s*허락\s*없이.{0,140}?금지되어\s*있습니다\.?$"),
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
_HF_TAG_RE = re.compile(r"<!/?[^>]+>")      # 러닝풋 판정 전 <!강조> 등 인라인 태그 제거

# ── 지면 가장자리 머리글·표지 억제 (2026-08-24) ─────────────────────────────
# 러닝풋 억제(_is_running_foot)는 `header_footer` 타입에만 걸린다. 그런데 실측하니
# 머리글의 대부분이 **`text` 타입으로 온다**(text 36 · header_footer 6 · title 1).
# 그래서 `2027학년도 EBS 수능특강 문학`·`정답과 해설 21` 같은 배너가 본문에 실렸다.
#
# 판정은 **지면 가장자리 + 배너 문구** 둘 다일 때만 한다. 실측 100쪽 전수에서
# **억제 65건 · 손해 0건**(gold 에 있는데 지우는 것)이다.
# ⚠ 어제(C-59)는 손해가 더 크다고 봤는데 그건 검증 도구가 **공통 4셀만 맞아도 "gold 에
#   있다"** 로 판정한 착시였다. 정렬점수 0.6 임계를 걸어 다시 재 결과가 위 수치다(C-61).
_PAGE_EDGE_BAND = 0.07                      # 지면 위아래 7% 안
# ⚠ `학년도`·`N회` 단독은 넣지 않는다. 정답본이 **출처 표기**로 살린다
#   (`2025학년도 수능`·`2026학년도 6월 모의평가`·`1회`). 실측 손해 12건 중 셋이 이것이다.
#   `수능특강`이 붙은 도서명 배너만 잡는다.
_HEADER_BANNER_RE = re.compile(r"정답과\s*해설|수능특강|실전학습|주제·소재편")
# 본문 상호참조는 머리글이 아니다 — `정답과 해설 125쪽`. 지면 가장자리에 와도 살린다.
_XREF_RE = re.compile(r"\d+\s*쪽")
# 머리글 뒤에 글상자가 붙은 요소는 통째로 지우면 테두리를 잃는다(`정답과 해설 21` + 글상자).
_BOX_TAG_RE = re.compile(r"<!상자")


def _page_edge_band(elements: list[dict]) -> tuple[float, float, float] | None:
    """요소 bbox 로 지면 위·아래 끝과 높이를 낸다. bbox 가 없으면 None(억제 안 함)."""
    ys = [(e["bbox"][1], e["bbox"][3]) for e in elements
          if isinstance(e.get("bbox"), (list, tuple)) and len(e["bbox"]) >= 4]
    if not ys:
        return None
    top = min(y for y, _ in ys)
    bot = max(y2 for _, y2 in ys)
    return (top, bot, bot - top) if bot > top else None


def _is_edge_header(content: str, bbox, band: tuple[float, float, float] | None) -> bool:
    """지면 가장자리에 놓인 머리글·표지 배너인가."""
    if band is None or not isinstance(bbox, (list, tuple)) or len(bbox) < 4:
        return False
    top, bot, h = band
    if (bbox[1] - top) / h > _PAGE_EDGE_BAND and (bot - bbox[3]) / h > _PAGE_EDGE_BAND:
        return False                        # 지면 가장자리가 아니다
    c = _HF_TAG_RE.sub("", content or "")
    if not _HEADER_BANNER_RE.search(c) or _XREF_RE.search(c):
        return False
    return not _BOX_TAG_RE.search(content or "")


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


# ── 추출 실패 안내문 억제 (2026-07-26) ────────────────────────────────────
# 4분류: ① 데이터 오류 — 경계 파일의 요소 content가 '그 영역의 글자'가 아니라 **추출
# 모델이 스스로 못 읽었다고 쓴 해설문**인 경우. 우리는 이걸 본문 텍스트로 믿고 그대로
# 점역해 인쇄한다(영문 안내문이 한글 점자로 찍혀 학생에게 나간다).
#
# 실측(2026-07-26, dev+val 1,131p·요소 28,425개 전수):
#   · 해당 요소 2건 — 생물 원본 p043(job page_030)·p175(page_130), 둘 다 type=header_footer,
#     내용은 페이지 머리의 장식 삽화(책꽂이 선화)를 두고 쓴 해설이다.
#       "The image contains no discernible text or characters. It is a simple line drawing
#        of a bookshelf ... Therefore, no OCR output can be generated."   (183자)
#       "... Therefore, the correct OCR output is an empty string."        (200자)
#   · 아래 패턴의 오검출 0건 — 검출은 위 2건뿐이고, 영문 위주(ASCII 90%↑)·60자 이상인
#     요소 약 960개가 오검출 위험 모수다(집계 정의에 따라 957~963 — 독립 검증 재집계
#     2026-07-26. 판정에 쓰는 수치가 아니라 위험 규모 감각용이다). 외국어 지문이 'There is no question…',
#     'It is not uncommon…'처럼 부정문을 흔히 쓰므로, 패턴은 **OCR/판독 작업 자체를
#     자기언급하는 표현**만 잡도록 좁혔다(단순 부정문·'The image shows…' 류는 제외).
#     (재현: temp/r29_census.py)
#
# 처리는 **인쇄 생략 + 검토 플래그(R11)**다. [처리 불가: …] 플레이스홀더를 쓰지 않는다:
#   · 규정 근거 — 점자 자료 제작 지침 6.3.4(2)② "추가 설명이 필요 없는 시각 자료: …
#     '시각 자료 유형 생략'의 형식으로 적는다. 다만 시각적 장식 용도로 제시되어 있거나
#     본문을 이해하는 데 필요하지 않은 경우에는 생략 여부를 표기하지 않는다." 위 2건은
#     장식 삽화이므로 '표기하지 않는다'에 해당한다.
#   · 코드 선례 — app/ai/llm/image_opt.py: "실패 문자열('[처리 불가: …]')을 내면 그 한글이
#     그대로 점자로 찍혀 학생에게 나간다 — 어떤 경우에도 정당하지 않다. 점역사에겐
#     flags→R11로 알린다."
# 요소를 통째로 버리지 않고 content만 비우는 이유: 버리면 그 자리가 있었다는 사실까지
# 사라져 점역사가 확인할 단서가 없다. 비우면 R11(IMAGE_TEXT_MISSING)이 떠서
# "이 자리 원본을 직접 보라"는 신호가 남는다(실측: 두 페이지 모두 status=NEEDS_REVIEW,
# quality_report.review_flags에 R11, bbox flags=['R11'], 인쇄물에 영문 안내문 0줄).
# ★ 2026-09-08(재구조화 2단계) — 정규식 표와 판정은 `app/ai/gates.py` 로 옮겼다(위 import).
#   관문 G1(`captioner.guard_llm_text`)이 **같은 표**를 봐야 한다(설계 §2-2). captioner 에
#   두면 pipeline 이 openai 를 무는 모듈을 최상단에서 import 하게 되어 빠른 게이트가 깨진다.
#   이 자리의 검사(`_parse_txt_result`)는 그대로 둔다.
_is_extraction_refusal = gates.is_extraction_refusal


# ── 응답 빌더 ─────────────────────────────────────────────────────────────

# 쪽 대표 레이아웃 유형(대시보드 T1-2 집계 축) — **비싼 쪽이 이긴다.**
# 실측 원가가 그림 94 > 표 58 > 수식 46 > 본문 21원/쪽이라 이 순서다. 그림 하나만
# 섞여도 그 쪽은 그림 쪽이다 — 개수로 세면 비싼 요소가 본문에 묻혀 유형별 평균이 흐려진다.
_LAYOUT_RANK = (
    ("visual",  {"image", "cartoon", "chart_graph", "diagram"}),
    ("table",   {"table"}),
    ("formula", {"formula"}),
)


def _page_layout_type(result: dict) -> str:
    """응답의 요소 유형들 → 쪽 대표 유형. 요소가 없으면 "" (BLOCKED 쪽 등)."""
    types = {(t.get("type") or "") for t in (result.get("text_list") or [])}
    if not types:
        return ""
    for name, members in _LAYOUT_RANK:
        if types & members:
            return name
    return "text"


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


def _atomic_write(path: Path, text: str) -> None:
    """임시 파일에 쓰고 rename. 중간에 죽어도 반쪽짜리 경계 파일이 안 남는다.

    ★ 반쪽 경계 파일은 다음 실행에서 `exists()` 로는 멀쩡해 보이고 `json.loads` 에서
      터진다 — 그 쪽만 죽는 게 아니라 job 전체가 같은 자리에서 반복해 죽는다.
    """
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def _write_txt_result(task: PageTask, extraction: dict,
                      doc_meta: DocumentMeta | None = None) -> None:
    p = _txt_result_path(task)
    p.parent.mkdir(parents=True, exist_ok=True)
    _atomic_write(p, json.dumps(extraction, ensure_ascii=False, indent=2))
    # 경계 파일이 먼저, stamp 가 나중. 순서를 뒤집으면 stamp 만 남은 자리를 유효로 읽는다.
    _write_extract_stamp(task, extraction, doc_meta)


# ── 경계 stamp (재구조화 3-a: **쓰기만**) ──────────────────────────────────
# 이 경계 파일이 **어느 판의 추출**로 만들어졌는지 옆에 적어 둔다. 읽고 판정해 재파생하는
# 것은 3-d 다 — 여기서는 아무것도 읽지 않는다(동작 변화 0).
# ★ 경계 파일 **안에** 넣지 않는다. 넣으면 판이 바뀔 때마다 경계 바이트가 달라져
#   재현 diff 자(설계 §3-2)가 판 지문을 재는 자로 변한다. 옆 파일로 둔다.
# ★ 파일명에 `_txt_result` 를 넣지 않는다 — `test/corpus_runner.py:393` 이
#   `*_txt_result.json` 을 glob 한다. 넣으면 코퍼스 러너가 stamp 를 경계 파일로 읽는다.
# ★ 커밋 해시가 아니라 **추출 단계 파일들의 내용 해시**다(설계 2-3 "빠진 것 #10").
#   본문 점역·조판 커밋으로는 값이 안 바뀌어야 재파생이 헛돌지 않는다.
_EXTRACT_SOURCES = (
    "app/ai/parser/mineru_runner.py",
    "app/ai/parser/hancom_glyphs.py",       # 층 글 되돌리기 표 · 모르는 글리프(#1060 · #376) — 경계 글이 바뀐다
    "app/ai/parser/figure_detect.py",
    "app/ai/parser/opus_fallback.py",
    "app/ai/captioning/captioner.py",
    "app/ai/captioning/classifier.py",
    "app/ai/builder/result_builder.py",
    "app/ai/parser/extraction_losses.py",   # 경계 파일의 `extraction_losses` 를 만든다(T35)
    "app/ai/preprocessor/line_join.py",     # 경계 요소를 잇는다(요소 수·flags 가 바뀐다)
)
# 추출 산출을 가르는 스위치만. 값 자체는 안 싣는다(키가 섞일 수 있다) — 해시만.
_EXTRACT_ENV = (
    "FIGURE_DETECT", "FIGDET_MODEL", "DISABLE_LLM_FALLBACK",
    "CAPTION_BACKEND", "CAPTION_MODEL", "CAPTION_CACHE_DIR",
    "MINERU_BIN", "CHAIN_SEQUENTIAL",
    # ★ T39 S5 전수(2026-09-30) — 경계 내용을 바꾸는데 빠져 있던 것. 운영에서 바꿔도 옛 경계를 그대로
    #   재사용했다(eval 실측: MINERU_MATH_FONT_GUARD 하나로 경계 8쪽 중 4쪽이 바뀐다). 캡션을 통째로 끄는
    #   SEMOJUM_NO_CAPTION 도 없었다 — 끄고 뜬 경계가 켠 실행에 그대로 쓰였다.
    #   새 스위치를 추출 단계에 넣으면 여기 또는 `test_extract_env_fingerprint` 의 "경계 무관" 표에 적는다.
    "MINERU_MATH_FONT_GUARD", "MINERU_EFFORT", "MINERU_BACKEND", "MINERU_ENGINE",
    "LAYER_GATE_AFTER_RESTORE", "LAYER_GATE_LATEX_GUARD", "LAYER_CTRL_TO_SPACE",      # #1072 층 신뢰 게이트
    "LAYER_HALLUC_RULE",                                                               # #1078 환각 층 대체 · R4 표시
    "LAYER_HALLUC_STRUCT",                                                             # #1274 표 · 수식 환각 R4 표시
    "LAYER_LATEX_COUNT_GUARD",                                                         # #1130 층 글 첨자 수 가드
    "BOX_FALSE_OUTER",                                                                 # #1149 가짜 바깥 상자 빼기
    "BOX_Q_FRAME_TABLE",                                                               # #1149 표 품은 문항 틀 빼기
    "UL_WIDTH_GUARD",                                                                  # #1148 글보다 넓은 선은 밑줄 아님(강조 축 C)
    "UL_FRAC_GUARD",                                                                   # #1166 분수선은 밑줄 아님(강조 축 E)
    "TEXT_FRACTION",                                                                   # #1183 글로 된 분수 → 분모 ⠌ 분자
    "TABLE_LAYER_CTRL",                                                                # #1148 표 경로 층 글의 제어 문자 띄움
    "TABLE_CELL_PIECES",                                                               # #1208 긴 칸 층 조각 대조
    "TABLE_CELL_CIRCLED_DIGIT",                                                        # #1210 표 칸 ㉠ → 민 숫자 되돌리기
    "TABLE_MISREAD_FIX",                                                               # #1296 포기한 표의 한 음절 오독 고치기
    "LAYER_LENGTH_MARK",                                                               # #1222 긴소리표 ː 를 층 관문에서 안 셈
    "LAYER_UNKNOWN_GLYPH",                                                             # #376 표에 없는 수식 글꼴 글리프 블록은 층 불신
    "HANCOM_FRACTION",                                                                 # #1055 한컴 작은 수 분수 풀기
    "ITALIC_TAG",                                                                      # #1205 영어 줄 기울임 태그
    "ZERO_FOOT_PAGE_NUMBER",                                                           # #1247 ZERO 꼬리말 쪽 번호 떼기
    "SEMOJUM_NO_CAPTION", "CAPTION_MATERIAL", "CAPTION_UPSCALE", "CAPTION_FAIL_STREAK_LIMIT",
    "LLM_TEXT_GUARD", "LLM_CACHE_MODE", "SIDEBAR_AS_NOTE", "GRAFT_SIM_MIN",
    "ADVANCED_EXTRACT_MODE", "ADVANCED_EXTRACT_MODEL", "ADVANCED_EXTRACT_FALLBACK_MODEL",
    "ADVANCED_EXTRACT_RELABEL", "ADVANCED_EXTRACT_MAX_TOKENS", "ADVANCED_EXTRACT_RETRY_BUDGET",
    "ADVANCED_KEEP_CAPTIONS", "STABLE_ELEMENT_ID", "GUARD_MONOLOGUE", "GUARD_SENTENCE_VOICE", "ANSWER_BOX_TEXTLAYER", "CAPTION_MARKERS", "CAPTION_DECOR_KEEP",
    "ANSWER_MARK_TEXT", "NUM_BADGE_TEXT", "TEXTLAYER_GLYPH_RESTORE", "CAPTION_KEEP_SOURCE",
    "IMAGE_AS_CAPTION_NOTE", "ORPHAN_CAPTION_FORM",                                     # #1073 인쇄 캡션 그림 표지 · F07 꼴
)


@lru_cache(maxsize=1)
def _extract_sha() -> str:
    h = hashlib.sha256()
    root = Path(__file__).resolve().parents[2]
    for rel in _EXTRACT_SOURCES:
        h.update(rel.encode())
        try:
            h.update(hashlib.sha256((root / rel).read_bytes()).digest())
        except OSError:                 # 배포본에서 파일이 없으면 그 사실을 값에 남긴다
            h.update(b"?")
    return h.hexdigest()[:12]


# 추출 단계에서 도는 LLM 자리의 판 번호만 싣는다. `visual`·`text`·`formula`·`table` 은
# **경계 파일 뒤(opt 단계)** 라 경계를 무효로 만들 이유가 없다 — 넣으면 본문 프롬프트를
# 손볼 때마다 재파생이 돌고 `element_id`(uuid4)가 갈려 점역사 피드백 참조가 끊긴다.
_EXTRACT_VER_KINDS = ("caption", "classify", "figure", "opus")


def _extract_prompt_ver() -> str:
    from app.utils.llm_cache import PROMPT_VER
    return ",".join(f"{k}={PROMPT_VER.get(k, 0)}" for k in _EXTRACT_VER_KINDS)


def _extract_env_fp() -> str:
    # ★ 캡션 API 키는 값이 아니라 **있고 없음**만 싣는다(T39 S5). 키 없이 뜬 경계는 시각 요소 캡션이
    #   전부 비어 있다(CAPTION_FAILED). 키를 넣은 뒤에도 그 경계가 그대로 재사용되면 안 된다.
    keys = f"keys={int(bool(config.anthropic_api_key))}{int(bool(config.openai_api_key))}"
    return hashlib.sha256(
        ("|".join(f"{k}={os.environ.get(k, '')}" for k in _EXTRACT_ENV) + "|" + keys).encode()
    ).hexdigest()[:12]


def _boundary_reuse(reuse_reason: str | None) -> str | None:
    """`BOUNDARY_REUSE` 스위치를 지문 판정에 얹는다. None = 경계를 그대로 쓴다, 그 밖 = 다시 뜬다(사유).

    ★ `always` 는 되돌리는 길이다. 지문 대조를 건너뛰고 옛 동작(있으면 쓴다)으로 돈다. 단 `doc_meta`
      가 없는 옛 경계 파일은 여기서도 다시 뜬다 — 그게 없으면 티어를 되짚을 수밖에 없고, 되짚으면 틀린다.
    ★ `never` 는 반대로 **늘 다시 뜬다**(T39 S2). 추출 · 캡션 · 순서 · 그림 회수를 바꾼 A/B 는 경계를
      다시 떠야 차이가 보인다. 지문에 안 잡히는 변경도 이 팔에서는 다시 돈다.
    프로세스 env 로만 읽는다(`.env` 아님 — `.env` 는 빈 값에도 진다).
    """
    from app.core.config import measure_reuse
    if not measure_reuse():                 # 제품은 같은 job 쪽도 늘 다시 뜬다(#1212, config.measure_reuse)
        return "reconvert"
    mode = process_env("BOUNDARY_REUSE") or ""
    if mode == "never":
        return "never"
    if reuse_reason and reuse_reason != "no_doc_meta" and mode == "always":
        return None
    return reuse_reason


def _stamp_path(task: PageTask) -> Path:
    return _page_dir(task) / "data" / f"{task.page_no:03d}_extract_stamp.json"


def _write_extract_stamp(task: PageTask, extraction: dict,
                         doc_meta: DocumentMeta | None = None) -> None:
    """경계 파일 옆에 판 지문을 남긴다. 실패해도 쪽은 나가야 한다.

    `doc_meta` 를 같이 싣는 이유(3-d): 재사용 경로에서 티어를 `extraction_method` 로
    되짚으면 틀린다(원장 `routing-tier-from-run-state`). 만든 자리에서 적어 둔다.
    """
    try:
        from app.core.health_check import prompt_sha
        _atomic_write(_stamp_path(task), json.dumps({
            "extract_sha": _extract_sha(),
            "prompt_ver": _extract_prompt_ver(),
            # 참고용. **판정에 안 쓴다** — `prompt_sha()` 는 opt 단계 프롬프트(visual·text·
            # formula·table)까지 묶은 값이라 본문 문안만 고쳐도 값이 바뀐다.
            "prompt_sha": prompt_sha(),
            "env_fp": _extract_env_fp(),
            "method": extraction.get("meta", {}).get("extraction_method"),
            "doc_meta": doc_meta.model_dump() if doc_meta else None,
            "written_at": int(time.time()),
        }, ensure_ascii=False, indent=2))
    except Exception as exc:            # noqa: BLE001 — 지문 한 줄이 쪽을 죽이면 안 된다
        logger.debug("경계 stamp 기록 실패(진행): %s", exc)


# ── 경계 stamp 읽기 (재구조화 3-d) ────────────────────────────────────────
# 같은 job 을 다시 돌릴 때 경계 파일을 그대로 쓸지, 추출을 다시 돌릴지 여기서 가른다.
# 종전에는 "파일이 있으면 쓴다" 뿐이라, 캡션 프롬프트를 고쳐도 그 job 에서는 실행조차
# 안 됐다(원장 `boundary-file-freezes-captions-too`, 0902 에 두 라운드 무효).
# ⚠ 판정에 커밋 해시를 쓰지 않는다. 배포마다 재파생하면 `element_id` 가 갈려
#   점역사 피드백의 요소 참조가 끊긴다(설계 2-3 "빠진 것 #10").
def _stamp_verdict(task: PageTask) -> tuple[str | None, dict]:
    """(무효 사유, stamp). 사유가 None 이면 그대로 재사용해도 된다."""
    try:
        stamp = json.loads(_stamp_path(task).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return "no_stamp", {}
    for field, live in (("extract_sha", _extract_sha()),
                        ("prompt_ver", _extract_prompt_ver()),
                        ("env_fp", _extract_env_fp())):
        if stamp.get(field) != live:
            return field, stamp
    if not stamp.get("doc_meta"):
        return "no_doc_meta", stamp
    return None, stamp


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

async def _gather_chains(coros):
    """체인들을 모아 실행. 요소 격리(불변 규칙 3)를 위해 예외를 값으로 돌려준다.

    ★ `CHAIN_SEQUENTIAL=1`이면 gather 대신 **순차 await**로 돈다(2026-08-21).
      진단 전용 스위치다 — 같은 입력에 산출이 갈리는 쪽이 있는데(NULL 두 벌 1/709,
      실험 두 벌 34/709), 그 원인이 체인 동시 실행의 공유 상태인지 가리려면 순차 조건이
      필요하다. 순차에서도 갈리면 동시성이 아니고, 안 갈리면 동시성이 원인이다.
      기본은 꺼져 있고, 켜면 느려지므로 운영에서는 쓰지 않는다.
    """
    if process_env("CHAIN_SEQUENTIAL") == "1":
        out = []
        for c in coros:
            try:
                out.append(await c)
            except Exception as exc:      # noqa: BLE001 — gather(return_exceptions=True)와 같은 계약
                out.append(exc)
        return out
    return await asyncio.gather(*coros, return_exceptions=True)


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


def _blocks_with_bbox(blocks: list[dict], page_h: float = 0) -> list[dict]:
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
    return _split_foot_number(elements, page_h)


# ZERO 꼬리말 블록의 쪽 번호(#1247). ZERO 층은 쪽 번호가 꼬리말 글과 한 블록으로 온다(`24  2027학년도 EBS
# 수능특강 생활과 윤리` · `06강 항상성  85`). 숫자만 든 블록이 아니라 `page_number` 로 안 잡혀, d8c dev·val ZERO
# 300쪽 중 페이지행 원본 쪽 번호가 맞은 쪽이 0 이었다. 300쪽 모두 쪽의 가장 아래 블록이 그 꼬리말이고(윗변이 쪽
# 높이 94%), 앞이나 뒤 숫자가 그 쪽 번호다(앞 147 · 뒤 153, 다른 꼴 0). 결과 V2 temp/n10/결과_ZERO쪽번호_1247.md.
_FOOT_NUM_RE = re.compile(r"(\d{1,3})\s{2,}(\S.*)|(.*\S)\s{2,}(\d{1,3})", re.S)
_FOOT_BAND = 0.9                # 블록 윗변이 쪽 높이의 이 비율 아래


def _split_foot_number(elements: list[dict], page_h: float) -> list[dict]:
    """쪽 가장 아래 블록이 아래 띠의 꼬리말이면 앞이나 뒤 쪽 번호를 `page_number` 요소로 떼어 맨 앞에 둔다(#1247).

    ★ 맨 앞에 둔다. 페이지행은 첫 `page_number` 를 원본 쪽 번호로 쓰는데, 꼬리말은 대개 차례 끝 블록이고
      쪽 안 그래프 눈금 `0` 같은 숫자 블록이 그 앞에 온다(생명과학 p0085).
    ★ 좌표를 안 단다(`_blocks_from_text` 요소처럼). 꼬리말 글과 같은 사각형을 주면 문항 번호 붙이기(`_join_item_numbers`
      왼쪽 끝 짝)가 번호를 꼬리말 글에 도로 붙인다. 좌표 없는 요소는 붙이기 · 되돌리기(`_unpage_item_numbers`)와
      지면 가장자리 띠(`_page_edge_band`)가 안 본다. (0,0,0,0)을 달면 띠 윗변이 0 으로 끌려 머리글 억제가 흔들린다.
    꼬리말 글은 그대로 둔다. 적을지 말지는 규정(제작 지침 §2.1.2 '페이지행에 꼬리말을 적는다')과 gold(91.4% 안 적음)가
    갈려 자문 대기다(원장 C-86). `수능특강` · `정답과 해설` 배너는 종전대로 `_is_edge_header` 가 거른다.
    ★ MinerU 도 꼬리말을 쪽 번호와 한 블록으로 낸다(`02. 사회·문화 현상의 연구 방법  23`, #1264). 그래서
      `_parse_txt_result` 가 모든 경로에 이 함수를 다시 건다(ZERO 는 이미 뗐으니 그대로 지나간다).
      · MinerU 는 대개 같은 번호를 `page_number` 로 따로도 낸다(dev · val 659쪽 중 656). 그때는 글에서만 뗀다.
      · 꼬리말 고르기에서 `page_number` 는 뺀다. 쪽 번호 블록이 꼬리말보다 조금 아래 있으면(윗변 947 대 945)
        그것이 가장 아래 블록이 되어 꼬리말을 못 골랐다.
      · 남겨 두면 32칸에서 접혀 쪽 번호만 홀로 선 줄이 본문에 생긴다(16줄, #1264).
    끄기 `ZERO_FOOT_PAGE_NUMBER=0`(이름과 달리 MinerU 쪽도 같이 끈다).
    """
    if not page_h or os.environ.get("ZERO_FOOT_PAGE_NUMBER", "1") == "0":
        return elements
    boxed = [e for e in elements if isinstance(e.get("bbox"), (list, tuple)) and len(e["bbox"]) >= 4
             and e.get("type") != "page_number"]
    if not boxed:
        return elements
    foot = max(boxed, key=lambda e: e["bbox"][1])
    m = _FOOT_NUM_RE.fullmatch(foot["content"]) if foot["bbox"][1] >= _FOOT_BAND * page_h else None
    if not m:
        return elements
    foot["content"] = m.group(2) or m.group(3)
    num = m.group(1) or m.group(4)
    if any(e.get("type") == "page_number" and str(e.get("content") or "").strip() == num for e in elements):
        return elements
    for e in elements:
        e["order"] += 1
    pid = uuid5(_EID_NS, f"{foot['id']}|page_number") if _stable_ids() and foot.get("id") else uuid4()
    return [{"id": str(pid), "order": 1, "type": "page_number", "content": num}] + elements


async def _extract_via_models(
    task: PageTask, doc_meta: DocumentMeta
) -> tuple[list[dict], int, int, str]:
    """non-ZERO Tier(스캔 PDF): MinerU2.5-Pro 통합 추출 → (elements, page_w, page_h, bbox_space).
    result_builder가 이미지 분류·캡셔닝까지 거쳐 경계 elements(bbox 포함)를 만든다.
    MinerU 미설치/실패/타임아웃 시: 텍스트레이어가 있으면 PyMuPDF 폴백으로 본문을
    살리고(표·그림 구조 손실 → 요소 R1 플래그), 스캔 전용이면 빈 결과로 격리.

    ★ bbox_space를 **같이 돌려준다**. MinerU는 0~1000 정규화지만 폴백은 픽셀이라
      좌표계가 갈리는데, 종전에는 소비자가 `extraction_method`(둘 다 "OCR")로
      좌표계를 유추해 폴백 쪽 bbox가 한 번 더 확대됐다(Step8)."""
    import os
    import tempfile
    try:
        from app.ai.parser.mineru_runner import run as mineru_run
        from app.ai.builder.result_builder import build as build_result

        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
            f.write(task.pdf_data)
            tmp_path = f.name
        try:
            # ★ 추출 상한(60초)은 **슬롯을 잡은 뒤부터** 재야 한다.
            #   mineru-api가 자체 동시 상한으로 요청을 큐에 세우는데, 종전에는 그 대기
            #   중에도 subprocess 타임아웃이 이미 돌고 있었다 — 줄이 길면 정상 페이지가
            #   '느린 페이지'로 오인돼 끊긴다. 상한은 비정상 탐지기이므로 그러면
            #   탐지기가 망가진다. 대기는 페이지 예산(180초) 쪽에서만 계산한다.
            from app.core.limits import mineru_slot
            from app.utils.req_log import gpu_span
            async with mineru_slot():
                # 슬롯을 잡은 뒤부터 잰다 — 큐 대기는 GPU 점유가 아니다.
                with gpu_span("추출"):
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
        return (result.get("elements", []), int(m.get("image_width") or 0),
                int(m.get("image_height") or 0), "norm1000")
    except Exception as exc:
        logger.warning("MinerU 추출 실패: %s", exc)
        elements, w, h = await _fallback_text_layer(task, doc_meta)
        return elements, w, h, "pixel"


# 이식 짝짓기 관문 — 근거는 `_graft_text` 도크스트링(temp/graft/빠짐없이_0909.md 실측).
# 갈아 끼울 글자는 원래 글자의 이만큼은 돼야 한다. **길이**로 본다 — 글자가 깨진 것은
# 길이를 안 줄이지만 문장이 통째로 빠지면 줄어든다. 닮은 정도로 재면 많이 깨진 요소,
# 곧 우리가 고쳐야 할 바로 그 요소가 관문에 걸린다.
_GRAFT_KEEP = 0.85
_GRAFT_COVER = 0.9     # 2패스 '담김' — MinerU 글자가 LLM 글자 안에 이만큼 들어 있으면
_GRAFT_PREFIX = 0.55   # 그때도 앞머리는 이만큼 닮아야 한다(다른 문장에 붙는 것 막기)
_GRAFT_HEAD = 24       # 앞머리로 보는 글자 수
_GRAFT_LOOSE_MIN = 12  # 2패스 '담김'을 걸 최소 길이 — 짧은 토막은 아무 문장에나 들어간다
# LLM 이 그림을 설명한 줄. 본문 요소에 이것이 붙으면 지면에 없던 말이 나간다.
_GRAFT_CAPTION_HEADS = ("그림:", "그래프:", "도식:", "표:", "사진:", "지도:")
_GRAFT_SHARE = 0.6     # LLM 요소 하나가 MinerU 요소 여럿에 걸쳤을 때, 조각이 그 요소
                       # 글자를 이만큼은 담아야 그 자리 것으로 본다
_GRAFT_SHARE_SPAN = 3  # 한 LLM 요소를 나눠 가질 수 있는 MinerU 요소의 앞뒤 범위
_GRAFT_DUP = 0.8       # 이웃 요소 글자를 이만큼 머금으면 같은 말이 두 번 나간다
_GRAFT_DUP_LEN = 5     # 그 판정을 걸 이웃 글자의 최소 길이
# 빈 구역 회수(`_page_gaps`) 문턱. 전부 지면 높이에 대한 비율이라 dpi 를 안 탄다.
_GAP_PAD = 0.002       # MinerU bbox 를 이만큼 부풀려 덮는다(글자 삐침 여유)
_GAP_INK = 30          # 배경보다 이만큼 어두우면 잉크
_GAP_MIN_INK = 7e-5    # 구역이 지면 넓이의 이만큼은 잉크여야 한다
_RECOVER_SPAN = 6      # 짝 잡힌 앞뒤 요소가 이보다 벌어지면 자리를 못 잡는다
_RECOVER_FIT = 3.0     # 구역 넓이로 셈한 글자 수의 이 배까지만 세운다
_RECOVER_COL = 0.3     # 구역이 앞뒤 요소 중 하나와 가로로 이만큼 겹쳐야 한다(단 넘음 막기)
_RECOVER_TOL = 5       # 앞뒤 요소와 구역 사이에 이만큼(지면 0.5%)은 넘나들어도 낀 것으로 본다


def _graft_sim_min() -> float:
    """글자 이식 짝짓기 문턱. 되돌리려면 `GRAFT_SIM_MIN=0.45`(**호출 때** 읽는다).

    실측 근거 — `temp/graft/이식률_0908.md` §4·§5. 표본 6쪽 422요소, 실제로 글자가
    바뀐 309건을 유사도 띠별 10건씩 40건 눈으로 갈라 전체에 환산했다:

        문턱     이식   실제 바뀜   추정 개선   추정 개악
        0.45     338      309         216         78     ← 종전
        0.60     304      274         219         44
        0.75     244      214         206         20     ← 지금
        0.80     218      188         188         12

    개악은 **전부 r<0.75 에 몰려** 있었다. 그 실물은 본문 단락 90% 삭제(p2#21) ·
    다른 경우의 문장으로 바꿔치기(p4#4 `4=f(2)…` 를 `6=f(2)…` 로) · 같은 글자가 두 번
    나가는 중복(p1#45/#46 등 4쌍)이다. 0.75 로 올리면 개선은 216→206 으로 거의 안 잃고
    개악만 78→20 으로 준다. 더 올리면(0.80) 개선까지 깎인다.

    ⚠ 종전 값 0.45 의 근거는 코드·주석·커밋 메시지 어디에도 없었다. 같은 값이
      `mineru_runner._SIM_MIN` 에 근거 주석과 함께 있어 그것을 가져다 쓴 것으로 보인다.
    """
    return float(os.environ.get("GRAFT_SIM_MIN", "0.75"))


def _page_gaps(img_path, bboxes: list) -> list[list[int]]:
    """지면에서 **어떤 MinerU 요소도 안 덮은 채 글자가 있는** 구역. norm1000 사각으로 돌려준다.

    MinerU 가 지면의 줄을 통째로 안 뽑으면 갈아 끼울 자리가 없어 `_graft_text` 로는 못
    고친다(실측 30건 = 못 고친 것의 가장 큰 덩어리, `temp/graft/빠짐없이_0909.md` §5-가).
    글자로만 짝을 지으면 "MinerU 에 없다"는 판정이 안 서서 헛것이 다섯 배 나왔다.
    **좌표는 안 쓰고 있었다** — 요소들의 bbox 를 지면에 깔면 남는 빈 자리가 곧 그 자리다.

    잉크는 배경(중간값 흐림)보다 어두운 픽셀로 본다. 색 채움 상자는 흐림값도 같이
    내려가 안 걸리고, 긴 가로·세로 줄(테두리·밑줄·점선)은 글자가 아니라 걷어 낸다.
    """
    try:
        import cv2
        import numpy as np
    except ImportError:                       # 이미지 도구가 없으면 회수만 건너뛴다
        return []
    im = cv2.imread(str(img_path))
    if im is None:
        return []
    h, w = im.shape[:2]
    g = cv2.cvtColor(im, cv2.COLOR_BGR2GRAY)
    ink = (cv2.subtract(cv2.medianBlur(g, int(h * 0.011) | 1), g) > _GAP_INK).astype(np.uint8)
    ln = max(3, int(h * 0.041))
    ink = cv2.subtract(ink, cv2.bitwise_or(
        cv2.morphologyEx(ink, cv2.MORPH_OPEN, np.ones((1, ln), np.uint8)),
        cv2.morphologyEx(ink, cv2.MORPH_OPEN, np.ones((ln, 1), np.uint8))))

    pad = max(2, int(h * _GAP_PAD))
    cov = np.zeros((h, w), np.uint8)
    for b in bboxes:
        if not (isinstance(b, (list, tuple)) and len(b) == 4):
            continue
        cv2.rectangle(cov, (int(b[0] / 1000 * w) - pad, int(b[1] / 1000 * h) - pad),
                      (int(b[2] / 1000 * w) + pad, int(b[3] / 1000 * h) + pad), 1, -1)
    res = cv2.bitwise_and(ink, 1 - cov)

    # 낱자를 줄로 잇고(가로), 붙은 줄끼리 살짝 묶는다(세로).
    box = cv2.dilate(res, np.ones((3, max(3, int(h * 0.015))), np.uint8))
    box = cv2.dilate(box, np.ones((max(3, int(h * 0.003)), 1), np.uint8))
    n, lab, stats, _ = cv2.connectedComponentsWithStats(box, 8)
    out = []
    for i in range(1, n):
        x, y, bw, bh, _ = stats[i]
        if bh < h * 0.006 or bw < h * 0.010:
            continue
        if int(res[y:y + bh, x:x + bw][lab[y:y + bh, x:x + bw] == i].sum()) < h * w * _GAP_MIN_INK:
            continue
        out.append([round(x / w * 1000), round(y / h * 1000),
                    round((x + bw) / w * 1000), round((y + bh) / h * 1000)])
    out.sort(key=lambda b: (b[1], b[0]))
    return out


def _gap_fits(gap: list[int], above: list[int], below: list[int]) -> bool:
    """빈 구역이 앞뒤 요소 **사이에 끼어** 있고 같은 단인가.

    둘을 감싼 사각과 겹치기만 하면 된다고 하면, 앞뒤 요소가 단을 넘을 때 그 사각이 지면
    절반이 되어 **남의 구멍에 남의 글자**가 들어간다(실측 p4 두 건: 꼬리말·코너 제목).
    """
    gw = max(1, gap[2] - gap[0])
    return (above[3] - _RECOVER_TOL <= gap[1] and gap[3] <= below[1] + _RECOVER_TOL
            and any((min(box[2], gap[2]) - max(box[0], gap[0])) / gw >= _RECOVER_COL
                    for box in (above, below)))


def _gap_capacity(gap: list[int], per_char: float, fallback: int) -> float:
    """구역에 들어갈 글자 수. `per_char` 는 그 쪽에서 잰 글자 한 자의 넓이."""
    return (gap[2] - gap[0]) * (gap[3] - gap[1]) / per_char if per_char else fallback


def _recover_missing(mnr_els: list[dict], llm_els: list[dict],
                     at: dict[int, int], img_path) -> int:
    """MinerU 가 통째로 빠뜨린 줄을 **빈 구역 자리에** 새 요소로 세운다.

    못 고친 것 중 가장 큰 덩어리가 "요소가 아예 없다"였다(실측 30건, `temp/graft/
    빠짐없이_0909.md` §5-가). 갈아 끼울 자리가 없으니 `_graft_text` 로는 닿지 않는다.

    관문이 둘이라 헛것이 안 선다.

      ① **짝을 못 찾은 LLM 줄**만 후보다. 이것만 쓰면 안 된다 — MinerU 가 같은 내용을
         다른 LaTeX 로 갖고 있어 "없다"는 판정이 안 서고, 앞 갈래에서 6쪽에 153건이
         걸렸다(실제 누락 30건, 다섯 배가 헛것).
      ② **지면 그 자리에 잉크가 있는데 요소가 없어야** 한다(`_page_gaps`). 종전에는
         좌표를 아예 안 봤다. 요소들의 bbox 를 지면에 깔면 남는 빈 자리가 곧 누락 자리다.

    자리는 **읽기순서**로 잡는다. 짝 못 찾은 줄의 덩어리 앞뒤로 짝이 잡힌 LLM 줄이 있으면
    그 둘이 붙은 MinerU 요소 `a`·`b` 사이가 들어갈 자리다(`_RECOVER_SPAN` 이내). 구역은
    그 둘 **사이에 끼어** 있고 **같은 단**이어야 한다 — 겹치기만 하면 된다고 하면 앞뒤
    요소가 단을 넘을 때 남의 구멍에 남의 글자가 들어간다(실측 p4 두 건). bbox 는 그 구역을
    그대로 쓴다 — 지면에서 실제로 글자가 있던 자리다.

    덧관문 둘. **이웃이 이미 가진 말**이면 두 번 나가므로 안 세우고(양방향으로 본다),
    **구역에 안 들어갈 분량**이면 안 세운다(쪽마다 글자 넓이를 재서 견준다). 뒤엣것이
    없으면 12줄짜리 표가 한 줄 자리에 들어간다(p2 실측).

    실측(`temp/graft/누락회수_0909.md`): 6쪽에서 8개를 세워 **전부 지면에 실제로 있는
    글자**였고(눈으로 확인), 눈으로 센 누락 30건 중 10건을 되살렸다. 기계 계측 삭제·중복은
    끄고 켠 두 팔이 같다(삭제 0 · 중복 6).
    """
    boxes = [e.get("bbox") for e in mnr_els]
    gaps = _page_gaps(img_path, boxes)
    if not gaps:
        return 0

    import difflib
    import re as _re
    from app.ai.captioning.captioner import guard_llm_text

    def norm(t: str) -> str:
        return _re.sub(r"[\s\W_]+", "", _re.sub(r"\\[a-zA-Z]+", " ", t or ""))

    def ok(b) -> bool:
        return isinstance(b, (list, tuple)) and len(b) == 4 and b[2] > b[0] and b[3] > b[1]

    def covered(a: str, b: str) -> float:
        if not a:
            return 0.0
        return sum(x.size for x in
                   difflib.SequenceMatcher(None, a, b).get_matching_blocks()) / len(a)

    nm = [norm(e.get("content")) for e in mnr_els]
    # 쪽마다 글자 한 자가 차지하는 넓이(norm1000²). 짝이 잡힌 요소들로 잰다 — dpi·판형 무관.
    per = sorted((boxes[i][2] - boxes[i][0]) * (boxes[i][3] - boxes[i][1]) / len(nm[i])
                 for i in set(at.values()) if ok(boxes[i]) and nm[i])
    per_char = per[len(per) // 2] if per else 0.0

    def eligible(j: int) -> bool:
        c = llm_els[j].get("content") or ""
        return len(norm(c)) >= 4 and not c.lstrip().startswith(_GRAFT_CAPTION_HEADS)

    runs, cur = [], []            # 짝 못 찾은 LLM 줄의 연속 덩어리
    for j in range(len(llm_els)):
        if j not in at and eligible(j):
            cur.append(j)
            continue
        if cur:
            runs.append(cur)
        cur = []
    if cur:
        runs.append(cur)

    plan: list[tuple[int, list[int], str]] = []
    taken: list[list[int]] = []
    for run in runs:
        lo = max((j for j in at if j < run[0]), default=None)
        hi = min((j for j in at if j > run[-1]), default=None)
        if lo is None or hi is None:
            continue              # 쪽 앞뒤 끝 — 자리를 못 잡는다
        a, b = at[lo], at[hi]
        if not (0 <= a < b <= a + _RECOVER_SPAN):
            continue              # 읽기순서가 어긋났거나 사이가 너무 벌어졌다
        if not (ok(boxes[a]) and ok(boxes[b])):
            continue
        got = [g for g in gaps if g not in taken and _gap_fits(g, boxes[a], boxes[b])]
        if not got:
            continue              # 지면 그 자리에 남은 잉크가 없다 — 누락이 아니다
        txt = "\n".join(t for j in run
                         if (t := guard_llm_text(llm_els[j].get("content") or "", "body").strip()))
        nt = norm(txt)
        if not nt:
            continue
        # 구역 여럿이 걸리면 **글자 수에 가장 맞는 하나**만 쓴다. 다 합치면 그림까지 감싸
        # bbox 가 지면 한 뭉텅이가 된다(p3 실측) — 나머지 구역은 다른 덩어리 몫으로 남긴다.
        bb = min(got, key=lambda g: abs(_gap_capacity(g, per_char, len(nt)) - len(nt)))
        if len(nt) > _RECOVER_FIT * _gap_capacity(bb, per_char, len(nt)):
            continue              # 그 구역에 들어갈 분량이 아니다
        # 구역이 글자보다 높으면 위에서부터 쓸 줄 수만큼만 잡는다 — 안 그러면 MinerU 가
        # 크게 빠뜨린 자리에서 bbox 가 그림까지 감싼다(p3 실측).
        if per_char:
            ch = per_char ** 0.5                      # 글자 한 자의 한 변
            n = max(1, -(-round(len(nt) * ch) // max(bb[2] - bb[0], 1)))
            bb = [bb[0], bb[1], bb[2], min(bb[3], bb[1] + max(round(n * ch), 1))]
        if any(nm[k] and len(nm[k]) >= _GRAFT_DUP_LEN
               and max(covered(nm[k], nt), covered(nt, nm[k])) >= _GRAFT_DUP
               for k in range(max(0, a - 2), min(len(mnr_els), b + 3))):
            continue              # 이웃이 이미 가진 말 — 두 번 나간다
        pos = a + 1               # 사이에 낀 요소보다 위면 그 앞에 세운다
        while pos < b and ok(boxes[pos]) and boxes[pos][3] <= bb[1]:
            pos += 1
        plan.append((pos, bb, txt))
        taken.append(bb)

    return _insert_recovered(mnr_els, plan)


def _insert_recovered(mnr_els: list[dict], plan: list[tuple[int, list[int], str]]) -> int:
    """`(자리, bbox, 글자)` 를 새 요소로 세우고 읽기순서를 다시 매긴다. 회수(`_recover_missing`)와
    크롭 되묻기(`crop_reask`)가 같이 쓴다."""
    import uuid
    for pos, bb, txt in sorted(plan, key=lambda p: -p[0]):
        src = mnr_els[max(pos - 1, 0)] if mnr_els else {}
        mnr_els.insert(pos, {
            "element_id": str(uuid.uuid4()),
            "type": "text",
            "bbox": bb,
            "content": txt,
            "page_width": src.get("page_width"),
            "page_height": src.get("page_height"),
            "image_path": None,
            "heading_level": None,
            "caption_ref": None,
            "flags": ["ADVANCED_RECOVERED"],
        })
    if plan:
        for k, e in enumerate(mnr_els):          # 읽기순서를 새로 매긴다
            e["reading_order"] = k
            if "order" in e:
                e["order"] = k
    return len(plan)


def _graft_text(mnr_els: list[dict], llm_els: list[dict], img_path=None) -> int:
    r"""**MinerU 요소를 기준으로 두고** LLM 이 읽은 글자만 갈아 끼운다.

    고급 점역의 몫은 "MinerU 가 한자로 깨뜨리는 글자를 제대로 읽는 것"이지 지면 구조를
    다시 잡는 것이 아니다(2026-09-03 대표 지시). 그래서 **레이아웃·좌표·읽기순서·유형·
    캡션 연결은 MinerU 것을 그대로 쓰고** 글자만 바꾼다. 이렇게 해야 bbox 가 보통 경로와
    똑같이 맞는다. 짝을 못 찾은 MinerU 요소는 **원래 글자를 지킨다.**

    ⚠ 종전에는 반대로 했다 — LLM 요소 목록을 기준으로 두고 좌표만 얹었다. 그러면 LLM 이
      쪼갠 단위와 MinerU 레이아웃이 어긋나 **FE 하이라이트가 글자와 안 맞았다.**

    짝짓기는 네 가지로 짠다. 근거는 `temp/graft/빠짐없이_0909.md` — 6쪽 422요소에서
    **눈으로 센 깨진 요소 125건**을 놓고 잰 실측이다(온전히 고쳐진 것 30→45건).

      1. **LaTeX 제어어를 걷고 견준다.** MinerU 는 같은 수식을 `\overline {{AH _ {1}}}`
         처럼 장황하게 뱉어 `\overline{AH_1}` 과의 유사도가 깎였다. 수식이 빽빽한 5·6쪽이
         이것 하나로 갈렸다.
      2. **앞머리로 짝을 고른다.** MinerU 가 지면 열 줄을 한 요소로 뭉치는 일이 잦다
         (2쪽은 38요소 대 LLM 83요소). 뭉친 쪽 전문과 견주면 길이 차로 점수가 깎여
         짝이 안 잡힌다. 그래서 LLM 요소가 짧으면 **MinerU 글자의 같은 길이 앞머리**와 견준다.
      3. **이어 붙인다.** 한 MinerU 요소에 LLM 요소 여럿이 걸리면 뒤따르는 것을 붙여
         가며 유사도가 오르는 동안 이어 붙인다. 첫 줄만 갈아 끼워 **단락의 90%가
         사라지던** 개악이 여기서 없어진다.
      4. **2패스.** 1패스는 엄격히, 2패스는 남은 것끼리 '담김'(MinerU 글자가 LLM 글자
         안에 거의 다 들어 있고 앞머리도 같음)까지 받는다. `실수 k의 최,` 처럼 **잘린**
         요소가 여기서 붙는다. 순서를 뒤집으면 멀쩡한 짝이 잘린 요소에 먼저 먹힌다.

    관문 셋 — **글자 수가 줄면 안 되고**(`_GRAFT_KEEP`), **이웃 요소 글자를 통째로
    머금으면 안 되고**(같은 말이 두 번 나간다), **그림을 설명한 LLM 줄은 본문에 안 붙인다**
    (`_GRAFT_CAPTION_HEADS`). 실측에서 삭제 9→0 · 중복 7→3 이다.
    """
    import difflib
    import re as _re

    # ★ 관문 G1(재구조화 §2-2) — 갈래 B 가 읽어 온 글자가 요소 `content` 를 덮는 자리다.
    #   `kind="body"` 는 **거부문 판정만** 한다. 여기 오는 것은 본문 글자라 존댓말 문장이
    #   정상으로 있고, AI 말투 줄 걷기를 걸면 교과서 문장을 먹는다(guard_llm_text 도크스트링).
    from app.ai.captioning.captioner import guard_llm_text   # 지연 — openai SDK

    def norm(t: str) -> str:
        """LaTeX 제어어를 걷고 남은 글자만. 같은 수식을 같은 것으로 보게 한다."""
        return _re.sub(r"[\s\W_]+", "", _re.sub(r"\\[a-zA-Z]+", " ", t or ""))

    def norm_map(t: str) -> tuple[str, list[int]]:
        """`norm` 과 같은 글자를 내되 글자마다 **원문 어디서 왔는지**를 같이 준다.

        제어어를 같은 길이의 공백으로 바꾸므로 남는 글자의 자리가 안 밀린다.
        """
        t = _re.sub(r"\\[a-zA-Z]+", lambda m: " " * len(m.group()), t or "")
        keep = [(k, c) for k, c in enumerate(t) if not _re.match(r"[\s\W_]", c)]
        return "".join(c for _, c in keep), [k for k, _ in keep]

    def ratio(a: str, b: str) -> float:
        return difflib.SequenceMatcher(None, a, b).ratio()

    def covered(a: str, b: str) -> float:
        """a 가 b 안에 얼마나 들어 있나(0~1)."""
        if not a:
            return 0.0
        blocks = difflib.SequenceMatcher(None, a, b).get_matching_blocks()
        return sum(x.size for x in blocks) / len(a)

    thr = _graft_sim_min()
    nl = [norm(m.get("content")) for m in llm_els]
    nm = [norm(el.get("content")) for el in mnr_els]
    cap = [(m.get("content") or "").lstrip().startswith(_GRAFT_CAPTION_HEADS) for m in llm_els]
    # ★ 시각 요소 content 는 캡셔너가 쓴 설명이지 MinerU 가 읽은 글자가 아니다 — 갈아 끼울 것이 없다
    #   (재구조화 L5 손질 · #1012). 유형 필터가 없던 때는 첫머리가 `_GRAFT_CAPTION_HEADS` 밖인 LLM
    #   그림 설명(`모식도:` · `만화:` …)이 유사도로 짝이 잡혀 캡션을 통째로 덮었다. 표는 MinerU 글이라 둔다.
    from app.ai.parser.crop_reask import keep_captions
    skip = [keep_captions() and el.get("type") in _VISUAL_TYPES - {"table"} for el in mnr_els]
    out: list[str | None] = [None] * len(mnr_els)
    used: set[int] = set()
    at: dict[int, int] = {}          # LLM 줄 → 붙은 MinerU 요소. 회수 때 자리를 잡는 데 쓴다.

    def swallows_neighbour(i: int, txt: str) -> bool:
        """이웃 요소 글자를 **새로** 머금었나. MinerU 가 원래 두 벌 갖고 있던 건 통과."""
        t = norm(txt)
        for k in range(max(0, i - 4), min(len(mnr_els), i + 5)):
            if k == i:
                continue
            # 쪽번호·문제번호는 두 글자만 겹쳐도 두 번 읽힌다(`정답 및 해설 199` + `199`).
            if len(nm[k]) < (2 if nm[k].isdigit() else _GRAFT_DUP_LEN):
                continue
            if covered(nm[k], t) >= _GRAFT_DUP and covered(nm[k], nm[i]) < _GRAFT_DUP:
                return True
        return False

    def score(a: str, b: str, loose: bool) -> float:
        if len(b) < len(a):                       # 뭉친 요소 — 앞머리끼리 견준다
            return ratio(a[:len(b)], b)
        r = ratio(a, b)
        if loose and len(a) >= _GRAFT_LOOSE_MIN:  # 잘린 요소 — 담김으로 본다
            k = min(_GRAFT_HEAD, len(a))
            if covered(a, b) >= _GRAFT_COVER and ratio(a[:k], b[:k]) >= _GRAFT_PREFIX:
                r = max(r, covered(a, b))
        return r

    def wrap(k: int, el: dict) -> str:
        """LLM `formula` 요소를 **본문 요소에 붙일 때는** `$…$` 로 감싼다.

        고급 점역 프롬프트는 독립 수식 줄을 `type=formula` 로 내면서 `$` 를 뺀다. 그 줄이
        MinerU `text` 요소로 들어가면 감싸는 것이 없어 **LaTeX 소스가 본문 글자 그대로**
        점역된다(2쪽 [19]·[26]·[30] 실측). 수식 요소끼리 붙는 자리는 그대로 둔다.
        """
        t = guard_llm_text(llm_els[k].get("content") or "", "body").strip()
        if (llm_els[k].get("type") == "formula" and el.get("type") != "formula"
                and t and "$" not in t):
            return f"${t}$"
        return t

    for loose in (False, True):
        for i, el in enumerate(mnr_els):
            if out[i] is not None or skip[i]:
                continue
            a = nm[i]
            if len(a) < 4:
                continue
            best, best_r = -1, thr
            for j, b in enumerate(nl):
                if j in used or len(b) < 4 or cap[j]:
                    continue
                r = score(a, b, loose)
                if r > best_r:
                    best, best_r = j, r
            if best < 0:
                continue
            span, acc, cur = [best], nl[best], ratio(a, nl[best])
            j = best + 1
            while j < len(nl) and j not in used and not cap[j]:
                nxt = ratio(a, acc + nl[j])
                if nxt <= cur:
                    break
                cur, acc = nxt, acc + nl[j]
                span.append(j)
                j += 1
            if len(acc) < _GRAFT_KEEP * len(a):   # 바꾸면 글자 수가 준다 — 손대지 않는다
                continue
            kept = [(k, wrap(k, el)) for k in span
                    if (guard_llm_text(llm_els[k].get("content") or "", "body").strip())]
            if not kept:
                continue
            txt = "\n".join(t for _, t in kept)
            while len(kept) > 1 and swallows_neighbour(i, txt):
                kept.pop()                        # 남의 글자를 먹었으면 꼬리를 자른다
                txt = "\n".join(t for _, t in kept)
            if swallows_neighbour(i, txt):        # 같은 말이 두 번 나간다 — 손대지 않는다
                continue
            out[i] = txt
            used.update(k for k, _ in kept)
            at.update({k: i for k, _ in kept})

    def window(a: str, b: str) -> tuple[int, int, float] | None:
        """`b` 안에서 `a` 가 놓인 구간과, 그 구간이 `a` 와 닮은 정도."""
        blk = [x for x in difflib.SequenceMatcher(None, a, b).get_matching_blocks() if x.size >= 3]
        if not blk:
            return None
        s, e = blk[0].b, blk[-1].b + blk[-1].size
        return s, e, ratio(a, b[s:e])

    def share() -> None:
        """LLM 요소 하나가 MinerU 요소 **여럿에 걸치면 쪼개서 각각에 붙인다**.

        MinerU 가 지면의 한 문장을 서너 줄로 갖고 LLM 은 그 문장을 한 요소로 읽는
        자리가 잦다. 위 두 패스는 LLM 요소를 **통째로만** 갈아 끼우므로 그런 자리에서
        한 줄만 글자를 얻고 나머지는 깨진 채 남는다. 통째로 세우면 이웃의 말까지 같이
        나가 중복 관문에 걸려 **아무것도 못 고치는** 일까지 있다.

        실측(`temp/graft/개선_0909b.md`) — 못 고친 33건이 막힌 자리는 문턱미달 20 ·
        중복관문 6 · 길이관문 3 · LLM선점 1 인데, 셋 다 뿌리가 이 한 가지다. 위 패스의
        점수는 LLM 글자가 길수록 깎이므로(`ratio` 는 길이 차를 벌로 준다) 걸친 자리는
        문턱을 못 넘는다. 여기서는 **그 요소가 놓인 구간과만** 견준다.

        조각은 **원문을 빈틈없이 나눈다** — 한 글자도 안 버리므로 이 패스가 글자를
        지우는 일은 없다. 길이·중복 관문은 조각마다 그대로 건다.
        """
        for i in range(len(mnr_els)):
            if out[i] is not None or skip[i] or len(nm[i]) < _GRAFT_LOOSE_MIN:
                continue
            pick = None
            for j, b in enumerate(nl):
                # 통째로 갈아 끼우는 짝은 위 두 패스가 이미 봤다. 여기 몫은 **더 긴** 것뿐.
                if cap[j] or len(b) < len(nm[i]) + _GRAFT_LOOSE_MIN:
                    continue
                w = window(nm[i], b)
                if w and w[2] >= thr and (pick is None or w[2] > pick[1][2]):
                    pick = (j, w)
            if pick is None:
                continue
            j, (ws, we, _) = pick
            lo = hi = i
            while (lo - 1 >= 0 and i - lo < _GRAFT_SHARE_SPAN
                   and (out[lo - 1] is None or at.get(j) == lo - 1) and len(nm[lo - 1]) >= 4
                   and not skip[lo - 1]):
                lo -= 1
            while (hi + 1 < len(mnr_els) and hi - i < _GRAFT_SHARE_SPAN
                   and (out[hi + 1] is None or at.get(j) == hi + 1) and len(nm[hi + 1]) >= 4
                   and not skip[hi + 1]):
                hi += 1
            if not (at.get(j) is None or lo <= at[j] <= hi):
                continue          # 이 LLM 줄은 딴 데 붙어 있다 — 나누면 두 번 나간다
            raw = llm_els[j].get("content") or ""
            b, bidx = norm_map(raw)
            seg, cur, top = {i: (ws, we)}, we, ws
            for k in range(i + 1, hi + 1):
                w = window(nm[k], b[cur:])
                if not w or w[2] < thr:
                    break
                seg[k] = (cur + w[0], cur + w[1])
                cur = seg[k][1]
            for k in range(i - 1, lo - 1, -1):
                w = window(nm[k], b[:top])
                if not w or w[2] < thr:
                    break
                seg[k] = (w[0], w[1])
                top = w[0]
            if len(seg) < 2:
                continue
            ks = sorted(seg)
            cuts = [0]
            for t in range(len(ks) - 1):
                # 자르는 자리는 **띄어쓰기이면서 `$` 짝이 맞는 곳**이어야 한다. 정렬 구간의
                # 한가운데를 그냥 자르면 낱말과 수식이 두 동강 난다(`곡|선`·`$\lim_{`).
                gap = [x for x in range(bidx[seg[ks[t]][1] - 1] + 1, bidx[seg[ks[t + 1]][0]] + 1)
                       if x >= len(raw) or (raw[x].isspace() and raw[:x].count("$") % 2 == 0)]
                if not gap:
                    break
                mid = (bidx[seg[ks[t]][1] - 1] + bidx[seg[ks[t + 1]][0]]) // 2
                cuts.append(min(gap, key=lambda x: abs(x - mid)))
            if len(cuts) != len(ks):
                continue          # 안전하게 자를 자리가 없다 — 손대지 않는다
            cuts.append(len(raw))
            pieces = []
            for t, k in enumerate(ks):
                txt = guard_llm_text(raw[cuts[t]:cuts[t + 1]], "body").strip()
                if len(norm(txt)) < _GRAFT_KEEP * len(nm[k]) or swallows_neighbour(k, txt):
                    break
                pieces.append((k, txt))
            if len(pieces) != len(ks):
                continue
            for k, txt in pieces:
                out[k] = txt
            at[j] = i

    share()

    hit = 0
    for i, txt in enumerate(out):
        if txt is not None:
            mnr_els[i]["content"] = txt
            hit += 1
    if img_path:
        n = _recover_missing(mnr_els, llm_els, at, img_path)
        if n:
            logger.info("빈 구역에 빠진 요소 %d개 회수", n)
    return hit


async def _fallback_text_layer(task: PageTask, doc_meta: DocumentMeta) -> tuple[list[dict], int, int]:
    """MinerU 실패/타임아웃 폴백: 텍스트레이어가 있으면 PyMuPDF로 본문만 추출.

    무거운 페이지의 페이지 전체 BLOCKED 대신 부분 초안을 살린다(오류 코드는 C1~C7 뿐이고 이 폴백은 R1). 표·그림
    구조는 잃으므로 각 요소에 C2_FALLBACK 플래그 → QualityChecker가 R1로 승격
    → 페이지 NEEDS_REVIEW(점역사 확인). 스캔 전용(텍스트레이어 없음)은 빈 결과."""
    if doc_meta.scan_only:
        return [], 0, 0
    try:
        from app.ai.preprocessor.pdf_analyzer import extract_text_blocks
        blocks, w, h = await asyncio.to_thread(extract_text_blocks, task.pdf_data, task.page_no)
        elements = _blocks_with_bbox(blocks, h)
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


def _page_size_px(pdf_data: bytes, page_no: int) -> tuple[int, int]:
    """쪽 크기(2x 렌더 픽셀). LLM 추출은 bbox 를 안 주지만 응답 계약상 크기는 필요하다."""
    try:
        import fitz
        with fitz.open(stream=pdf_data, filetype="pdf") as d:
            r = d[min(max(page_no - 1, 0), d.page_count - 1)].rect
            return int(r.width * 2), int(r.height * 2)
    except Exception as exc:  # noqa: BLE001 — 크기를 못 재면 0으로 둔다(FE가 비율 매핑을 건너뛴다)
        logger.warning("쪽 크기 산출 실패: %s", exc)
        return 0, 0


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


def _page_rotation(pdf_data: bytes, page_no: int) -> int:
    """쪽 회전각(도). 못 읽으면 0 — 읽기순서 보정을 안 걸 뿐 본문은 그대로 나간다."""
    try:
        import fitz
        from app.ai.preprocessor.pdf_analyzer import _coerce_pdf_bytes
        with fitz.open(stream=_coerce_pdf_bytes(pdf_data), filetype="pdf") as d:
            return int(d[max(0, min(page_no - 1, d.page_count - 1))].rotation) % 360
    except Exception as exc:  # noqa: BLE001 — 회전각은 있으면 좋은 것이다
        logger.debug("쪽 회전각 확인 실패(0으로 진행): %s", exc)
        return 0


def _place_recovered_figures(elements: list[dict], add: list[dict]) -> None:
    """회수한 그림을 **추정 y 자리**에 끼워 넣고 order 를 다시 매긴다(#875).

    회수분은 bbox 가 없다 — 비전 모델의 눈대중 좌표를 경계로 내보내지 않기 때문이다
    (`figure_detect.to_elements` 관문 G2). 그래서 뒤의 기하 읽기순서 보정
    (`_reorder_columns` 5번)이 손대지 않고 **원래 슬롯**을 지킨다. 종전에는 끝에
    붙여 두고 그 보정이 추정 좌표로 자리를 잡아 줬는데, 좌표를 뺐으니 그림 설명이
    쪽 맨 뒤로 밀린다. 자리는 여기서 정해 둔다 — 눈대중 값을 쓰는 곳은 여기뿐이고,
    쓰는 것도 절대 위치가 아니라 **앞뒤 순서**다(그 정도는 실측에서 맞았다).
    """
    for el in add:
        est = el.get("bbox_est")
        y = est[1] if est and len(est) >= 4 else None
        pos = len(elements)
        if y is not None:
            for i, e in enumerate(elements):
                bb = e.get("bbox")
                if isinstance(bb, (list, tuple)) and len(bb) >= 4 and bb[1] > y:
                    pos = i
                    break
        elements.insert(pos, el)
    for i, e in enumerate(elements, start=1):
        e["order"] = i


async def _extract_with_hyunju(task: PageTask) -> tuple[DocumentMeta, dict]:
    """현주 추출 단계: analyze_pdf + (ZERO 텍스트 | non-ZERO 모델) → 경계 dict(크기·bbox 포함)."""
    from app.ai.preprocessor.pdf_analyzer import (
        analyze_pdf,
        box_rects_norm,
        char_box_glyphs_norm,
        extract_text_blocks,
        mark_glyphs_norm,
        tag_char_boxes,
        regroup_boxed,
        tag_answer_marks,
        tag_boxed_elements,
        drop_question_frames,
        drop_sidebar_columns,
    )

    # analyze_pdf의 page_no는 1-indexed(0 이하만 내부 보정). 빼기 1을 넘기면
    # 2페이지부터 한 장씩 밀리므로 task.page_no를 그대로 전달한다(현주 계약).
    doc_meta, pdf_text = await asyncio.to_thread(
        analyze_pdf, task.pdf_data, task.page_no, task.job_id
    )
    image_width = image_height = 0
    # bbox 좌표계는 경로마다 다르다("pixel" = 2x 렌더 픽셀 / "norm1000" = 0~1000 정규화).
    # 추출한 자리에서 한 번 정하고 meta에 적어 둔다 — 소비자가 다른 필드로 유추하면 안 된다.
    # 고급 점역(요청 advanced_ai) — MinerU 대신 LLM 이 쪽 이미지를 직접 읽는다.
    # ★ **티어로 건너뛰지 않는다**(2026-09-08 대표 정정). 종전에는 ZERO 티어(텍스트 레이어가
    #   멀쩡한 쪽)를 빼고 돌렸는데, "이 쪽은 이미 깨끗하니 안 해도 된다" 는 **우리 판단이지
    #   고객 판단이 아니다.** 켜면 쉬운 쪽이든 어려운 쪽이든 모든 쪽을 LLM 이 읽는다.
    advanced_used = ""
    advanced_why = ""          # 고급 점역이 안 돈 이유. 아래에서 실패로 알린다.
    mnr: tuple[list[dict], int, int, str] | None = None
    if task.advanced_ai:
        from app.ai.parser import crop_reask as _crop
        from app.ai.parser import opus_fallback as _llm
        adv_mode = _crop.advanced_mode()
        if not _llm.advanced_available():
            advanced_why = "모델 키가 없다(ANTHROPIC_API_KEY)"
        else:
            img = _page_image_path(task)
            if not img:
                advanced_why = "지면 이미지를 못 만들었다"
            else:
                # ★ MinerU 를 **끄지 않고 같이 돌린다**(2026-09-03 대표 지시). 고급 점역은
                #   내용을 잘 읽지만 좌표를 못 준다 — 종전에는 이 경로에서 bbox 가 통째로
                #   (0,0,0,0) 이라 FE 하이라이트가 아예 안 떴다. LLM 은 API·MinerU 는 GPU 라
                #   서로 안 막으므로 나란히 돌리면 벽시계는 둘 중 긴 쪽이다.
                # ★ crop 모드(`ADVANCED_EXTRACT_MODE=crop`, 2026-09-10 대표 지적 "깨진 거만 배치로")는
                #   쪽 전체를 안 읽는다 — MinerU 가 먼저 읽고, 깨진 요소만 잘라 되묻는다(아래).
                #   **기본은 `both` 다**(2026-09-11 대표 결재) — 쪽 전체를 읽고(page) 그래도 깨진
                #   자리를 잘라 한 번 더 되묻는다. 실측 70~73 → 82~84/125(58.4% → 67%), 쪽당
                #   +$0.02·+6~22초. 고치는 부류가 서로 달라 보완 관계다(`crop_reask.advanced_mode`).
                mnr_job = asyncio.create_task(_extract_via_models(task, doc_meta))
                if adv_mode == "crop":
                    els, used = None, ""
                else:
                    els, used = await asyncio.to_thread(_llm.extract_advanced, str(img))
                try:
                    mnr = await mnr_job
                except Exception as exc:  # noqa: BLE001 — 좌표가 없을 뿐 내용은 살린다
                    logger.warning("고급 점역 곁의 MinerU 실패(좌표 없이 진행): %s", exc)
                    mnr = None
                if adv_mode == "crop":
                    if mnr and mnr[0]:
                        n = await asyncio.to_thread(_crop.reask_crops, mnr[0], str(img))
                        if n is None:
                            advanced_why = "크롭 되묻기가 실패했다"
                        else:
                            advanced_used = _llm.ADVANCED_MODEL
                            logger.info("고급 점역(crop) %d요소 갈아 끼움 (page=%d)", n, task.page_no)
                    else:
                        advanced_why = "MinerU 가 지면을 못 읽었다"
                elif els:
                    advanced_used = used
                    logger.info("고급 점역 추출 채택: %s %d요소 (page=%d)",
                                used, len(els), task.page_no)
                else:
                    advanced_why = "두 모델 다 지면을 못 읽었다"
        # ★ 유료 옵션은 **조용히 실패하면 안 된다**(대표 결정 2026-09-08 「고급 점역의 정의」).
        #   여기까지 왔다는 것은 어려운 지면(티어 != ZERO)이라 이 옵션이 **걸리는 자리**인데
        #   못 돌았다는 뜻이다. 종전에는 경고 한 줄 찍고 MinerU 로 되돌아가, 값을 치른 것과
        #   다른 것이 **멀쩡한 척** 나갔다. 새 체계를 만들지 않고 예외로 알린다 — `run()` 이
        #   `status="BLOCKED"` + `CriticalError(C1)` 로 옮긴다.
        #   ⚠ **티어를 안 가린다.** 켜면 늘 도는 옵션이라 안 돈 경우는 전부 결함이다.
        if not advanced_used:
            raise RuntimeError(
                f"고급 점역을 쓸 수 없다: {advanced_why or '알 수 없는 이유'} "
                f"(page={task.page_no}, 티어={doc_meta.routing_tier})")

    if advanced_used:
        method = "LLM_VISION"
        if mnr and mnr[0]:
            # ★ **MinerU 가 기준이다**(2026-09-03 대표 지시). 고급 점역의 몫은 MinerU 가
            #   한자로 깨뜨리는 글자를 제대로 읽는 것이지 지면 구조를 다시 잡는 것이
            #   아니다. 레이아웃·좌표·읽기순서·유형·캡션 연결을 MinerU 것으로 두고
            #   글자만 갈아 끼우면 bbox 가 보통 경로와 **똑같이** 맞는다.
            elements = mnr[0]
            if els:
                n = _graft_text(elements, els, img)
                logger.info("고급 점역 글자 이식 %d/%d 요소 (page=%d)",
                            n, len(elements), task.page_no)
                if adv_mode == "both":
                    # 이식이 못 잡은 자리(원문자·구조·누락)를 크롭으로 한 번 더 — 실측 73 → 82/125.
                    n = await asyncio.to_thread(_crop.reask_crops, elements, str(img))
                    logger.info("고급 점역(both) 크롭 되묻기 %s요소 (page=%d)", n, task.page_no)
            image_width, image_height, bbox_space = mnr[1], mnr[2], mnr[3]
        else:
            # MinerU 가 없으면 LLM 결과를 그대로 쓴다(좌표 없음). 종전 규약을 따른다.
            elements = els
            bbox_space = "pixel"
            image_width, image_height = await asyncio.to_thread(
                _page_size_px, task.pdf_data, task.page_no
            )
    elif doc_meta.routing_tier == "ZERO":
        method, bbox_space = "TEXT_NATIVE", "pixel"
        blocks, image_width, image_height = await asyncio.to_thread(
            extract_text_blocks, task.pdf_data, task.page_no
        )
        elements = _blocks_with_bbox(blocks, image_height) or _blocks_from_text(pdf_text)
    else:
        method = "OCR"
        elements, image_width, image_height, bbox_space = await _extract_via_models(task, doc_meta)

    # 글상자 테두리(NLD-1.2.5 · 원장 C-01b) — 묵자의 벡터 사각형이 감싼 텍스트 요소에
    # 테두리 태그를 붙인다. 두 경로(ZERO·MinerU) 모두 여기를 지나므로 한 자리면 된다.
    if not doc_meta.scan_only:
        rects = await asyncio.to_thread(box_rects_norm, task.pdf_data, task.page_no)
        # 사각형은 0~1000 정규화로 온다. 경계 bbox의 좌표계가 경로마다 다르므로 맞춰 준다
        # (`result_builder` 2026-07-19: MinerU=정규화 / ZERO·폴백=2x 픽셀).
        if bbox_space == "pixel" and image_width and image_height:
            rects = [[r[0] / 1000 * image_width, r[1] / 1000 * image_height,
                      r[2] / 1000 * image_width, r[3] / 1000 * image_height] for r in rects]
        # 추출기 읽기순서가 상자를 가로지르면 먼저 모아 준다 — 안 그러면 아래 태깅이
        # "읽기순서가 끊겼다"로 상자를 통째로 건너뛴다(원장 C-17 후속).
        if n := regroup_boxed(elements, rects):
            logger.info("글상자 %d개 순서 재정렬 (page=%d)", n, task.page_no)
        # page_w — 곁단 판정(원장 C-77)이 상자 폭을 지면 폭과 견준다. 좌표계에 맞춘다.
        _page_w = float(image_width) if (bbox_space == "pixel" and image_width) else 1000.0
        # 문항 틀 · 곁단 바탕은 글상자가 아니다(#1110 · #1149, pdf_analyzer 주석). 순서 재정렬(위)은 종전대로 다 쓴다.
        _page_h = float(image_height) if (bbox_space == "pixel" and image_height) else 1000.0
        boxes = drop_sidebar_columns(drop_question_frames(elements, rects), _page_w, _page_h)
        if n := tag_boxed_elements(elements, boxes, _page_w):
            logger.info("글상자 %d개 태깅 (page=%d)", n, task.page_no)

        # 정오 표시 ○·×(원장 M-04) — 채움 경로라 텍스트레이어에도 MinerU에도 안 잡힌다.
        marks = await asyncio.to_thread(mark_glyphs_norm, task.pdf_data, task.page_no)
        if bbox_space == "pixel" and image_width and image_height:
            marks = [(k, [r[0] / 1000 * image_width, r[1] / 1000 * image_height,
                          r[2] / 1000 * image_width, r[3] / 1000 * image_height])
                     for k, r in marks]
        if n := tag_answer_marks(elements, marks):
            logger.info("정오 표시 %d개 태깅 (page=%d)", n, task.page_no)

        # 네모 문자(규정 제64항 · 원장 C-16-2) — 지문 빈칸 ▯(가)▯ 의 네모는 벡터 드로잉이라
        # 텍스트 추출에 안 잡힌다. 추출물에는 `(가)`만 남아 문두 지시와 구분이 사라진다.
        cboxes = await asyncio.to_thread(char_box_glyphs_norm, task.pdf_data, task.page_no)
        if bbox_space == "pixel" and image_width and image_height:
            cboxes = [(t, [r[0] / 1000 * image_width, r[1] / 1000 * image_height,
                           r[2] / 1000 * image_width, r[3] / 1000 * image_height])
                      for t, r in cboxes]
        if n := tag_char_boxes(elements, cboxes):
            logger.info("네모 문자 %d개 태깅 (page=%d)", n, task.page_no)

        # 놓친 그림 회수 — 앞단이 시각 요소를 **0개** 낸 쪽만 비전 모델로 다시 본다.
        # 평가 실측: 시각 요소가 0인 26쪽에서 우리가 gold의 1%만 쓴다(프롬프트로는 안 움직인다).
        from app.ai.parser import figure_detect
        _VIS = _VISUAL_TYPES - {"table"}     # 표가 있어도 그림은 회수 대상이다
        if figure_detect.enabled() and not any(e.get("type") in _VIS for e in elements):
            figs = await asyncio.to_thread(figure_detect.detect, task.pdf_data, task.page_no)
            if figs:
                # bbox 좌표계는 경계 파일 규약을 따른다(MinerU=0~1000 정규화 / ZERO·폴백=2x 픽셀).
                w, h = ((image_width, image_height) if bbox_space == "pixel"
                        else (1000.0, 1000.0))
                add = figure_detect.to_elements(figs, w, h, len(elements) + 1)
                _place_recovered_figures(elements, add)
                logger.info("그림 회수 %d개 (page=%d)", len(add), task.page_no)

    # QA용 쪽 이미지 보관(기본 off — KEEP_PAGE_IMAGE=1로만 켠다, 대표 결정 2026-08-07).
    # 평소에는 처리 후 원본을 안 남긴다(저작권·디스크). QA 기간에만 켜면 bbox·읽기순서·
    # 표 오분류를 **쪽 위에 겹쳐 눈으로** 볼 수 있다. 렌더는 고급 점역 추출과 같은 자리를 쓴다.
    if os.environ.get("KEEP_PAGE_IMAGE") == "1":
        _page_image_path(task)

    # 줄바꿈으로 쪼개진 텍스트 조각 잇기(#263) — **두 추출 경로가 만나는 자리다.**
    # 한때 mineru_runner 안에 뒀는데 ZERO 티어(TEXT_NATIVE)가 그 경로를 안 타서 절반에
    # 안 걸렸다(100쪽 표본 A/B 총 편집셀 차 0 · 대표가 지적한 시연 p01 이 ZERO 티어였다).
    # 여기서 하면 두 경로가 다 걸린다. bbox 좌표계가 경로마다 다르므로 bbox_space 를 넘긴다.
    if elements:
        import fitz
        from app.ai.preprocessor.line_join import join_wrapped_lines
        from app.ai.preprocessor.pdf_analyzer import _coerce_pdf_bytes
        try:
            with fitz.open(stream=_coerce_pdf_bytes(task.pdf_data), filetype="pdf") as _d:
                _pg = _d[max(0, min(task.page_no - 1, _d.page_count - 1))]
                n0 = len(elements)
                elements = join_wrapped_lines(
                    elements, _pg, bbox_space=bbox_space,
                    image_width=image_width, image_height=image_height)
            if n0 != len(elements):
                logger.info("줄바꿈 조각 %d개 이음 (page=%d · %s)",
                            n0 - len(elements), task.page_no, method)
        except Exception as exc:      # noqa: BLE001 — 잇기는 있으면 좋은 것, 실패는 격리
            logger.warning("줄바꿈 조각 잇기 건너뜀 (page=%d): %s", task.page_no, exc)

    # 추출 손실 목록(T35) — 추출이 못 본 글(unseen)과 MinerU 는 봤는데 여기까지 못 온 글(dropped).
    # 요소가 다 정해진 **마지막 자리**에서 잰다. 앞 단계(builder·줄 잇기·상자 태깅)가 버린 것도 같이 잡힌다.
    # 점역에는 안 쓴다 — 채점기가 미커버를 갈래로 나눌 때 읽는다(`extraction_losses` 모듈 주석).
    losses: list[dict] = []
    loss_checks: list[str] = []
    try:
        import fitz
        from app.ai.parser.extraction_losses import extraction_losses
        from app.ai.preprocessor.pdf_analyzer import _coerce_pdf_bytes
        with fitz.open(stream=_coerce_pdf_bytes(task.pdf_data), filetype="pdf") as _d:
            _pg = _d[max(0, min(task.page_no - 1, _d.page_count - 1))]
            losses, loss_checks = extraction_losses(
                elements, _pg, _page_dir(task) / "mineru_raw" if method != "TEXT_NATIVE" else None)
    except Exception as exc:          # noqa: BLE001 — 표시는 있으면 좋은 것, 실패는 격리
        logger.warning("추출 손실 목록 건너뜀 (page=%d): %s", task.page_no, exc)

    if bbox_space == "norm1000" and _answer_textlayer_on() and task.pdf_data:
        try:                      # 정답 상자 칸의 벗겨진 동그라미 숫자(B-11 중 이 자리만)
            import fitz
            from app.ai.preprocessor.pdf_analyzer import _coerce_pdf_bytes
            with fitz.open(stream=_coerce_pdf_bytes(task.pdf_data), filetype="pdf") as _d:
                _restore_answer_marks(elements, _d[max(0, min(task.page_no - 1, _d.page_count - 1))])
        except Exception as exc:  # noqa: BLE001 — 되살리기는 덤, 실패는 격리
            logger.warning("정답 상자 동그라미 숫자 되살리기 건너뜀 (page=%d): %s", task.page_no, exc)

    if _stable_ids():             # 요소가 다 정해진 뒤 한 자리에서 매긴다(N5 · #1017)
        _rekey_elements(elements, task.job_id, task.page_no)

    extraction = {
        "meta": {
            "job_id": task.job_id,
            "page_no": task.page_no,
            "extraction_method": method,
            "image_width": image_width,
            "image_height": image_height,
            # bbox 좌표계(2026-08-08 Step8). "pixel" = 2x 렌더 픽셀 / "norm1000" = 0~1000.
            # 없는 옛 파일은 소비자가 extraction_method로 유추한다(하위호환).
            "bbox_space": bbox_space,
            # 쪽 회전각(0·90·180·270). 보기엔 평범한 1단 쪽인데 PDF 내부 좌표가 누워 있는
            # 지면이 있다(외국어 영역 실측 57쪽). 읽기순서를 바로 세우려면 이 값이 필요하다.
            "page_rotation": _page_rotation(task.pdf_data, task.page_no),
            # 손실 목록을 무엇과 대조해 만들었나("mineru" · "text_layer"). 빠진 쪽은 안 쟀다는 뜻이다 —
            # 목록이 비었다고 손실이 없다고 읽으면 안 된다.
            "loss_checks": loss_checks,
            # 캡셔닝을 끄고 뜬 경계인가. **경계와 함께 다닌다** — 응답 표시(processing_meta.caption_disabled)는
            # 요청 때 env 가 아니라 이 값을 옮긴다. 경계를 재사용·복사하면 env 와 내용이 갈리기 때문이다
            # (arm.py 108곳: 캡션 든 d8c 경계에 True 가 찍혔다). 이 키가 없는 옛 경계는 '모름'(None)이다.
            "caption_disabled": process_env("SEMOJUM_NO_CAPTION") == "1",
            # 추출 중에 센 관문 발동(G1 등). 재사용 때 되살린다 — 추출이 안 돌면 안 세져서
            # 재요청마다 검토 표시가 빠졌다(#1032). 이 키가 없는 옛 경계는 종전대로 표시 없음.
            "gate_counts": [[g, r, n] for (g, r), n in sorted(gates.gate_counts().items())],
        },
        "elements": elements,
        "extraction_losses": losses,
    }
    return doc_meta, extraction


# ── 태민 분해 (Phase 2) — 경계 파일 → LayoutResult + ExtractedContent ───────

# 읽기순서 재배정 모드. off=원순서(MinerU content_list) | geom=순수 기하 위→아래(H1, 폐기)
#   | sidebar=max-gap 사이드바 머지(H2, 폐기) | col=열 클러스터링(H3, 운영 기본).
# 깨끗한 자로 다시 잰 값(2026-10-04 eval, tau_prod.py · gold 백틱 cell): dev 171쪽 off 0.783 → col 0.919
#   (나빠짐 1 · 좋아짐 35) · val 904쪽 off 0.803 → col 0.885(나빠짐 22 · 좋아짐 126). col 기본은 그대로 둔다.
#   종전 이 자리의 'dev 18p off 0.805 · sidebar 0.832 · col 0.965, 회귀 0건'(07-13)은 gold 백틱을 띄움으로 읽은 자의 값이었다.
# sidebar(H2)는 x0 최대간격 분할이라 분할선이 본문/사이드바를 관통하는 페이지에서 오발동·미발동
# (세계사 p086 관통, p106 임계 3px 미달)이 잦아 col로 대체.
_REORDER_MODE = os.environ.get("READING_ORDER_MODE", "col")
# 기하 정렬을 걸 수 있는 최대 열 수. 교재 쪽은 많아야 3단이다. 이보다 많이 잡히면
# 열 모형이 안 맞는 쪽(회전 페이지·비정형 글상자)이라 원순서를 그대로 둔다.
# 실측(2026-08-07, dev2027 189 · devall 172 · valall 868쪽, 요소단위 τ. 열 우선 정렬 적용 후):
#   상한 없음 0.909/0.805/0.826 → ≤3열 0.909/0.908/0.888. 4~8열로 올려도 값이 같다(평탄).
_MAX_COLS = 3
# 다리 요소 탐색 상한(요소 수). 탐색이 O(n^3) 이라 큰 쪽에서는 접는다 — 실측 코퍼스
# 1,131쪽의 최대 요소 수가 62 라 이 상한에 걸려 접히는 쪽은 없다.
_BRIDGE_MAX_ELEMENTS = 80
# 참고열로 인정할 '한 덩이' 비율. 추출기 순번에서 최장 연속 토막이 그 열 요소의 이 비율
# 이상이면 한 단으로 본다(그리고 3개 이상이어야 한다 — 낱개 라벨 보호).
_SIDE_RUN_SHARE = 0.5


def _valid_bbox(b: BBoxItem) -> bool:
    return b.bbox[2] > b.bbox[0] and b.bbox[3] > b.bbox[1]


def _reorder_by_geometry(items: list[BBoxItem], rotation: int = 0) -> list[BBoxItem]:
    """다단/사이드바 페이지의 읽기순서를 보정. 모드는 _REORDER_MODE. 쪽 끝으로 미룬 곁단 요소를 돌려준다(col 모드만).

    배경: MinerU content_list 순서는 좁은 좌측 사이드바(보충설명)를 본문보다 먼저 방출해
    읽기순서를 흩뜨린다(세계사 p086/p106). bbox 유효 요소가 과반인 MinerU 페이지만 손대고,
    bbox (0,0,0,0)인 ZERO/TEXT_NATIVE는 원순서를 보존한다.
    """
    if _REORDER_MODE == "off":
        return []
    valid = [b for b in items if _valid_bbox(b)]
    if len(valid) < max(3, len(items) * 0.5):
        return []  # 기하정보 부족 → 원순서 유지

    if _REORDER_MODE == "geom":
        # H1(폐기): 전체를 위→아래·행내 좌→우로 정렬. MinerU가 옳던 페이지를 망가뜨림.
        heights = sorted(b.bbox[3] - b.bbox[1] for b in valid)
        band = max(1.0, heights[len(heights) // 2] * 0.5)
        big = 10 ** 9
        key = lambda b: ((round(b.bbox[1] / band), b.bbox[0]) if _valid_bbox(b)
                         else (big, b.reading_order))
        for i, b in enumerate(sorted(items, key=key), start=1):
            b.reading_order = i
        return []

    if _REORDER_MODE == "sidebar":
        _reorder_sidebar(items, valid)
        return []

    if _REORDER_MODE == "col":
        return _reorder_columns(items, rotation)
    return []


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


_BANDED = os.environ.get("READING_ORDER_BANDED", "1") != "0"   # #1079 가로 띠 신호(끄면 종전) · 같은 커밋 A/B 스위치


def _reorder_columns(items: list[BBoxItem], rotation: int = 0) -> list[BBoxItem]:
    """H3: 열 클러스터링 읽기순서. 쪽 끝으로 미룬 곁단 요소(아래 (1))를 새 차례대로 돌려준다(없으면 빈 목록).

    규정 근거 —「점자 도서 제작 지침」2장 5. 다단 점역:
      · 동등한 관계의 다단 → "일반적으로 왼쪽 단을 적은 후 오른쪽 단으로, 상단을 적은
        후 하단을 적는다"  → (5) 열 우선 정렬.
      · 주종 관계의 다단 → "본문에 해당하는 단을 우선 적고, 참고 자료는 본문 아래"
        → (1) 좁은 참고열 후치.

    정답 BRL 관찰(2026-07-13)에 근거한 세 규칙:

    (1) 점역사는 좁은 용어설명 열을 본문 뒤에 둔다 — MinerU가 이 열을 본문 앞에
        통째로(연속 순번) 방출하는 것이 주 실패 양상(세계사 p086·p106).
        반대로 순번이 본문 사이에 흩어진 좁은 요소(문항별 포인트 라벨 등)는
        MinerU의 의도 배치 → 보존(세계사 p160).
        '연속'은 3개 이상 블록일 때 이탈 하나까지 봐준다 — 쪽 아래 출전 한 줄이 같은
        열로 묶여 후치가 통째로 막히는 쪽이 있었다(생물 p180 τ −0.111 → 1.000).
        낱개 '그림'은 아예 후치 대상이 아니다 — 아래 lone_visual 주석.
    (1') 본문 열은 요소가 많은 열이 아니라 **면적이 큰 열**이다. 잘게 쪼개진 보충설명
        열이 개수로 본문을 이기는 쪽이 있었다(생물 p180: 사이드 9개 vs 본문 7개).
    (2) 대등한 2단 본문은 MinerU가 열 단위로 옳게 방출 — y-정렬하면 두 열이 섞여
        파괴되므로, MinerU 순서가 y-흐름을 심하게 거스를 때만 열 내부를 y-정렬
        (사회문화 p035: MinerU 순서 자체가 뒤죽박죽인 페이지).
    (3) 페이지행 요소(header_footer/page_number)·빈 bbox는 원래 순번 슬롯 유지.
    (4) 열이 _MAX_COLS개를 넘으면 '열'이라는 모형이 이 쪽에 안 맞는다 → 원순서 유지.
    (5) y-정렬은 열 안에서만 한다 — 열을 가로질러 정렬하면 2단 본문이 한 줄씩 섞인다.
    """
    body = [b for b in items if _valid_bbox(b) and b.type not in ("header_footer", "page_number")]
    if len(body) < 3:
        return []

    # 1) x-구간 겹침(좁은 쪽 폭 50% 이상) union-find → 열 클러스터
    def _components(skip: set[int]) -> list[list[int]]:
        """`skip` 을 뺀 요소들의 x-겹침 연결성분(요소 위치 목록)."""
        par = {i: i for i in range(len(body)) if i not in skip}

        def find(i: int) -> int:
            while par[i] != i:
                par[i] = par[par[i]]
                i = par[i]
            return i

        ks = list(par)
        for n, i in enumerate(ks):
            for j in ks[n + 1:]:
                a, c = body[i], body[j]
                ov = min(a.bbox[2], c.bbox[2]) - max(a.bbox[0], c.bbox[0])
                w = min(a.bbox[2] - a.bbox[0], c.bbox[2] - c.bbox[0])
                if w > 0 and ov >= 0.5 * w:
                    par[find(i)] = find(j)
        out: dict[int, list[int]] = {}
        for i in ks:
            out.setdefault(find(i), []).append(i)
        return list(out.values())

    # 1-a) ★ 두 단을 가로지르는 요소 하나가 쪽 전체를 한 덩이로 붙여 버린다(2026-09-10).
    #   x-겹침 union 은 전이적이라, 좌측 참고열과 본문에 걸치는 요소가 **하나만** 있어도
    #   두 단이 한 클러스터로 합쳐지고 참고열 후치(아래 3번)가 통째로 막힌다.
    #   실물: 세계사 p104 의 강 제목 `르네상스와 종교 개혁`(x 151~609)이 좌측 용어열
    #   (x 106~283)과 본문(x 318~1071)을 이었다 — 28요소가 클러스터 1개.
    #   그래서 **빼면 3요소 이상 성분이 둘로 갈리는 요소**를 다리로 보고 클러스터링에서만
    #   제외한다. 그 요소는 아래 3번 참고열 판정이 끝난 뒤 본문에 붙인다(사라지지 않는다).
    #   비용은 O(n^3) 이라 요소가 적은 쪽에서만, 그리고 **한 덩이로 뭉친 쪽에서만** 찾는다.
    bridge: set[int] = set()
    if len(body) <= _BRIDGE_MAX_ELEMENTS and len(_components(set())) == 1:
        for k in range(len(body)):
            if sum(1 for c in _components({k}) if len(c) >= 3) >= 2:
                bridge = {k}
                break

    clusters: dict[int, list[BBoxItem]] = {}
    for comp in _components(bridge):
        clusters[comp[0]] = [body[i] for i in comp]
    for k in bridge:                              # 다리는 홀로 둔다(3번 뒤 main 에 붙는다)
        clusters[-1 - k] = [body[k]]

    # 1-b) ★ 열이 너무 많으면 손대지 않는다. 교재 쪽은 많아야 3단인데 x-겹침 열이 10~30개로
    #   나오는 쪽이 실제로 있다 — 270° 회전 페이지(외국어 영역)와 비정형 글상자 배치다.
    #   그런 쪽에서 기하 정렬을 걸면 읽기순서가 통째로 뒤집힌다(실측 τ 1.00 → −1.00,
    #   valall 47쪽 평균 0.677 → −0.442). 모형이 안 맞는 쪽은 추출기 순서를 믿는다.
    if len(clusters) - len(bridge) > _MAX_COLS:
        # ★ 그런데 그런 쪽의 대부분은 **회전된 지면**이다(실측 58쪽 중 57쪽이 rotation 270°).
        #   보기엔 평범한 1단 쪽인데 PDF 내부 좌표가 누워 있어 x0가 흩어져 열이 10~30개로
        #   잡힌다. 회전각을 알면 규칙으로 바로 세울 수 있다 — 270°에서 표시상의 '위에서
        #   아래'는 내부 좌표의 **x 내림차순**이다.
        #   실측(valall 4열+ 47쪽): 원순서 τ 0.677 → 이 규칙 0.996. 같은 쪽에 LLM을 물어본
        #   값이 0.989였다(쪽당 $0.0166) — 규칙이 더 정확하고 공짜다.
        if rotation in (90, 270):
            desc = rotation == 270
            for i, b in enumerate(sorted(body, key=lambda b: (-b.bbox[0] if desc else b.bbox[0],
                                                              b.bbox[1])), start=1):
                b.reading_order = i
        return []
    # 열 번호(왼쪽부터 0,1,2). ★ 여기서 확정해 둔다 — 아래에서 main 리스트를 extend하면
    #   클러스터 리스트가 같은 객체라 그대로 오염된다(열 번호가 뒤바뀐다).
    col_of = {id(b): ci for ci, cl in
              enumerate(sorted(clusters.values(), key=lambda c: min(b.bbox[0] for b in c)))
              for b in cl}

    # 2) main = 총면적이 가장 큰 클러스터(동률이면 요소 수). main 헐과 자기 폭 50% 이상
    #    겹치는 클러스터(선지 ①②③ 조각 등)는 흡수.
    #    ★ 예전에는 요소 수를 먼저 봤는데, 잘게 쪼개진 좁은 보충설명 열이 개수로 본문을
    #      이겨 본문이 통째로 뒤로 밀렸다(생물 p180: 사이드 9개 vs 본문 7개, τ −0.111).
    main_key = max(clusters, key=lambda k: (sum((b.bbox[2] - b.bbox[0]) * (b.bbox[3] - b.bbox[1])
                                                for b in clusters[k]), len(clusters[k])))
    main = clusters.pop(main_key)
    hull0, hull1 = min(b.bbox[0] for b in main), max(b.bbox[2] for b in main)
    sides: list[list[BBoxItem]] = []
    # ★ 다리(1-a)는 흡수·후치 판정에 넣지 않고 3번 뒤 main 에 붙인다(2026-09-29, #656).
    #   예전엔 여기서 헐 겹침으로 흡수를 따졌는데, 다리는 두 단에 걸쳐 헐과 절반도 안 겹치기
    #   일쑤라 낱개 '좁은 열'로 판정돼 쪽 맨 끝으로 갔다(2027 윤리와 사상 p040: 쪽 머리 제목이
    #   41 중 40번째). 그렇다고 3번 **전에** main 에 넣으면 다리 폭이 main 최대 요소 폭을
    #   부풀려 본문 단이 좁은 열로 잡힌다(사회문화 val p113 τ 0.960 → 0.036).
    bridges: list[BBoxItem] = []
    for key, cl in clusters.items():
        if key < 0:
            bridges.extend(cl)
            continue
        c0, c1 = min(b.bbox[0] for b in cl), max(b.bbox[2] for b in cl)
        if min(hull1, c1) - max(hull0, c0) >= 0.5 * (c1 - c0):
            main.extend(cl)
        else:
            sides.append(cl)

    # 3) 연속 순번 + 좁은 폭(본문 헐의 절반 이하) 사이드 열만 본문 뒤로 이동
    body_rank = {id(b): r for r, b in
                 enumerate(sorted(body, key=lambda b: b.reading_order), start=1)}
    # ★ '좁다'의 잣대는 main **헐**이 아니라 main 에서 **가장 넓은 요소**다(2026-09-29, #656, 원장 C-122-b).
    #   헐은 옆 해설 열이 다리 조각으로 붙으면 부푼다 — 언어 p019 는 가운데 본문 단 조각
    #   (x 669~745)이 아래 해설 상자와 겹쳐 헐이 454~745 → 454~1069 가 됐고, 폭이 같은 왼쪽
    #   본문 단(291)이 '헐의 절반 이하'로 잡혀 쪽 끝으로 밀렸다(τ 1.000 → −0.059).
    #   실측 1,076쪽: 바뀐 쪽 5 = 이득 4(언어 011·019·159·223) · 손해 1(언어 222: 왼쪽 해설 열이
    #   본문 한 단과 폭이 비슷해 앞으로 온다 — 폭으로는 019 와 못 가른다, 내용 판정은 자문 대기).
    _main_w = max(b.bbox[2] - b.bbox[0] for b in main)
    deferred: list[list[BBoxItem]] = []
    for cl in sides:
        ranks = sorted(body_rank[id(b)] for b in cl)
        runs, run = [], 1
        for _a, _c in zip(ranks, ranks[1:]):
            if _c == _a + 1:
                run += 1
            else:
                runs.append(run); run = 1
        runs.append(run)
        best = max(runs)
        # ★ 참고열이 **두 토막**으로 나오는 쪽이 있다(2026-09-07, 이슈 #643).
        #   같은 좌측 열에 보충설명(순번 1~9)과 정답(17~19)이 따로 실리면 "한 덩이" 조건이
        #   깨져 후치가 통째로 막혔다(생명과학 p114: 최장 9 < 12-1 → 순서 무변경).
        #   규정이 뒤로 미루라는 것은 '참고 자료 단'이고(「점자 도서 제작 지침」 2장 5,
        #   주종 관계의 다단), 그 단이 두 토막이어도 단이다 — 한 덩이일 것을 요구할 근거가 없다.
        #   낱개가 본문 사이에 흩어진 열(문항별 포인트 라벨 등, 세계사 p160)은 3 미만
        #   덩이만 나오므로 종전대로 보존된다.
        #   ★ 2026-09-10 — 토막이 **셋 이상**인 쪽도 같은 얼굴이다. 두 토막만 봐주던
        #   조건이 `runs=[7,1,1]` 같은 쪽에서 다시 막혔다(생물 p018: 좌측 빈칸문제 7개 +
        #   정답 상자 1개 + 낱개 1개 → 후치 실패, 본문이 통째로 뒤로 밀렸다).
        #   조항이 요구하는 것은 '참고 자료 단'이지 추출기 순번의 연속성이 아니므로,
        #   최장 토막이 그 열의 절반 이상이면 한 단으로 본다(_SIDE_RUN_SHARE).
        contiguous = (best == len(ranks)
                      or (best >= 3 and best >= _SIDE_RUN_SHARE * len(ranks)))
        narrow = (max(b.bbox[2] for b in cl) - min(b.bbox[0] for b in cl)) \
            <= 0.5 * _main_w
        # ★ 요소 하나짜리 클러스터는 '연속 순번'이 공짜로 참이라 이 조건을 못 거른다.
        #   그래서 본문 옆에 홀로 놓인 그림·아이콘·표가 통째로 쪽 끝으로 밀려났다
        #   (실측 devall+valall 13쪽 — 생물 p026 '유형' 아이콘이 y=355인데 마지막에서 두 번째).
        #   규정이 뒤로 미루라는 것은 '참고 자료 단'이지 낱개 그림이 아니다
        #   (「점자 도서 제작 지침」 2장 5, 주종 관계의 다단). 그림 하나는 단이 아니다.
        #   텍스트 낱개(좌측 여백의 유형 라벨 등)는 종전대로 후치한다 — 정답 배치가 그렇다
        #   (사회문화 p034: 후치를 막으면 τ 0.927 → 0.709).
        lone_visual = len(cl) == 1 and cl[0].type in _VISUAL_TYPES
        if contiguous and narrow and not lone_visual:
            deferred.append(cl)
        else:
            main.extend(cl)
    main.extend(bridges)
    hull0, hull1 = min(b.bbox[0] for b in main), max(b.bbox[2] for b in main)

    # 4) main: MinerU 순서가 y-흐름을 2회 넘게 거스를 때만 y-밴드 정렬.
    #    위반 = y가 2밴드 이상 되돌아가는데 오른쪽 열 점프(2단 전환)도 아닌 연속 쌍.
    #    ★ 정렬 키의 첫 자리는 열이다(왼쪽 열 전부 → 오른쪽 열 전부). 열을 무시하고
    #      y부터 정렬하면 2단 본문이 왼쪽 한 줄·오른쪽 한 줄로 번갈아 섞여 나온다
    #      (dev-2027 TEXT_NATIVE 82쪽 τ 0.830 → 0.817, 열 우선으로 고치면 0.963).
    heights = sorted(b.bbox[3] - b.bbox[1] for b in main)
    band = max(1.0, heights[len(heights) // 2] * 0.5)

    def _ykey(b: BBoxItem) -> tuple:
        return (col_of[id(b)], round(b.bbox[1] / band), b.bbox[0])

    by_mineru = sorted(main, key=lambda b: b.reading_order)
    viol = sum(
        1 for a, c in zip(by_mineru, by_mineru[1:])
        if c.bbox[1] < a.bbox[1] - 2 * band and c.bbox[0] < a.bbox[0] + 0.3 * (hull1 - hull0)
    )
    # ★ 완전 분리 역전은 한 번만 나와도 명백한 오류다(2026-08-19).
    #   위 `viol`은 **위끝(y1)끼리만** 재기 때문에, 뒤 요소가 앞 요소보다 통째로 위에 있어도
    #   앞 요소가 키가 크면 위끝 차이가 밴드에 못 미쳐 안 잡힌다. 실제 사고가 그 얼굴이었다
    #   (테스트_1.pdf: 만화 y 115~273이 1번, 제목 y 87~105가 2번. 위끝 차 28 < 2밴드 37).
    #   여기서는 **세로로 전혀 안 겹치고 가로로는 겹치는**(= 같은 단) 쌍만 센다. 2단 본문의
    #   열 점프는 가로가 안 겹치므로 걸리지 않는다 — 그래서 임계를 1로 둬도 안전하다.
    hard = sum(
        1 for a, c in zip(by_mineru, by_mineru[1:])
        if c.bbox[3] <= a.bbox[1]
        and min(a.bbox[2], c.bbox[2]) - max(a.bbox[0], c.bbox[0]) > 0
    )
    # ★ 가로 띠 읽기(#1079). 깨끗한 2단 띠 읽기(좌상 → 우상 → 좌하 → 우하)는 단을 **건너뛰며** 되돌아가므로
    #   위 `viol`(오른쪽 점프 아닌 되돌림)에도 `hard`(같은 단 역전)에도 안 걸려 정렬이 아예 안 켜졌다
    #   (2027 사회·문화 body p0079: 문항 01 → 03 → 02 → 04, 조사 temp/n83/조사_합쳐짐순서.md B-1).
    #   추출기 순번을 열 번호 런으로 쪼개, 같은 열을 다시 찾는데 뒤 런이 앞 런보다 통째로 아래이고 **그 사이에
    #   다른 열의 런(3요소 이상)이 앞 런과 같은 높이에서 시작하면** 띠로 읽힌 것이다(좌상 → 우상 → 좌하).
    #   ★ 사이 런 조건이 없으면 1단 본문이 여백 라벨 하나(`④` · `정답과 풀이 41쪽`)나 문항별 좁은 힌트 상자에
    #     끊긴 쪽까지 켜진다(2027 dev·val 1,745쪽 중 181쪽이 바뀌고 수학 I p0071 τ 1.0 → 0.5 · 생명과학 p0038
    #     0.371 → 0.143: 힌트 둘이 쪽 맨 앞으로 몰렸다).
    #   가드를 통째로 빼는 안은 기각(384쪽 중 157쪽이 바뀌고 문항번호 역전 73 → 148).
    runs: list[list] = []                      # [열, 위끝, 아래끝, 요소 수]
    for b in by_mineru:
        c = col_of[id(b)]
        if runs and runs[-1][0] == c:
            r = runs[-1]
            r[1], r[2], r[3] = min(r[1], b.bbox[1]), max(r[2], b.bbox[3]), r[3] + 1
        else:
            runs.append([c, b.bbox[1], b.bbox[3], 1])
    banded = _BANDED and any(
        a[0] == c[0] and a[3] >= 3 and c[3] >= 3 and c[1] >= a[2]
        and any(m[0] != a[0] and m[3] >= 3 and m[1] < a[2] for m in runs[i + 1:j])
        for i, a in enumerate(runs) for j, c in enumerate(runs[i + 1:], start=i + 1))
    # ★ 오른쪽 단을 통째로 먼저 읽은 쪽(#1123). MinerU 열 번호가 한 번만 내려가고(오른쪽 → 왼쪽) 한 번도 안 오른다.
    #   거스름이 단을 넘는 그 한 번뿐이라 `viol`(문턱 2)에도 `hard` 에도 안 걸렸다(2027 생활과 윤리 해설 25쪽,
    #   τ 평균 0.00 → 0.998). 열 런이 둘뿐인 쪽이라 위 띠 읽기(같은 열을 다시 찾음)와 겹치지 않는다.
    #   '거스름 한 번이면 정렬'(viol >= 1)로 넓히는 안은 기각(2027 τ val 좋 34 : 나 9 · dev 좋 9 : 나 10).
    cols = [col_of[id(b)] for b in by_mineru]
    swapped = (len(set(cols)) == 2 and sum(c < a for a, c in zip(cols, cols[1:])) == 1
               and not any(c > a for a, c in zip(cols, cols[1:])))
    if swapped:      # 두 열이 정말 나란한가 — 단을 가로지르는 넓은 제목이 '오른쪽 열'로 잡히는 쪽을 거른다(사회·문화 p0151)
        lo, hi = min(cols), max(cols)
        swapped = (min(b.bbox[0] for b in main if col_of[id(b)] == hi)
                   >= max(b.bbox[2] for b in main if col_of[id(b)] == lo) - 0.02 * (hull1 - hull0))
    main = sorted(main, key=_ykey) if (viol > 1 or hard or banded or swapped) else by_mineru

    # 5) 새 본문 순서 = main → 이동 열(x0 순, 각 y-정렬). 비본문은 원 슬롯 유지.
    deferred.sort(key=lambda cl: min(b.bbox[0] for b in cl))
    tail = [b for cl in deferred for b in sorted(cl, key=lambda x: x.bbox[1])]
    new_body = main + tail
    body_ids = {id(b) for b in body}
    it = iter(new_body)
    seq = [next(it) if id(b) in body_ids else b
           for b in sorted(items, key=lambda b: b.reading_order)]
    for k, b in enumerate(seq, start=1):
        b.reading_order = k
    return tail


# ── 선택지·보기 하위항목 분절(P2a, opt 직전) ─────────────────────────────────
# 4분류: ① 규칙 미비 — MinerU는 선택지(①~⑤)·보기(ㄱㄴㄷㄹ)를 줄바꿈만 있는 한 list_item
#   요소로 묶어 내지만, 정답 도서는 항목마다 별도 줄(2칸 들여)로 조판한다(NLD-2.3.5).
#   결합 요소를 그대로 두면 항목 하나의 사소한 차이가 전체 블록을 통째로 miss 처리한다
#   (채점기는 요소 단위 연속부분열 일치를 본다 — 5항목 중 1개만 달라도 5개 전부 실패).
#   줄머리 마커가 뚜렷이 2개 이상 있을 때만 쪼갠다: 선택지 원문자(①~⑳)·보기 자음(ㄱ.~ㅎ.)
#   두 계열만 앵커로 인정해 산문 list_item(마커 없음, 예: 도입문 단독 요소)은 불가침.
#   "(가)"·"1." 같은 범용 열거 패턴은 산문 열거와 구분이 안 돼 앵커에서 제외했다(과분할 위험).
#   문장 속 참조("밑줄 친 ㉠~㉢에")는 마커가 줄 첫머리가 아니거나 다른 문자군(㉠~㉿)이라
#   애초에 매치되지 않는다(줄머리만 검사).
#   실측(라운드3, dev 18p 재현): list_item 무수정 사용률 38.4%→68.5~74.3%.
_LIST_SPLIT_MARKER_RE = re.compile(
    r"^(?:[①-⑳]"      # ①-⑳ (선택지 원문자)
    r"|[ㄱ-ㅎ]\.\s)"    # ㄱ.~ㅎ. (보기 자음, 뒤에 공백 필수 — 오탐 방지)
)


# 요소 id 이름공간(N5 · #1017). 바꾸면 모든 요소 id 가 한 번 바뀐다 — 고정값이다.
# ── 정답 상자 동그라미 숫자 (T33 §2-3 후속 · 원장 B-11 중 정답 상자 자리만) ──────────
# MinerU 표 인식이 원문자를 벗겨 `01 ④` 가 `01 4` 로 온다. 텍스트층에는 원문 그대로 있다
# (dev 실물 셋: 생명과학 ans p0026 · 수학 ans p0003 · 국어 ans p0012, PUA 0). 정답 상자로
# 판정된 표만, **세 목록이 어긋남 없이 같을 때만** 칸을 고친다: 표 칸의 쌍 순서 · 텍스트층의 쌍
# 순서 · 번호와 값(원문자는 그 숫자로 환산). 여러 묶음 상자는 번호가 되풀이되므로 번호가 아니라
# 순서로 짝짓는다. 조금이라도 다르면 손대지 않는다. 되돌리는 길 `ANSWER_BOX_TEXTLAYER=0`.
_ANS_CELL_HTML_RE = re.compile(r"(<t[dh][^>]*>)\s*(\d{1,2})\s+([①-⑳]|\d{1,4})\s*(</t[dh]>)")
_ANS_TEXT_RE = re.compile(r"(?<!\d)(\d{1,2})[ \t]+([①-⑳]|\d{1,4})(?![\d~])")


def _answer_textlayer_on() -> bool:
    return os.environ.get("ANSWER_BOX_TEXTLAYER", "1") != "0"


def _table_keep_cells() -> bool:
    return os.environ.get("TABLE_KEEP_CELLS", "1") != "0"


def _is_answer_box_html(html: str) -> bool:
    """표 HTML 이 정답 상자인가(`ANSWER_BOX_FORM` 이 켜졌을 때만)."""
    from app.ai.braille.table_braille import answer_box_on, answer_box_parts
    if not answer_box_on() or "<t" not in (html or ""):
        return False
    from app.ai.llm.table_opt import _html_to_grid
    return answer_box_parts(_html_to_grid(html, expand=False)) is not None


def _answer_val(a: str) -> str:
    return str(ord(a) - 0x245F) if "①" <= a <= "⑳" else a


def _restore_answer_marks(elements: list[dict], page) -> int:
    """정답 상자 표의 `번호 답` 칸을 텍스트층 글자로 되살린다. 고친 칸 수를 돌려준다."""
    from app.ai.braille.table_braille import answer_box_parts
    from app.ai.llm.table_opt import _html_to_grid
    if page.rotation:
        return 0
    fixed = 0
    W, H = page.rect.width, page.rect.height
    for el in elements:
        html, bb = el.get("content") or "", el.get("bbox")
        bb = json.loads(bb) if isinstance(bb, str) else bb
        if el.get("type") != "table" or not bb or "<t" not in html:
            continue
        cells = list(_ANS_CELL_HTML_RE.finditer(html))
        if not cells or answer_box_parts(_html_to_grid(html, expand=False)) is None:
            continue
        clip = (bb[0] / 1000 * W - 3, bb[1] / 1000 * H - 3, bb[2] / 1000 * W + 3, bb[3] / 1000 * H + 3)
        layer = [(m.group(1), m.group(2)) for m in _ANS_TEXT_RE.finditer(page.get_text("text", clip=clip))]
        ours = [(m.group(2), m.group(3)) for m in cells]
        if len(layer) != len(ours) or any(int(a[0]) != int(b[0]) or _answer_val(a[1]) != _answer_val(b[1])
                                          for a, b in zip(layer, ours)):
            continue
        answers = iter(ans for _, ans in layer)
        el["content"] = _ANS_CELL_HTML_RE.sub(
            lambda m: f"{m.group(1)}{m.group(2)} {next(answers)}{m.group(4)}", html)
        fixed += sum(1 for a, b in zip(layer, ours) if a[1] != b[1])
    return fixed


_EID_NS = UUID("5e0c6f1e-7a2b-4c1d-9f3e-2b8a6d4c1f70")


def _stable_ids() -> bool:
    """요소 id 를 입력에서 정한다(기본). `STABLE_ELEMENT_ID=0` 이 종전(uuid4)이다. 호출 때 읽는다."""
    return os.environ.get("STABLE_ELEMENT_ID", "1") != "0"


def _rekey_elements(elements: list[dict], job_id: str, page_no: int) -> None:
    """경계 요소 id 를 다시 매긴다 — 같은 job · 쪽 · 자리의 요소는 늘 같은 id 다(N5 · #1017).

    종전 uuid4 는 재파생마다 전부 갈려 점역사 피드백의 요소 참조가 끊겼다(설계 §2-3). 열쇠는
    **자리**(유형 + 상자)다. 글은 안 넣는다 — 캡션 · 교정이 바뀌어도 같은 요소는 같은 id 여야 한다.
    상자가 없는 요소(회수 그림 · 쪽 읽기 요소)만 글 앞머리로 잡는다. 겹치면 순번을 붙인다.
    요소끼리의 참조(`caption_ref`)도 같이 옮긴다. MinerU 이미지 조각은 `image_path` 로 찾으므로
    id 를 바꿔도 안 끊긴다.
    """
    seen: dict[str, int] = {}
    remap: dict[str, str] = {}
    for el in elements:
        bb = el.get("bbox")
        where = (",".join(str(round(float(v))) for v in bb) if bb
                 else re.sub(r"\s+", "", el.get("content") or "")[:40])
        key = f"{el.get('type', '')}|{where}"
        seen[key] = seen.get(key, 0) + 1
        new = str(uuid5(_EID_NS, f"{job_id}|{page_no}|{key}|{seen[key]}"))
        if el.get("id"):
            remap[str(el["id"])] = new
        el["id"] = new
    for el in elements:
        if el.get("caption_ref") and str(el["caption_ref"]) in remap:
            el["caption_ref"] = remap[str(el["caption_ref"])]


# 문항 번호만 든 요소(`01` · `<!강조>02<!/강조>`) — 원장 C-107 (ㄴ).
_ITEM_NUMBER_ONLY_RE = re.compile(r"^\s*(?:<!강조>)?\s*(?:0\d|[1-9]\d?)\s*(?:<!/강조>)?\s*$")


def _join_item_numbers(items: list[BBoxItem], ext_map: dict, unit: float = 1.0) -> int:
    """따로 뽑힌 문항 번호를 같은 줄 오른쪽 발문 앞에 붙이고 번호 요소를 뺀다. 붙인 수를 돌려준다.

    번호를 색 네모에 찍는 책(004 등)은 MinerU 가 `01` 을 title·page_number·text 형 별도 요소로
    낸다. 조판은 그걸 홀로 한 줄에 찍는데, gold 는 문항코드 꼴(C-107 X·Y)과 상관없이 모두
    `01 발문` 한 줄이다. 실측(d8c dev·val, 제품 최종 차례): dev 136쪽 209곳 · val 129쪽 244곳,
    gold 에서 번호와 발문이 한 줄 100%. 짝을 title 형까지 넓히면 단원 제목(`7 방어 작용`)이
    섞여 짝은 text 형만 받는다.

    짝: 번호 오른쪽 끝이 발문 왼쪽 끝 +5 이내이고 가로 틈 80 미만(0~1000 정규화 기준, `unit` 은
    픽셀 배율), 세로로 낮은 쪽 높이의 30% 넘게 겹친다. 틈이 가장 좁은 발문 하나.
    ★ 읽기 차례를 정한 **뒤**에 돈다. 차례를 정하기 전에 요소를 빼면 열 판정이 흔들린다
      (원장 `dropping-element-shifts-layout` 전례). 번호 요소를 빼도 다른 요소끼리의 차례는 그대로다.
    ★ 발문이 태그로 시작하면(`<!상자>` 등, `<!강조>` 만 예외) 붙이지 않는다 — 태그가 깨진다.
    ⚠ 계약 변화: 번호 요소가 응답에서 사라지고 번호는 발문 칸 글에 합쳐진다.
    ★★ **번호 요소의 형은 일부러 안 가린다**(#1068). MinerU 는 문항 번호 배지를 `page_number` 형으로도 내고
      ZERO 층 글도 숫자만 든 블록을 `page_number` 로 적는다. d8c dev·val 에서 쪽 가운데 `page_number` 번호
      232개 중 209(MinerU 91 · ZERO 118)가 **여기서 발문에 붙어 살아난다.** 번호 쪽 형을 `text` 로 조이면 그 209 가
      한꺼번에 사라지고 첫 `page_number` 가 페이지행 원본 쪽 번호 자리(`02`)를 차지한다. 조이려면 아래
      `_unpage_item_numbers`(#1068)와 같이 되돌려 봐라. 시험 `test_join_item_numbers.py::test_page_number_형_번호도_붙는다` 가
      이 동작을 지킨다(그 시험이 깨지면 209 가 깨진 것이다).
    ★ 위 짝을 못 찾으면 **왼쪽 끝이 같은 발문**을 본다(#1068, `ITEM_NUMBER_JOIN_ALIGNED=0` 이면 끔). ZERO 층 블록은 발문
      상자가 번호 자리까지 덮어(`06` [92,691,123,736] · 발문 [92,705,549,757]) 가로 틈이 음수라 위 조건에 안 걸린다.
      발문 왼쪽 끝이 번호 왼쪽 끝 ±5 이고 발문 윗변이 번호 높이 안에서 시작하는 것. 종전 짝이 있으면 안 본다.
      d8c dev·val 에서 18곳이 여기로 붙고 다른 쪽 출력은 안 바뀐다(결과 V2 temp/n10/결과_문항번호쪽번호_1068.md).
    """
    def txt(b: BBoxItem) -> str:
        c = ext_map.get(b.element_id)
        return (c.corrected_text or "") if c else ""

    def overlap(a, b) -> float:
        return min(a[3], b[3]) - max(a[1], b[1])

    aligned_on = os.environ.get("ITEM_NUMBER_JOIN_ALIGNED", "1") != "0"
    joined, taken, drop = 0, set(), set()
    for n in items:
        if not _valid_bbox(n) or not _ITEM_NUMBER_ONLY_RE.match(txt(n)):
            continue
        best = None
        aligned = None              # 왼쪽 끝이 같은 발문(위 ★) — (윗변 차, 차례, 요소)
        for s in items:
            body = txt(s).lstrip()
            if (s is n or s.type != "text" or s.element_id in taken or s.element_id in drop
                    or not _valid_bbox(s) or not body or _ITEM_NUMBER_ONLY_RE.match(body)
                    or (body.startswith("<!") and not body.startswith("<!강조>"))):
                continue
            gap = s.bbox[0] - n.bbox[2]
            h = min(n.bbox[3] - n.bbox[1], s.bbox[3] - s.bbox[1])
            if gap >= -5 * unit and gap < 80 * unit and overlap(n.bbox, s.bbox) > 0.3 * h:
                if best is None or gap < best[0]:
                    best = (gap, s)
            elif (aligned_on and abs(s.bbox[0] - n.bbox[0]) <= 5 * unit and s.bbox[2] > n.bbox[2]
                    and n.bbox[1] - 5 * unit <= s.bbox[1] <= n.bbox[3] and not body.startswith(txt(n).strip())):
                key = (abs(s.bbox[1] - n.bbox[1]), s.reading_order)
                if aligned is None or key < aligned[:2]:
                    aligned = (*key, s)
        if best is None and aligned is not None:
            best = (0, aligned[2])
        if best is None:
            continue
        s = best[1]
        ext_map[s.element_id].corrected_text = f"{txt(n).strip()} {txt(s).lstrip()}"
        taken.add(s.element_id); drop.add(n.element_id); joined += 1
    if drop:
        items[:] = [b for b in items if b.element_id not in drop]
        for eid in drop:
            ext_map.pop(eid, None)
        logger.info("문항 번호 붙임(C-107 ㄴ): %d곳", joined)
    return joined


def _unpage_item_numbers(items: list[BBoxItem], ext_map: dict, page_h: float) -> int:
    """붙이기(`_join_item_numbers`) 뒤에도 남은 `page_number` 형 문항 번호를 본문(`text`)으로 되돌린다. 고친 수(#1068).

    번호만 들었고(`_ITEM_NUMBER_ONLY_RE`) 쪽 위아래 10% 띠 밖에 있는 것만. d8c dev·val 쪽 번호(`page_number` 숫자)는
    전부 그 띠 안이다(아래 띠 1,445 · 위 띠 14, MinerU 원출력). 두면 페이지행이 첫 `page_number` 를 원본 쪽 번호로 써서
    `02` · `a02` 가 쪽 번호 자리에 찍히고 진짜 쪽 번호(`53`)는 본문에 홀로 밀려난다(언매 p0053 · 화작 p0073, 번호 옆이
    발문 아닌 표라 붙일 짝이 없는 꼴). 읽기 차례 뒤라 차례 슬롯은 그대로다. 되돌리기 `ITEM_NUMBER_UNPAGE=0`(호출 때 읽음).
    ⚠ 이것만 켜면(왼쪽 끝 붙이기 끔) ZERO 번호 19곳이 본래 차례(지문 한가운데)에 홀로 서서 실물이 dev·val 둘 다 나빠진다.
    """
    if not page_h or os.environ.get("ITEM_NUMBER_UNPAGE", "1") == "0":
        return 0
    n = 0
    for b in items:
        if (b.type == "page_number" and _valid_bbox(b) and b.bbox[3] > 0.1 * page_h and b.bbox[1] < 0.9 * page_h
                and (c := ext_map.get(b.element_id)) and _ITEM_NUMBER_ONLY_RE.match(c.corrected_text or "")):
            b.type = "text"
            n += 1
    if n:
        logger.info("쪽 가운데 page_number 번호 → 본문(#1068): %d곳", n)
    return n


# EBS 문항코드 `[26015-0017]` 만 든 요소 — 원장 C-107.
_ITEM_CODE_ONLY_RE = re.compile(r"^\s*[\[【]\s*\d{5}\s*-\s*\d{4}\s*[\]】]\s*$")
_ITEM_LEAD_NUM_RE = re.compile(r"^(\s*(?:<!강조>)?\s*\d{1,2}(?:<!/강조>)?)(?!\d)(?!\s*[)\].,쪽강])\s*")
# ★ 기본 X(`01 [코드] 발문`), 점역사가 책마다 고른다(대표 결재 2026-10-04, 원장 C-107).
#   gold 가 책마다 X · Y(코드 윗줄 · `01 발문`)로 갈리고 규정 조항이 없다. 꼴은 묵자에서 안 보이는 점역자 선택이라
#   자동으로 정하지 않는다. 기본은 관행 다수 X(2027 비홀드아웃 12권 중 7권), 요청마다 `PageTask.item_code_form` 으로 바꾼다.
#   ⚠ 기본 X 의 값(2027 dev·val, 대조 fe7a853): Y꼴 책 셋(001 · 009 · 013)에서 실제 손해가 난다(자 +487 · +370 · +431,
#   실물 009 +602 · 013 +270). 점역사가 그 책에서 Y 로 바꾸면 이득이 된다(자 −1,011 · −2 · −608). 바꾸지 않으면 손해가 남는다.
#   결과 V2 temp/n46/c/결과_C107_조합AB.md. 환경변수 `ITEM_CODE_FORM`(X · Y · off)은 서버 기본값이다.
_ITEM_CODE_FORM = os.environ.get("ITEM_CODE_FORM", "X")
# 요청(문서)마다 고른 꼴. `run()` 이 쪽 시작에 심는다 — 쪽 Task 마다 컨텍스트가 따로라 쪽 사이로 안 샌다.
_ITEM_CODE_FORM_JOB: ContextVar[str] = ContextVar("item_code_form", default="")


def _item_code_stem(code: BBoxItem, items: list[BBoxItem], txt, ux: float, uy: float):
    """문항코드의 발문(번호로 시작하는 요소)을 기하로 찾는다. 못 찾으면 None.

    묵자에서 코드는 번호 발문 윗줄 오른쪽에 앉는다. 코드와 가로로 겹치거나(발문 첫 줄이 길 때),
    코드 왼쪽 아래에서 끝나는(발문 첫 줄이 짧을 때) 발문 중, 윗변이 코드 아랫변 −25~+30
    (0~1000 정규화) 안에 있는 것. 설계 후보 2b — d8c dev·val 번호 아는 코드 1,205개에서
    맞음 1,103 · 틀림 0 · 못 찾음 102. 이웃 차례로 잡으면 다음 문항 코드를 앞 문항에 붙여
    틀림 105 라 버렸다(T44 '답 ④' 와 같은 함정).
    """
    x0, y0, x1, y1 = code.bbox
    best = None
    for s in items:
        if (s is code or s.type in ("header_footer", "page_number") or not _valid_bbox(s)
                or not _ITEM_LEAD_NUM_RE.match(txt(s)) or _ITEM_CODE_ONLY_RE.match(txt(s))
                or _ITEM_NUMBER_ONLY_RE.match(txt(s))):
            continue
        a0, b0, a1, b1 = s.bbox
        d = (b0 - y1) / uy
        if not -25 <= d <= 30:
            continue
        if min(x1, a1) - max(x0, a0) > 0:
            score = abs(d)
        elif a1 <= x0 + 5 * ux and (x0 - a1) / ux < 350:
            score = 30 + (x0 - a1) / ux / 10          # 같은 줄 왼쪽 발문은 아래 겹침보다 뒤
        else:
            continue
        if best is None or score < best[0]:
            best = (score, s)
    return best and best[1]


def _place_item_codes(items: list[BBoxItem], ext_map: dict, ux: float = 1.0, uy: float = 1.0,
                      form: str | None = None) -> int:
    """문항코드 요소를 `form` 꼴로 제 발문 옆에 둔다. 옮긴 수를 돌려준다. `off` 면 아무것도 안 한다.

    Y: 코드 요소를 발문 바로 앞 차례로 옮기고 제목 조판에서 뺀다(gold Y 꼴은 코드 줄이 문단 들여쓰기).
    X: 코드 글을 발문 번호 뒤에 `01 [26004-0003] 발문` 으로 합치고 코드 요소를 뺀다.
    `_join_item_numbers` 뒤에 돈다 — 번호가 따로 떨어져 있으면 발문을 못 알아본다.
    """
    form = form or _ITEM_CODE_FORM_JOB.get() or _ITEM_CODE_FORM
    if form not in ("X", "Y"):
        return 0

    def txt(b: BBoxItem) -> str:
        c = ext_map.get(b.element_id)
        return (c.corrected_text or "") if c else ""

    pairs, used = [], set()
    for c in items:
        if _valid_bbox(c) and _ITEM_CODE_ONLY_RE.match(txt(c)):
            s = _item_code_stem(c, items, txt, ux, uy)
            if s is not None and s.element_id not in used:
                used.add(s.element_id)
                pairs.append((c, s))
    if not pairs:
        return 0
    if form == "X":
        drop = set()
        for c, s in pairs:
            ext_map[s.element_id].corrected_text = _ITEM_LEAD_NUM_RE.sub(
                lambda m: f"{m.group(1)} {txt(c).strip()} ", txt(s), count=1)
            drop.add(c.element_id)
        items[:] = [b for b in items if b.element_id not in drop]
        for eid in drop:
            ext_map.pop(eid, None)
    else:
        codes = {c.element_id for c, _ in pairs}
        before = {s.element_id: c for c, s in pairs}
        order: list[BBoxItem] = []
        for b in sorted(items, key=lambda b: b.reading_order):
            if b.element_id in codes:
                continue
            if b.element_id in before:
                order.append(before[b.element_id])
            order.append(b)
        for i, b in enumerate(order, start=1):
            b.reading_order = i
        for c, _ in pairs:
            c.type, c.heading_level = "text", None
    logger.info("문항코드 %s꼴 배치(C-107): %d곳", form, len(pairs))
    return len(pairs)


def _split_list_marker_items(elements: list[dict]) -> list[dict]:
    """list_item 요소 중 줄머리 마커가 2개 이상이면 항목별로 쪼갠다(원소 dict 목록 변환).

    각 항목 = 마커 줄 + 다음 마커 전까지의 후속 줄(원문 줄바꿈 그대로, 인쇄 줄바꿈 포함).
    마커 앞 도입 문장(있으면)은 별도의 미분할 list_item으로 보존한다.
    """
    out: list[dict] = []
    for el in elements:
        if el.get("type") != "list_item":
            out.append(dict(el))
            continue
        content = el.get("content", "") or ""
        lines = content.split("\n")
        heads = {i for i, ln in enumerate(lines) if _LIST_SPLIT_MARKER_RE.match(ln.strip())}
        if len(heads) < 2:
            out.append(dict(el))
            continue
        groups: list[list[str]] = [[]]
        for i, ln in enumerate(lines):
            if i in heads:
                groups.append([ln])
            else:
                groups[-1].append(ln)
        if not groups[0]:
            groups.pop(0)
        for k, grp in enumerate(groups):
            child = dict(el)
            if _stable_ids() and el.get("id"):
                # 부모 id + 순번 — 같은 경계면 요청마다 같은 id 다(N5 · #1017). 종전엔 요청마다 uuid4 였다.
                child["id"] = str(uuid5(_EID_NS, f"{el['id']}|split|{k}"))
            else:
                child.pop("id", None)     # 새 UUID로 재발급(_parse_txt_result가 uuid4 폴백)
            child["flags"] = list(el.get("flags") or [])
            child["content"] = "\n".join(grp)
            out.append(child)
    # ★ 분절로 늘어난 요소 전부를 최종 리스트 위치로 재부여한다(원본 order 폐기).
    #   버그 이력(2026-07-20): 분절 자식만 order를 지워 idx 폴백을 태우면, 뒤이은
    #   미분절 요소는 원본(작은) order를 그대로 유지해 두 번호 체계가 섞인다 —
    #   예: list_item(order=3)을 4개로 쪼개면 자식은 idx=3~6인데 바로 다음 요소는
    #   원본 order=4를 유지해 자식④(order=6)보다 앞선 것처럼 역전된다. 이 비단조
    #   순서가 _reorder_columns의 연속성/y-위반 판정에 새어 들어가 다단 페이지의
    #   본문·사이드바 열 순서를 완전히 뒤섞었다(세계사 p105 실측: ee 342→1698).
    #   전 요소를 리스트 위치로 재부여하면 상대 순서가 그대로 보존되고 분절 유무와
    #   무관하게 단조 수열이 유지된다.
    for i, el2 in enumerate(out, start=1):
        el2["order"] = i
    return out


# ── 한 줄로 뭉친 선택지 갈라 놓기 (2026-08-10) ───────────────────────────────
# MinerU는 선택지를 쪽마다 다르게 낸다 — 어떤 쪽은 ①②③이 **각각 제 줄**, 어떤 쪽은
# **한 줄에 몰려서** 나온다. 뒤쪽이면 `layout_braille._mark_item_lines`가
# `len(src) < 2`로 조기 반환해 **항목 들여쓰기도 구분도 안 붙고**, 원문의 한 칸 띄어쓰기가
# 그대로 나간다.
#
# 실측(valall 6권 951쪽): 선택지 블록 243개 중 **48개(19.8%)**가 두 번째 모양으로 나갔다.
# 정답 도서는 결정적으로 일관적이다 — 항목 구분 **2칸 97.8%**(1500/1534),
# 선택지 줄 들여쓰기 **2칸 99.5%**(6981/7018). 규정도 같다(지침 3장3절4-(3)①).
#
# 한 줄에 항목 머리가 둘 이상이면 각 항목을 제 줄로 갈라 놓는다. 그 뒤는 기존 기계가
# 알아서 한다 — 여기서 들여쓰기를 직접 만지지 않는 게 중요하다(중복 적용을 피한다).
#
# ⚠ 항목이 하나뿐인 줄은 건드리지 않는다. 본문 안의 `①`(주석 참조 등)까지 가르면
#   멀쩡한 문장이 토막 난다.
_INLINE_CHOICE_SPLIT = re.compile(r"(?<=\S)\s+(?=[\u2460-\u2473]\s*\S)")


def _split_inline_choices(text: str) -> str:
    """한 줄에 몰린 ①②③…을 줄마다 하나씩으로 갈라 놓는다."""
    if not text or "\u2460" not in text and not any(
            "\u2460" <= ch <= "\u2473" for ch in text):
        return text
    out = []
    for line in text.split("\n"):
        heads = sum(1 for ch in line if "\u2460" <= ch <= "\u2473")
        out.append(_INLINE_CHOICE_SPLIT.sub("\n", line) if heads >= 2 else line)
    return "\n".join(out)


# ── 글상자 제목 승격 (2026-08-10) ────────────────────────────────────────────
# 4분류: ③ AI 오류 — 태깅 LLM이 상자 제목을 `<!상자>` 안에 넣을 때와 본문 줄로 남길 때가
#   갈린다. 원인은 MinerU 병합이다: 제목이 **별도 요소**로 오면(`보기`) 승격되고, 첫 항목에
#   **붙어 오면**(`보기ㄱ. A는 간기에…`) LLM이 떼어 내 본문 끝줄로 밀어 놓는다.
#   실측 EBS-E26-001 p0118: 네 상자 중 **둘만 승격**(별도 요소 2건 성공 / 병합 2건 실패).
#   정답은 넷 다 위 테두리에 제목을 박는다(지침 §2.1.6(1)②).
#
# ⚠ "짧은 한 줄이면 제목" 같은 일반 규칙은 쓰지 않는다 — 같은 표본의 004 p0118에서
#   `▵▵고교복`(글꼴 깨진 본문 첫 줄)이 걸렸는데 정답은 그걸 승격하지 않았다.
#   그래서 **정답에서 실제로 관측된 제목 낱말만** 승격한다(gold 2,917쪽 위 테두리 1,634건 실측:
#   〈보기〉 549 · 개념 체크 292 · 보기 285 · 수능 기본/실전 문제 각 72 · 자료 플러스 57 …).
#   ※ 괄호 유무(`〈보기〉` vs `보기`)는 **책마다 갈린다** — 우리는 원문 그대로 둔다(원장 C-28 성격).
from app.ai.braille.constants import BOX_TITLE_PROMOTABLE as _BOX_TITLE_PROMOTABLE  # noqa: E402 (정답 상자와 공유)
from app.ai.braille.constants import ENGLISH_GRADE1 as _ENGLISH_GRADE1, KOREAN_GRADE1 as _KOREAN_GRADE1  # noqa: E402
from app.ai.braille.constants import CHOICES_ONE_PER_LINE as _CHOICES_ONE_PER_LINE  # noqa: E402
from app.ai.braille.isolation import is_blocked_braille  # noqa: E402 (점역 못 한 요소 판정, #1275)
_BOX_BLOCK_RE = re.compile(
    r"(<!상자(\d?)>)(.*?)(<!/상자\2>)(.*?)(?=<!상자끝)", re.S)


# 인쇄면 줄바꿈을 잇는 요소 유형.
# list_item 도 넣는다(2026-08-24). "한 줄이 한 항목"이라 빼 뒀는데 실측이 반대다 —
# devall·valall 추출의 list_item 866건 중 **774건(89%)** 이 단 폭에 밀린 wrap 이고
# `사회 전체와의 연관 속에서 / 폭넓게 탐구하려는`처럼 어절이, 때로는 낱말이
# (`그 / 러다 보니`) 줄 끝에서 갈린다. 새 항목은 아래 `_LIST_HEAD_RE`가 지킨다.
_PARA_JOIN_TYPES = {"text", "caption", "footnote", "sidebar", "list_item"}
# 인쇄면 한 단으로 볼 최소 폭. 이보다 좁고 들쭉날쭉하면 시·대사처럼 줄바꿈 자체가
# 내용인 블록이라 잇지 않는다.
_PARA_MIN_COL = 15
# 괄호 꼴 항목 번호도 새 항목이다 — `(가)`·`(1)`. 이게 없으면 항목끼리 이어 붙는다.
_LIST_HEAD_RE = re.compile(
    r"^\s*(?:[①-⑮㉠-㉪]|\(\s*(?:[가-힣]|[0-9]{1,2})\s*\)"
    r"|[0-9]{1,2}\s*[.)]|[가-핳]\s*[.)]|[-•·])\s*")
# 보기 항목 자모 글머리(`ㄱ.` `ㄴ.`)도 새 항목이다(#1169). 위 `[가-핳]` 은 음절만 봐서, 앞 항목이 두 줄에 걸쳐 이어 붙으면
# 다음 자모 항목이 늘 붙었다(이어 붙인 앞 줄은 단 폭보다 길어 `fits` 가 거짓이다). 게이트 실행분(862227a) 경계에서 줄 가운데
# 붙은 자모 글머리 332(141쪽) → 18(남은 18은 경계에서 이미 한 줄). 「점자 도서 제작 지침」 〈보기〉 예는 항목마다 줄을 바꾸고
# 2칸 들인다(재추출본 3201~3205행 묵자 ↔ 3243~3249행 점자). 되돌리기 `JOIN_JAMO_HEAD=0`(호출 때 읽음).
_JAMO_HEAD_RE = re.compile(r"^\s*[ㄱ-ㅎ]\s*[.)]")


# 짝 없는 캡션의 생략 주 줄(원장 C-148, #1073 `result_builder._notify_orphan_captions`). 제목 줄 다음 줄이 내용이라
# 잇지 않는다 — 이으면 `거란(요)과 송(북송)의 영역 【점역자주】그림 생략【점역자주】` 한 문단이 된다(gold 는 두 줄).
# 이 꼴 그대로의 줄은 그 함수만 만든다(옛 꼴은 `생략: 제목` 이 표지 안에 들고, 캡션 끈 그림의 생략 주는 시각 요소라 여기 안 온다).
_OMIT_NOTE_LINE = "<!주>그림 생략<!/주>"


def _is_list_head(line: str) -> bool:
    return bool(_LIST_HEAD_RE.match(line) or line == _OMIT_NOTE_LINE
                or (os.environ.get("JOIN_JAMO_HEAD", "1") != "0" and _JAMO_HEAD_RE.match(line)))


# 낱말 갈림을 볼 때 양쪽 끝이 진짜 글자인지 확인한다 — 태그·기호 줄을 거른다.
_WORD_EDGE_RE = re.compile(r"[0-9A-Za-z가-힣]$")
_WORD_HEAD_RE = re.compile(r"^[0-9A-Za-z가-힣]")


# ★ T30 — 강조가 인쇄면 줄마다 따로 닫히고 열리면 낱말 가운데 갈림이 태그 뒤에 숨는다:
#   `…통해 가<!/강조>\n<!강조>출 동기…`. 판정기(`_join_words`)가 태그 글자를 보고 어절 경계로
#   읽어 두 잇기 함수 어디서도 안 이어졌다. 2027 8권 제품 응답 984쪽의 낱말 안 개행 16곳 중
#   진짜 낱말 안 7곳(`가‖출`·`평‖균`·`행‖동`·`기‖존`·`가‖능`·`아무‖런`·`진행‖하기로`)이 전부 이 꼴이고
#   나머지 9곳은 제목·이름표 줄(`보기`·`교초`)이다. 태그를 걷고 판정해 낱말 안이면 두 태그와 개행을
#   지워 강조 한 덩이로 잇는다. 어절 경계면 그대로 둔다(뒤의 잇기 함수가 맡는다).
_SPLIT_TAG_SPAN_RE = re.compile(
    r"([0-9A-Za-z가-힣])<!/([^<>\s/]+)>[ \t]*\n[ \t]*<!\2>(?=[0-9A-Za-z가-힣])")
_ANY_TAG_RE = re.compile(r"<!/?[^<>]*>")
# 강조 축 D(#1164) — **어절 경계**에서 인쇄 줄마다 갈린 강조도 한 덩이로 잇는다. 태그만 걷고 줄바꿈은 남겨
# 뒤의 줄 잇기(`_join_wrapped_lines`)가 띄어쓰기를 정하게 한다. 2027 게이트 실행분(862227a) 경계: 인쇄 줄바꿈 사이로
# 갈린 강조 중 gold 에서 한 강조 dev 142 · val 103, 두 강조 0. 같은 줄 빈칸 사이로 갈린 강조(언어와 매체 문법 예문의
# 낱말별 밑줄 `매끼를` · `새 밥으로`)는 gold 도 두 강조라 건드리지 않는다. 되돌리기 `EMPH_LINE_JOIN=0`(호출 때 읽음).
_SPLIT_EMPH_NL_RE = re.compile(r"<!/강조>([ \t]*\n[ \t]*)<!강조>")


def _join_split_tag_spans(text: str) -> str:
    if "\n<!" not in text:
        return text
    from app.ai.preprocessor.pdf_analyzer import _join_words

    def fix(m: re.Match) -> str:
        left = _ANY_TAG_RE.sub("", text[text.rfind("\n", 0, m.start()) + 1:m.start() + 1])
        rest = text[m.end():]
        right = _ANY_TAG_RE.sub("", rest.split("\n", 1)[0])
        if left.strip() and right.strip() and _join_words(left, right) == "":
            return m.group(1)
        return m.group(0)

    out = _SPLIT_TAG_SPAN_RE.sub(fix, text)
    if os.environ.get("EMPH_LINE_JOIN", "1") != "0":
        out = _SPLIT_EMPH_NL_RE.sub(lambda m: m.group(1), out)
    return out


def _join_split_words(text: str) -> str:
    """**낱말 가운데서** 갈린 줄만 잇는다 — `유전 물` / `질인`, `그` / `러다 보니`.

    이 갈림은 어떤 조판에서도 내용일 수 없다. 시·대사처럼 줄바꿈이 내용인 블록에서도
    낱말은 안 쪼갠다. 그래서 단 폭·유형을 따지지 않고 잇는다(NLD §1.2.1 어절단위 줄바꿈).
    붙일지 띄울지는 `_join_wrapped_lines`와 같은 판정기(`_join_words`)가 정한다.
    """
    if "\n" not in text:
        return text
    from app.ai.preprocessor.pdf_analyzer import _join_words

    out: list[str] = []
    touched = False
    for block in text.split("\n\n"):
        lines = [ln.strip() for ln in block.split("\n") if ln.strip()]
        if len(lines) < 2:
            out.append(block)
            continue
        merged = [lines[0]]
        for nxt in lines[1:]:
            # ★ **양쪽이 진짜 글자일 때만** 본다. `_join_words` 는 태그·기호 줄에도 빈
            #   구분자를 돌려주므로 그대로 믿으면 글상자 태그와 글머리가 붙는다
            #   (실측: `<!상자><!/상자>` + `•강아지는…` → 한 줄, A/B 에서 CER 악화로 잡혔다).
            if (_WORD_EDGE_RE.search(merged[-1]) and _WORD_HEAD_RE.match(nxt)
                    and not _LIST_HEAD_RE.match(nxt)
                    and _join_words(merged[-1], nxt) == ""):
                merged[-1] += nxt
                touched = True
            else:
                merged.append(nxt)
        out.append("\n".join(merged))
    # ★ 이을 것이 없으면 **원문을 그대로** 돌려준다. 재조립만 해도 줄 앞뒤 공백과 빈 줄이
    #   사라져 손댈 이유가 없는 요소까지 달라진다(실측: 갈림 없는 95쪽이 바뀌었다).
    return "\n\n".join(out) if touched else text


def _join_wrapped_lines(text: str) -> str:
    """인쇄면에서 끊긴 한 문단을 한 줄로 잇는다.

    MinerU/OCR 추출은 **인쇄면 한 줄이 한 줄**이라 문단 가운데 줄바꿈이 그대로 남는다.
    그대로 점역하면 어절이 인쇄면 줄 끝에서 갈린다 — `총 5개` / `의 문항이`가 두 어절로
    나가고, 32칸을 못 채운 짧은 줄이 남는다. 점자는 **어절 단위로** 접는 것이 규정이라
    (NLD §1.2.1 "어절단위 줄바꿈"), 인쇄면 줄바꿈은 점역 전에 지워야 한다.
    실측 OCR 텍스트 요소 5,621개 중 1,988개(35.4%)가 이 상태다.

    어느 줄바꿈이 인쇄면 줄바꿈인지는 **다음 줄 첫 어절이 이 줄에 들어갔겠는가**로 가른다.
    안 들어갔으면 단 폭에 밀린 것이니 잇고, 들어갔는데도 줄을 바꿨으면 그 줄바꿈은
    내용이다(시행·대사). 임계 상수가 없고 단 폭이 스스로 판정한다.

    붙일지 띄울지는 `pdf_analyzer._join_words`(형태소 분석)가 정한다 — TEXT_NATIVE
    경로가 이미 쓰는 것과 같은 판정기다. 빈 줄은 문단 경계라 그대로 둔다.
    """
    if "\n" not in text:
        return text
    from app.ai.preprocessor.pdf_analyzer import _join_words

    out: list[str] = []
    for block in text.split("\n\n"):
        lines = [ln.strip() for ln in block.split("\n") if ln.strip()]
        if len(lines) < 2:
            out.append(block)
            continue
        col = max(len(ln) for ln in lines)
        if col < _PARA_MIN_COL:
            # 좁은 단이라 문단 잇기는 안 한다. 다만 **낱말 가운데 갈림**은 잇는다 —
            # 그건 조판이 아니라 오류다. 이 게이트가 막고 있어서 b16exp 추출의 text
            # 요소 105건이 `유전 물` / `질인` 꼴로 남아 있었다(2026-08-24 실측).
            out.append(_join_split_words(block))
            continue
        merged = [lines[0]]
        for nxt in lines[1:]:
            sep = _join_words(merged[-1], nxt)
            head = nxt.split()[0]
            fits = len(merged[-1]) + 1 + len(head) < col
            # sep가 빈 문자열이면 어절 가운데서 갈린 것이라 무조건 잇는다 — 그 줄바꿈은
            # 어떤 조판에서도 내용일 수 없다(`총 5개` / `의 문항이`).
            if sep and (fits or _is_list_head(nxt)):
                merged.append(nxt)               # 들어갔는데 바꾼 줄 = 내용상 줄바꿈
            else:
                merged[-1] += sep + nxt
        out.append("\n".join(merged))
    return "\n\n".join(out)


def _promote_box_title(text: str) -> str:
    """제목 없는 글상자의 본문 첫/끝 줄이 정답에서 관측된 제목 낱말이면 위 테두리로 올린다."""
    if "<!상자" not in text:
        return text

    def fix(m: re.Match) -> str:
        open_tag, _lv, title, close_tag, body = m.group(1, 2, 3, 4, 5)
        if title.strip():
            return m.group(0)
        lines = body.split("\n")
        idxs = [i for i, ln in enumerate(lines) if ln.strip()]
        for i in (idxs[:1] + idxs[-1:]) if idxs else ():
            if lines[i].strip().strip("〈〉<>") in _BOX_TITLE_PROMOTABLE:
                new_title = lines[i].strip()
                rest = [ln for j, ln in enumerate(lines) if j != i]
                return open_tag + new_title + close_tag + "\n".join(rest)
        return m.group(0)

    return _BOX_BLOCK_RE.sub(fix, text)


def _parse_txt_result(
    extraction: dict, page_id: str
) -> tuple[LayoutResult, dict[UUID, ExtractedContent], str]:
    meta = extraction.get("meta", {})
    method = meta.get("extraction_method", "OCR")
    conf = 1.0 if method == "TEXT_NATIVE" else 0.95
    # 0~1000 정규화(MinerU)만 픽셀로 되돌린다. 페이지 크기를 모르면 손대지 않는다.
    # ★ 좌표계는 meta.bbox_space를 **읽는다**(생산자가 적어 준다). 옛 파일·주입 핸드오프엔
    #   그 키가 없어 종전 유추(TEXT_NATIVE=픽셀)로 폴백한다.
    iw, ih = meta.get("image_width") or 0, meta.get("image_height") or 0
    space = meta.get("bbox_space")
    if not space:
        # ★ 키가 없으면 **값으로 판정한다**(2026-08-19). 종전에는 추출 방식으로 유추해서
        #   OCR이면 무조건 norm1000으로 봤는데, 픽셀 좌표를 담은 옛 경계 파일이 그 길로
        #   들어와 좌표가 통째로 부풀었다(EBS-E26-013 p191: 경계 파일 y 75~1422가
        #   응답에서 111~2096. 배율이 정확히 image_height/1000 = 1.474였다).
        #   정규화 좌표는 정의상 0~1000을 못 넘으므로, 1000을 넘는 값이 하나라도 있으면
        #   픽셀이 확실하다. 추출 방식보다 값이 믿을 만한 근거다.
        vals = [v for el in extraction.get("elements", [])
                for v in (el.get("bbox") or []) if isinstance(v, (int, float))]
        space = "pixel" if (vals and max(vals) > 1000) else (
            "pixel" if method == "TEXT_NATIVE" else "norm1000")
    elif space == "norm1000":
        # ★ 2026-09-02 (원장 C-91 잔여) — 메타를 믿되 **값과 어긋나면 값을 따른다.**
        #   정규화 좌표는 정의상 0~1000 을 못 넘는다. `norm1000` 이라 적혀 있는데 쪽 최대값이
        #   1000 을 넘으면 그건 정규화가 아니다. 그대로 믿으면 픽셀 좌표를 한 번 더 확대해
        #   FE 하이라이트가 통째로 어긋난다.
        #   실측(dev·val 경계 1,200쪽): 4쪽이 여기 걸린다 — 쪽 최대 1,150·6,150·8,000 인데
        #   쪽 높이는 1,474 다. 확대하면 11,792 까지 간다.
        _pm = max((v for el in extraction.get("elements", [])
                   for v in (el.get("bbox") or []) if isinstance(v, (int, float))), default=0)
        if _pm > 1000:
            logger.warning("경계 meta 가 norm1000 이라는데 쪽 최대값이 %.0f 다 — 픽셀로 본다 "
                           "(확대하면 좌표가 어긋난다)", _pm)
            space = "pixel"
    scale_bbox = ((iw / 1000, ih / 1000, iw / 1000, ih / 1000)
                  if space == "norm1000" and iw and ih else None)

    bbox_items: list[BBoxItem] = []
    ext_map: dict[UUID, ExtractedContent] = {}

    _els = _split_list_marker_items(extraction.get("elements", []))
    _els = _split_foot_number(_els, 1000 if space == "norm1000" else ih)     # 꼬리말에 든 쪽 번호(#1264)
    _band = _page_edge_band(_els)
    for idx, el in enumerate(_els, start=1):
        try:
            eid = UUID(str(el.get("id")))
        except (ValueError, TypeError):
            eid = uuid4()
        orig_type = el.get("type", "text")
        etype = _TYPE_ALIAS.get(orig_type, orig_type)
        vsub = el.get("visual_subtype") or _SUBTYPE_FROM_TYPE.get(orig_type)
        order = int(el.get("order", idx))
        content = _join_split_tag_spans(el.get("content", "") or "")
        if etype in _PARA_JOIN_TYPES:
            content = _join_wrapped_lines(content)
        else:
            content = _join_split_words(content)      # 낱말 갈림은 유형을 안 가린다
        # 표는 보기 쪼개기를 안 탄다 — 한 행 HTML 에 원문자가 둘 이상이면 칸 안에 줄바꿈이 들어가
        # 격자가 행째로 부서진다(`01 ④` → `01\n④`). 쪼개기는 본문에 뭉친 선택지용이다.
        # 2027 dev·val 표 925개 중 실제로 바뀌던 표 7개: 정답 상자 1(#1040) · 나머지 6(#1042).
        # 두 스위치는 따로 되돌린다 — `ANSWER_BOX_FORM` · `TABLE_KEEP_CELLS`.
        if not (etype == "table" and (_table_keep_cells() or _is_answer_box_html(content))):
            content = _split_inline_choices(content)
        content = _promote_box_title(content)
        if etype in _TEXT_TYPES and _is_boilerplate(content):
            logger.info("보일러플레이트 드롭(%s): %.60s", etype, content)
            continue
        if etype == "header_footer" and _is_running_foot(content):
            logger.info("러닝풋 억제(header_footer): %.60s", content)
            continue
        if _is_edge_header(content, el.get("bbox"), _band):
            logger.info("지면 가장자리 머리글 억제(%s): %.60s", etype, content)
            continue
        # 추출 모델의 '못 읽었다' 해설문 → 내용 비우고 R11(원본 확인 요망)로 넘긴다.
        # 글자층에서 뽑은 글(TEXT_NATIVE)에는 모델 해설문이 생길 수 없다. 본문만 잘못 지운다(#1288).
        refused = method != "TEXT_NATIVE" and _is_extraction_refusal(content)
        if refused:
            logger.info("추출 실패 안내문 억제(%s): %.60s", etype, content)
            content = ""
        # heading_level: 현주 핸드오프가 주면 그 값, 없으면 title은 1단계 기본(PART 10 조판용)
        hlevel = el.get("heading_level")
        if hlevel in (None, 0) and etype == "title":
            hlevel = 1
        # bbox: 현주 레이아웃 좌표 → BoundingBox(x,y,x2,y2)로 BE 전달. 없거나 깨지면 (0,0,0,0).
        # ★ 경계 파일의 좌표계는 경로마다 다르다(`result_builder` 2026-07-19):
        #   MinerU = 0~1000 정규화 / ZERO·텍스트레이어 폴백 = 2x 렌더 픽셀. BE·FE는 `image_width/height`에
        #   대한 비율로 매핑하므로 **여기서 픽셀로 통일**한다. 안 하면 MinerU 쪽에서
        #   하이라이트가 실제 위치의 77%·65% 자리에 찍힌다(실측).
        raw_bbox = el.get("bbox")
        try:
            bbox = (int(raw_bbox[0]), int(raw_bbox[1]), int(raw_bbox[2]), int(raw_bbox[3]))
            if scale_bbox:
                bbox = tuple(int(round(v * s)) for v, s in zip(bbox, scale_bbox))
        except (TypeError, IndexError, ValueError):
            bbox = (0, 0, 0, 0)
        # caption_ref: 캡션→대상(그림/표) 연결. UUID 문자열만 수용, 그 외 None.
        raw_cref = el.get("caption_ref")
        try:
            caption_ref = UUID(str(raw_cref)) if raw_cref else None
        except (ValueError, TypeError):
            caption_ref = None
        flags = [str(f) for f in (el.get("flags") or [])]
        if refused and "R11" not in flags:
            flags.append("R11")          # IMAGE_TEXT_MISSING — 원본을 직접 봐야 하는 자리
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
                box_level=int(el.get("box_level") or 0),
            )

    wing = _reorder_by_geometry(bbox_items, int(meta.get("page_rotation") or 0))
    _band_explanations(bbox_items, ext_map, ih if (scale_bbox or space == "pixel") else 1000)
    _anchor_wing_terms(bbox_items, ext_map, wing)
    _join_item_numbers(bbox_items, ext_map, scale_bbox[0] if scale_bbox else 1.0)
    # 쪽 높이(bbox 와 같은 좌표계): 정규화를 픽셀로 늘렸으면 픽셀 높이, 정규화 그대로면 1000, 픽셀이면 메타 높이.
    _unpage_item_numbers(bbox_items, ext_map, ih if (scale_bbox or space == "pixel") else 1000)
    _place_item_codes(bbox_items, ext_map, scale_bbox[0] if scale_bbox else 1.0,
                      scale_bbox[1] if scale_bbox else 1.0)
    _box_concept_checks(bbox_items, ext_map)
    _mark_table_box_levels(bbox_items, ext_map)
    layout = LayoutResult(page_id=page_id, elements=bbox_items)
    return layout, ext_map, method


# 곁단 '개념 체크' 글상자(#1155). 사회 네 권 곁단의 개념 체크(제목 · 문항 · 정답)에는 묵자 사각형이 따로 없다(곁단 바탕
# 음영뿐, #1149 에서 상자 후보에서 뺐다). gold 는 그 묶음을 '개념 체크' 제목을 위 테두리에 박은 글상자로 적는다
# (`=GGGG @RC:5 ;NF[ GGG…=`, 동아시아사 body p0009 · 생활과 윤리 body p0096). #1149 켠 팔 270쪽: 제목 있는 쪽 224 ·
# gold 상자 221 · 우리 0. 최종 읽기순서에서 제목 → 번호 문항 → '정답' → 번호 답이 사이에 다른 글 없이 이어지는 쪽이 219다.
# 되돌리기 `CONCEPT_CHECK_BOX=0`(호출 때 읽음).
_CC_TITLE_RE = re.compile(r"^개념\s*체크$")
_CC_ITEM_RE = re.compile(r"^\d{1,2}\s*\.")
_INLINE_TAG_RE = re.compile(r"<!/?[^>]*>")

# 대표 기출 쪽의 해설 띠 차례(#1305). 문제 틀 둘이 위아래 띠로 놓이고 곁단에 문제마다 '정답과 해설' 상자가 같은 높이로
# 붙는다. `_reorder_columns` 3번은 그 곁단을 쪽 단위 참고 자료 단으로 보고 통째로 쪽 끝으로 미뤄 문제1 → 문제2 → 해설1 →
# 해설2 가 됐다. 「점자 도서 제작 지침」 2장 5(NLD-2.2.5) '내용의 계열 … 순서대로' · 주종 다단 '참고 자료는 본문 아래'를
# 문제 · 해설 짝 단위로 적용하면 띠 차례다. gold(holdout 뺀 90권)에서 이 꼴은 EBS 사회 네 권 86쪽에만 있고 모두 띠 차례,
# 쪽 끝 몰기 0쪽이다. dev · val 32쪽 중 30쪽이 바뀐다(가드 2쪽 그대로). 되돌리기 `EXPL_BAND_ORDER=0`(호출 때 읽음).
_EXPL_LABEL_RE = re.compile(r"^정답과\s*해설$")
_EXPL_BODY_RE = re.compile(r"^(?:정답\s*해설|정답\s*[①-⑤])")
_QUESTION_HEAD_RE = re.compile(r"^(?:대표\s*기출\s*문제|닮은꼴\s*문제)")


def _band_explanations(items: list[BBoxItem], ext_map: dict[UUID, ExtractedContent], page_h: float) -> None:
    """곁단 '정답과 해설' 덩이를 같은 높이 띠의 마지막 본문 요소 바로 뒤로 옮긴다(in-place, reading_order 만 바꾼다).

    표지(글이 정확히 '정답과 해설')가 둘 이상이고, 덩이마다 해설 몸이 있고, 띠마다 본문 요소가 있을 때만 움직인다.
    하나라도 어긋나면 손대지 않는다. 옮긴 덩이의 표지 요소에 근거 규정(NLD-2.2.5)을 남긴다.
    """
    if os.environ.get("EXPL_BAND_ORDER", "1") == "0" or page_h <= 0:
        return
    order = sorted(items, key=lambda b: b.reading_order)
    body = [_valid_bbox(b) and b.type not in ("header_footer", "page_number") for b in order]
    txt = [_INLINE_TAG_RE.sub("", ext_map[b.element_id].corrected_text or "").strip()
           if b.element_id in ext_map else "" for b in order]
    labels = [i for i in range(len(order)) if body[i] and _EXPL_LABEL_RE.match(txt[i])]
    if len(labels) < 2:
        return
    tol, gap = 0.03 * page_h, 0.02 * page_h            # 띠 경계 여유 · 덩이 안 세로 띄움 상한
    top = order[labels[0]].bbox[1]
    page_w = max(b.bbox[2] for b in order if _valid_bbox(b))
    # 본문 단 = 첫 표지 높이 아래의 넓은 요소들. 쪽 머리 제목은 뺀다 — 짝수 쪽은 해설 단이 왼쪽이라
    # 넓은 제목이 범위를 해설 단까지 늘린다(동아시아사 p0094).
    wide = [order[i].bbox for i in range(labels[0])
            if body[i] and order[i].bbox[2] - order[i].bbox[0] >= 0.3 * page_w and order[i].bbox[1] >= top - tol]
    if not wide:
        return
    m0, m1 = min(b[0] for b in wide), max(b[2] for b in wide)

    def side(i: int) -> bool:
        x0, _, x1, _ = order[i].bbox
        return body[i] and min(x1, m1) - max(x0, m0) < 0.5 * max(x1 - x0, 1)

    units: list[list[int]] = []
    for k, a in enumerate(labels):
        end = labels[k + 1] if k + 1 < len(labels) else len(order)
        unit = [a]
        for j in range(a + 1, end):
            if not side(j) or order[j].bbox[1] - max(order[x].bbox[3] for x in unit) > gap:
                break
            unit.append(j)
        if k + 1 < len(labels) and unit[-1] != end - 1:
            return                                     # 덩이 사이에 다른 요소
        units.append(unit)
    if any(not any(_EXPL_BODY_RE.match(txt[j]) for j in u) for u in units):
        return
    if any(side(i) and order[i].bbox[1] >= top - tol for i in range(labels[0])):
        return                                         # 곁단에 첫 표지보다 앞선 요소(출처 꼬리표 등)
    main = [i for i in range(labels[0]) if body[i] and not side(i)]
    # 띠 시작 = 표지 높이 − 3%. 그 위 10% 안 본문 단에 문제 머리표('대표 기출문제' · '닮은꼴 문제')가 있으면 거기부터다.
    # 머리표가 표지보다 68px 위에 오는 쪽(세계사 p0105)과 문제1 끝이 표지 45px 위인 쪽(동아시아사 p0094)이 함께 있어
    # 고정 여유 하나로는 못 가른다.
    bands = []
    for a in labels:
        ya = order[a].bbox[1]
        heads = [order[m].bbox[1] for m in main
                 if _QUESTION_HEAD_RE.match(txt[m]) and ya - 0.1 * page_h <= order[m].bbox[1] <= ya + tol]
        bands.append(min([ya - tol] + [y - 1 for y in heads]))
    bands.append(float("inf"))
    anchors = []
    for k in range(len(units)):
        # 마지막 띠는 쪽 아래 6%(꼬리말)만 뺀다 — 문제 선지 ⑤ 가 해설 덩이보다 아래로 내려가는 쪽이 있다.
        ms = [m for m in main if bands[k] <= order[m].bbox[1] < bands[k + 1] and order[m].bbox[1] < 0.94 * page_h]
        if not ms:
            return
        anchors.append(max(ms))
    if any(b <= a for a, b in zip(anchors, anchors[1:])):
        return
    moved = {j for u in units for j in u}
    seq: list[int] = []
    for i in range(len(order)):
        if i in moved:
            continue
        seq.append(i)
        if i in anchors:
            seq += units[anchors.index(i)]
    if seq == list(range(len(order))):
        return
    for k, i in enumerate(seq, start=1):
        order[i].reading_order = k
    for u in units:
        ext = ext_map.get(order[u[0]].element_id)
        if ext is not None and "NLD-2.2.5" not in ext.layout_rules:
            ext.layout_rules.append("NLD-2.2.5")


# 날개 용어 풀이 자리(원장 C-77). `_reorder_columns` 3번은 좁은 곁단(날개)을 참고 자료 단으로 보고 통째로 쪽 끝에 미룬다.
# 그런데 날개의 용어 풀이(제목 '의무론' + 풀이 문단)는 각주처럼 그 용어가 나온 본문 문단 바로 아래에 적는다.
# 「점자 도서 제작 지침」 2장 4 6) '각주는 주석이 위치한 본문 문단 다음'(재추출 1085행, NLD-2.2.4) · 점역사 답 Q8
# '날개단의 내용은 … 본문의 해당 설명 문단 바로 아래에 삽입하여 배치'(braille-source/text/점역사_qna.txt 27행).
# 차례만 옮긴 모의(dev · val, 날개 덩이 514 · 닻 505): 사회 네 권 실물 −99,431(좋 165 : 나 4).
# 쪽 끝에 두는 것: 개념 체크 · 정답 상자(그 뒤 날개 요소 전부), 라벨 · 번호 제목, 예문((예) · ☞ · →)이 달린 풀이.
# ⚠ 언매 gold 는 날개 풀이를 쪽 끝에 모은다(31/32). 예문 덩이를 남겨도 언매는 +3,580(0:9)이고 그걸 알고 Q8 을 따른다.
# 되돌리기 `WING_TERM_ORDER=0`(호출 때 읽음).
_WING_LABEL_RE = re.compile(r"^(?:개념체크|정답|자료플러스|개념플러스|기출플러스|수능|탐구|더알아보기|읽기자료|유제)")
_WING_NUM_RE = re.compile(r"^\s*\d+\s*[.)]|^\s*\d+\s")       # '1.' · '2 ' 번호 제목(용어 '9품중정제' · '5대 10국' 은 남긴다)
_WING_EXAMPLE_RE = re.compile(r"^\s*(?:\(예\)|예\)|☞|→|예:)|\(예\)")
_JOSA_TAIL_RE = re.compile(r"(?:의|와|과|및|란|이란|에서|으로|로|을|를|은|는|이|가)$")


def _wing_norm(s: str) -> str:
    return re.sub(r"[^가-힣A-Za-z0-9]", "", s)


def _wing_keys(title: str) -> list[str]:
    """닻 찾기 열쇠: 제목 전체 → 괄호 앞 → 2자 이상 낱말(긴 것부터, 같은 길이는 제목 차례)."""
    head = re.split(r"[(\[]", title)[0]
    words = sorted(dict.fromkeys(_JOSA_TAIL_RE.sub("", w) for w in re.findall(r"[가-힣]{2,}", head)), key=len, reverse=True)
    return [k for k in dict.fromkeys([_wing_norm(title), _wing_norm(head), *words]) if len(k) >= 2]


def _anchor_wing_terms(items: list[BBoxItem], ext_map: dict[UUID, ExtractedContent], wing: list[BBoxItem]) -> None:
    """후치된 날개의 용어 풀이 덩이를 그 용어가 처음 나온 본문 요소 바로 뒤로 옮긴다(in-place, reading_order 만 바꾼다)."""
    if os.environ.get("WING_TERM_ORDER", "1") == "0" or not wing:
        return
    wing_ids = {id(b) for b in wing}
    order = sorted(items, key=lambda b: b.reading_order)
    txt = [_INLINE_TAG_RE.sub("", ext_map[b.element_id].corrected_text or "").strip()
           if b.element_id in ext_map else "" for b in order]
    blocks: list[list[int]] = []
    boxed: set[int] = set()
    cur, in_box = None, False
    for i, b in enumerate(order):
        if b.type in ("header_footer", "page_number"):
            continue
        if id(b) not in wing_ids:
            cur, in_box = None, False
            continue
        t0 = _wing_norm(txt[i].split("\n")[0])
        box_head = t0.startswith("개념체크") or t0 == "정답"
        in_box = in_box or box_head                    # 개념 체크 · 정답 상자: 그 뒤 날개 요소는 상자 몫(생명과학 꼴)
        if b.type == "title" or box_head or cur is None:
            cur = [i]
            blocks.append(cur)
            if in_box:
                boxed.add(i)
        else:
            cur.append(i)
    # 상자 태그가 덩이 밖과 짝을 이루면 옮기지 않는다 — 여는 태그와 닫는 태그가 갈라져 상자가 찢기거나 엉뚱한 본문을
    # 감싼다(A/B 동아시아사 p0033 · p0061 · p0103: 날개 상자의 끝 태그가 다음 제목 · 본문 캡션에 붙어 왔다).
    # 덩이 안에서 짝이 맞는 상자(용어 하나가 제 상자)는 통째로 옮겨도 된다.
    delta = [len(re.findall(r"<!상자\d?>", ext_map[b.element_id].corrected_text or ""))
             - len(re.findall(r"<!상자끝\d?>", ext_map[b.element_id].corrected_text or ""))
             if b.element_id in ext_map else 0 for b in order]
    depth = [sum(delta[:i]) for i in range(len(order))]

    def box_safe(u: list[int]) -> bool:
        d = 0
        for j in u:
            d += delta[j]
            if d < 0:
                return False
        return depth[u[0]] == 0 and d == 0

    terms = [u for u in blocks
             if u[0] not in boxed and order[u[0]].type == "title" and len(u) >= 2
             and 0 < len(_wing_norm(txt[u[0]])) <= 15
             and not _WING_LABEL_RE.match(_wing_norm(txt[u[0]])) and not _WING_NUM_RE.match(txt[u[0]])
             and not any(_WING_EXAMPLE_RE.search(txt[j]) for j in u[1:]) and box_safe(u)]
    if not terms:
        return
    main = [i for i, b in enumerate(order) if id(b) not in wing_ids and b.type not in ("header_footer", "page_number")]
    mtxt = {i: _wing_norm(txt[i]) for i in main}
    after: dict[int, list[list[int]]] = {}
    for u in terms:
        for k in _wing_keys(txt[u[0]].split("\n")[0]):
            a = next((i for i in main if k in mtxt[i]), None)
            if a is not None:
                after.setdefault(a, []).append(u)
                break
    if not after:
        return
    moved = {j for us in after.values() for u in us for j in u}
    seq: list[int] = []
    for i in range(len(order)):
        if i in moved:
            continue
        seq.append(i)
        for u in after.get(i, []):
            seq += u
    # 닻이 마지막 본문 요소라 덩이가 이미 그 뒤에 있던 것은 옮긴 게 아니다 — 근거 규정을 안 남긴다(A/B 5쪽).
    def prev_of(idx) -> dict[int, int]:
        s = [i for i in idx if order[i].type not in ("header_footer", "page_number")]
        return dict(zip(s[1:], s))
    old_prev, new_prev = prev_of(range(len(order))), prev_of(seq)
    real = [u for us in after.values() for u in us if new_prev.get(u[0]) != old_prev.get(u[0])]
    if not real:
        return
    for k, i in enumerate(seq, start=1):
        order[i].reading_order = k
    for u in real:
        ext = ext_map.get(order[u[0]].element_id)
        if ext is not None and "NLD-2.2.4" not in ext.layout_rules:
            ext.layout_rules.append("NLD-2.2.4")


def _box_concept_checks(items: list[BBoxItem], ext_map: dict[UUID, ExtractedContent]) -> None:
    """'개념 체크' 제목 → 번호 문항 → '정답' → 번호 답 묶음을 글상자로 감싸고 제목은 위 테두리로 올린다(in-place)."""
    if os.environ.get("CONCEPT_CHECK_BOX", "1") == "0":
        return
    order = [it for it in sorted(items, key=lambda b: b.reading_order) if it.element_id in ext_map]
    texts = [_INLINE_TAG_RE.sub("", ext_map[it.element_id].corrected_text or "").strip() for it in order]
    raw = [ext_map[it.element_id].corrected_text or "" for it in order]
    drop: set = set()
    depth = 0                                    # 열린 상자 수 — 상자 안 개념 체크는 건드리지 않는다
    i = 0
    while i < len(order):
        if depth == 0 and _CC_TITLE_RE.match(texts[i]):
            j = i + 1
            while j < len(order) and _CC_ITEM_RE.match(texts[j]):
                j += 1
            k = j + 1 if j < len(order) and re.sub(r"[\s\u20de]", "", texts[j]) == "정답" else j
            m = k
            while k > j and m < len(order) and _CC_ITEM_RE.match(texts[m]):
                m += 1
            group = raw[i:m]
            if j > i + 1 and m > k > j and not any("<!상자" in t for t in group):
                first, last = ext_map[order[i + 1].element_id], ext_map[order[m - 1].element_id]
                first.corrected_text = f"<!상자>{texts[i]}<!/상자>\n{first.corrected_text}"
                last.corrected_text = f"{last.corrected_text}\n<!상자끝><!/상자끝>"
                drop.add(order[i].element_id)
                i = m
                continue
        depth += len(re.findall(r"<!상자\d?>", raw[i])) - len(re.findall(r"<!상자끝\d?>", raw[i]))
        i += 1
    if drop:
        items[:] = [it for it in items if it.element_id not in drop]
        for eid in drop:
            ext_map.pop(eid, None)


def _mark_table_box_levels(items: list[BBoxItem], ext_map: dict[UUID, ExtractedContent]) -> None:
    """표 위계 = min(경계 키 `box_level`, 최종 읽기순서에서 그 표를 감싼 상자 위계)(#1110, in-place).

    표에는 상자 태그를 못 단다 — 표 HTML 안에 넣으면 표 체인이 깨진다(`tag_boxed_elements`). 그래서 어느 상자
    **사각형 안**인지는 경계 키로 오고, 실제로 상자 **안에 그려지는지**는 읽기순서 재배정 뒤 앞뒤 글 요소의
    태그로 다시 본다. 둘 중 하나만 보면 틀린다(#1110 A/B):
      · 태그 깊이만(1차) — 재배정이 곁단 상자의 여는 태그와 닫는 태그를 갈라 놓으면 그 사이에 낀 본문 표까지
        상자 안으로 잡힌다(동아시아사 p0033 자 +233).
      · 경계 키만 — 사각형 안이어도 첫 글 앞 · 끝 글 뒤에 그려지면 상자 밖이다.
    작은 값을 쓰는 것은 바깥 상자 구간에만 든 안쪽 상자 표를 한 단계 더 올리지 않으려는 것이다.
    요소 flags 는 BE 응답으로 나가서 쓰지 않는다(`ExtractedContent.box_level` 은 내부 값).
    """
    from app.ai.braille.translator import box_borders_from_source
    depth: list[int] = []
    for it in sorted(items, key=lambda b: b.reading_order):
        ext = ext_map.get(it.element_id)
        if ext is None:
            continue
        if it.type == "table":
            ext.box_level = min(ext.box_level, depth[-1]) if depth else 0
            continue
        for kind, level, _title in box_borders_from_source(ext.corrected_text or ""):
            if kind == "top":
                depth.append(level)
            elif level in depth:
                while depth.pop() != level:
                    pass


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
        # 점역은 순수 CPU 동기 작업이라 코루틴 안에서 부르면 이벤트 루프가 멈춘다
        # (실측 쪽당 p95 2.1초). 전용 풀로 내린다 — app/core/limits.py 참조.
        braille_outputs = await run_braille(TextBraille().translate, llm_outputs)
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
        # 점역은 순수 CPU 동기 작업이라 코루틴 안에서 부르면 이벤트 루프가 멈춘다
        # (실측 쪽당 p95 2.1초). 전용 풀로 내린다 — app/core/limits.py 참조.
        braille_outputs = await run_braille(FormulaBraille().translate, llm_outputs)
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
        # 점역은 순수 CPU 동기 작업이라 코루틴 안에서 부르면 이벤트 루프가 멈춘다
        # (실측 쪽당 p95 2.1초). 전용 풀로 내린다 — app/core/limits.py 참조.
        box_levels = {e.element_id: e.box_level for e in extracted if e.box_level}
        braille_outputs = await run_braille(TableBraille(box_levels).translate, llm_outputs)
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
        from app.ai.braille.visual_braille import ImageBraille
        # 점역은 순수 CPU 동기 작업이라 코루틴 안에서 부르면 이벤트 루프가 멈춘다
        # (실측 쪽당 p95 2.1초). 전용 풀로 내린다 — app/core/limits.py 참조.
        braille_outputs = await run_braille(ImageBraille().translate, llm_outputs)
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
        from app.ai.braille.visual_braille import CartoonBraille
        # 점역은 순수 CPU 동기 작업이라 코루틴 안에서 부르면 이벤트 루프가 멈춘다
        # (실측 쪽당 p95 2.1초). 전용 풀로 내린다 — app/core/limits.py 참조.
        braille_outputs = await run_braille(CartoonBraille().translate, llm_outputs)
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
        from app.ai.braille.visual_braille import ChartGraphBraille
        # 점역은 순수 CPU 동기 작업이라 코루틴 안에서 부르면 이벤트 루프가 멈춘다
        # (실측 쪽당 p95 2.1초). 전용 풀로 내린다 — app/core/limits.py 참조.
        braille_outputs = await run_braille(ChartGraphBraille().translate, llm_outputs)
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
        from app.ai.braille.visual_braille import DiagramBraille
        # 점역은 순수 CPU 동기 작업이라 코루틴 안에서 부르면 이벤트 루프가 멈춘다
        # (실측 쪽당 p95 2.1초). 전용 풀로 내린다 — app/core/limits.py 참조.
        braille_outputs = await run_braille(DiagramBraille().translate, llm_outputs)
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
                     time.monotonic() - t0, exc,
                     extra={"job_id": task.job_id, "page": task.page_no,
                            "stage": label, "status": "CHAIN_FAILED"})
        raise
    _chain_done += 1
    n_llm = len(result[1]) if isinstance(result, tuple) else 0
    step(_chain_done, total, label, f"{len(elems)}요소→{n_llm}블록 {time.monotonic() - t0:.1f}s")
    return result


# mode b 표 블록. table_opt/table_braille가 쓰는 것과 같은 태그다(tag_names 미등재 —
# `표`·`행`·`칸`은 translator의 인라인 마커가 아니라 **표 체인 전용 구조 태그**다).
_MODE_B_TABLE_RE = re.compile(r"<!표>.*?<!/표>", re.DOTALL)
# hwp·docx 에서 뽑은 표는 BE 가 **HTML `<table>`** 로 실어 보낸다(노션 Review T705·T706).
# 종전에는 `<!표>` 형식만 표로 봤고, HTML 은 평범한 글줄로 떨어져 **마크업이 그대로
# 점자화**됐다(`<table>` → ⠠⠦⠞⠁⠼⠴⠄ …). 같은 격자 파서(`table_opt._html_to_grid`)로
# 태그 형식으로 옮겨 표 체인에 태운다 — 병합 셀 처리도 그쪽 규약을 그대로 따른다.
_MODE_B_HTML_TABLE_RE = re.compile(r"<table[^>]*>.*?</table>", re.DOTALL | re.IGNORECASE)


def _mode_b_html_tables_to_tags(src: str) -> str:
    """mode b 원문의 HTML 표를 `<!표>` 태그 형식으로 바꾼다. 표가 없으면 그대로."""
    if not src or "<table" not in src.lower():
        return src
    from app.ai.braille.table_braille import build_table_tags
    from app.ai.llm.table_opt import _html_to_grid

    def _sub(m: re.Match) -> str:
        try:
            rows = _html_to_grid(m.group(0), expand=False)
        except Exception:  # noqa: BLE001 — 못 읽으면 원문 그대로(종전 동작)
            logger.warning("mode b HTML 표 파싱 실패 — 원문 유지")
            return m.group(0)
        return build_table_tags(rows) if rows else m.group(0)

    return _MODE_B_HTML_TABLE_RE.sub(_sub, src)


# 괄호로 묶인 표지만 든 줄(`<보기>` · `[자료1]` · 〈보기 1〉) — mode b 글상자의 여는 줄.
# 조사·서술이 붙으면(`<보기>의 ㄱ에…`) 참조지 표지가 아니므로 줄 전체가 표지여야 한다.
_MODE_B_BOX_LABEL_RE = re.compile(r"^[<〈【\[][^<>〈〉【】\[\]]{1,20}[>〉】\]]$")
_MODE_B_BOX_MAX_LINES = 30


def _mode_b_segments(src: str) -> list[tuple[int, str, str]]:
    """mode b source_text → [(원본 줄 번호, 요소 유형, 텍스트)].

    `<!표>…<!/표>`는 여러 줄에 걸쳐도 **요소 하나**로 묶어 표 체인에 보낸다. 줄 단위로
    쪼개면 `<!행>`만 든 조각이 생겨 표 구조가 복원 불가능해진다. 나머지는 종전대로
    줄 하나 = 요소 하나(빈 줄은 요소를 만들지 않고 번호만 건너뛴다 — 2026-08-06).

    글상자도 표와 같은 자리다(#732 D · 표는 #724). 표지 줄을 제 요소로 떼면 태깅 LLM이
    **그 줄 하나만** 보고 `<!상자>표지<!/상자>` + `<!상자끝>`을 같은 요소 안에 내므로
    위·아래 테두리가 붙어 나오고 본문이 상자 밖으로 떨어진다 — 상자가 늘 빈다.
    표지 줄부터 다음 빈 줄 앞까지를 요소 하나로 묶어 LLM이 상자의 끝을 보게 한다.
    (mode c는 `pdf_analyzer`의 벡터 테두리 검출이 요소를 가로질러 닫으므로 이 병이 없다.)
    """
    def _lines(a: int, b: int) -> list[tuple[int, str, str]]:
        base = src.count("\n", 0, a) + 1
        raw = src[a:b].split("\n")
        out: list[tuple[int, str, str]] = []
        i = 0
        while i < len(raw):
            if not raw[i].strip():
                i += 1
                continue
            # ponytail: 평문에는 테두리가 없어 빈 줄이 유일한 상자 끝 신호다.
            # 빈 줄이 한 줄도 없는 원고에서 통째로 한 요소가 되지 않게 줄 수로도 끊는다
            # (점자 한 면이 25줄이라 32칸 이전의 평문 30줄이면 이미 두 면을 넘는다).
            if (_MODE_B_BOX_LABEL_RE.match(raw[i].strip())
                    and i + 1 < len(raw) and raw[i + 1].strip()):
                j, stop = i + 1, min(len(raw), i + 1 + _MODE_B_BOX_MAX_LINES)
                while j < stop and raw[j].strip():
                    j += 1
                out.append((base + i, "text", "\n".join(raw[i:j])))
                i = j
                continue
            out.append((base + i, "text", raw[i]))
            i += 1
        return out

    segs: list[tuple[int, str, str]] = []
    pos = 0
    for m in _MODE_B_TABLE_RE.finditer(src):
        segs += _lines(pos, m.start())
        segs.append((src.count("\n", 0, m.start()) + 1, "table", m.group(0)))
        pos = m.end()
    return segs + _lines(pos, len(src))


async def _run_pipeline(task: PageTask) -> dict:
    page_id = f"p_{task.page_no:03d}"

    doc_meta: Optional[DocumentMeta] = None
    image_width = 0
    image_height = 0

    # ── mode b: source_text 단일 텍스트 체인 ───────────────────────────
    if task.mode == "b":
        # ★ 줄 하나 = 요소 하나 (2026-08-06). 종전에는 source_text 전체를 요소 **하나**로
        #   묶어 내보내서, BE가 원문과 점역을 줄 단위로 짝지을 수 없었다("한 뭉텅이로 온다").
        #   BE는 txt·hwp를 줄마다 `\n`으로 이어 붙인 한 문자열로 보내므로, 그 `\n`이
        #   그대로 요소 경계다.
        #   · 빈 줄은 요소를 만들지 않는다 — 지침상 문단 구분은 빈 줄이 아니라 들여쓰기다
        #     (NLD 2장2절2 "3칸에서 시작"). 대신 `order`에 **원본 줄 번호**를 그대로 실어
        #     BE가 빈 줄이 어디였는지 알 수 있게 한다(번호가 건너뛴다).
        #   · id는 `text_list`와 `braille_text_list`가 같다 — 그게 짝짓기의 열쇠다.
        # 표 되읽기 두 갈래: BE 가 hwp·docx 에서 보낸 HTML `<table>` 과, 점역사가 우리
        # 묵자 초안을 고쳐 되돌린 테두리 블록(`┌ ├ └`). 둘 다 `<!표>` 태그로 옮겨
        # 같은 표 체인에 태운다 — 안 그러면 테두리 줄이 `[처리 불가]` 로 찍힌다(#723).
        from app.ai.braille.table_braille import parse_print_frames
        _src = parse_print_frames(_mode_b_html_tables_to_tags(task.source_text or ""))
        src_lines = _mode_b_segments(_src)
        if not src_lines:                       # 내용이 없으면 빈 응답(빈 결과 금지 규칙은
            src_lines = [(1, "text", task.source_text or "")]   # 플레이스홀더가 담당)
        line_ids = [uuid5(_EID_NS, f"{task.job_id}|{task.page_no}|b|{i}|{typ}|{txt[:40]}")
                    if _stable_ids() else uuid4()          # 같은 원문이면 같은 id(N5 · #1017)
                    for i, (_, typ, txt) in enumerate(src_lines)]
        layout_result = LayoutResult(
            page_id=page_id,
            elements=[BBoxItem(element_id=eid, type=typ, bbox=(0, 0, 0, 0),
                               reading_order=no)
                      for eid, (no, typ, _) in zip(line_ids, src_lines)],
        )
        extracted_texts = [ExtractedContent(
            element_id=eid,
            corrected_text=ln,
            ocr_confidence=1.0,
        ) for eid, (_, _, ln) in zip(line_ids, src_lines)]
        # 표 세그먼트는 표 체인으로 보낸다 — <!표>/<!행>/<!칸>을 아는 것은 table_braille뿐이라
        # 텍스트 체인에 넣으면 translator가 미지 태그로 지우고 셀이 한 줄로 붙어 버린다.
        _by_type = {"table": [], "text": []}
        for e, (_, typ, _t) in zip(extracted_texts, src_lines):
            _by_type[typ].append(e)
        _chains = [_run_text_chain(_by_type["text"], layout_result, "ZERO", task,
                                   include_braille=True)]
        if _by_type["table"]:
            _chains.append(_run_table_chain(_by_type["table"], layout_result, "ZERO", task,
                                            include_braille=True))
        # 요소 격리(불변 규칙 3) — 표 하나가 깨져도 본문은 나가야 한다.
        ext, llm_outputs, braille_outputs = [], [], []
        for _r in await _gather_chains(_chains):
            if isinstance(_r, Exception):
                logger.error("mode b 체인 실패 (계속 진행): %s", _r)
                continue
            for _dst, _src in zip((ext, llm_outputs, braille_outputs), _r):
                _dst.extend(_src)
        flat: dict = {}
        if braille_outputs:
            from app.ai.braille.layout_braille import LayoutBraille, flatten_elements
            # ★ 순서 주의: flatten이 먼저다. layout()이 braille_lines를 32칸 조판본으로
            #   write-back하고 rule_trail도 그 프레임으로 재매핑하므로, 통 문자열은
            #   조판 전 논리 줄에서 떠야 한다(조판 가이드 §3).
            # 조판도 CPU 동기 작업 + 파일 쓰기라 전용 풀로 내린다(점역과 같은 이유).
            flat = await run_braille(flatten_elements, braille_outputs, layout_result)
            await run_braille(
                LayoutBraille().layout, braille_outputs, task.page_no, task.job_id,
                layout_result=layout_result,
            )
        return _build_response(
            task, page_id, doc_meta, "ZERO", image_width, image_height,
            layout_result, ext, llm_outputs, braille_outputs, flat=flat,
        )

    # ── mode a, c ──────────────────────────────────────────────────────
    # Phase 1 (현주): 경계 파일이 없으면 현주 추출로 생성. 있으면 그대로 사용.
    with stage("추출") as st:
        reuse_reason: str | None = "no_boundary"
        stamp: dict = {}
        if _txt_result_path(task).exists():
            reuse_reason, stamp = _stamp_verdict(task)
            reuse_reason = _boundary_reuse(reuse_reason)
        # 경계 재사용을 계수기에 남긴다 — `never` 팔이 진짜 다시 떴는지 `경계 hit=0` 으로 본다.
        from app.utils.req_log import record_cache
        record_cache("경계", reuse_reason is None)
        if reuse_reason is None:
            extraction = _read_txt_result(task)
            doc_meta = DocumentMeta(**stamp["doc_meta"])
            # ★ 경계 지문(`_stamp_verdict`)은 코드·프롬프트·env 만 본다. **요청마다 달라지는
            #   `advanced_ai` 는 거기 없다** — 그래서 MinerU 로 만든 경계가 고급 점역 요청에
            #   그대로 재사용됐다. 유료 옵션이 조용히 안 도는 두 번째 자리다(#788).
            #   원하는 추출(LLM_VISION)이 아니면 재파생한다.
            if (task.advanced_ai
                    and extraction.get("meta", {}).get("extraction_method") != "LLM_VISION"):
                reuse_reason = "advanced_ai"
            else:           # 경계를 뜰 때 센 관문을 이 쪽 몫으로(#1032)
                gates.gate_restore(extraction.get("meta", {}).get("gate_counts"))
        if reuse_reason is not None:
            if reuse_reason != "no_boundary":
                logger.info("경계 stamp 무효(%s) → 재파생 job=%s page=%d",
                            reuse_reason, task.job_id, task.page_no)
            doc_meta, extraction = await _extract_with_hyunju(task)
            _write_txt_result(task, extraction, doc_meta)
            _debug_dump(task, "02_doc_meta", doc_meta.model_dump())
        method0 = extraction.get("meta", {}).get("extraction_method", "?")
        st.note = (f"{len(extraction.get('elements', []))}요소 · {method0} · "
                   f"{'경계 재사용' if reuse_reason is None else f'재파생({reuse_reason})'}")

    # 원본 페이지 크기(경계 meta) → 응답 image_width/height. bbox와 같은 좌표계(2x 픽셀).
    _meta0 = extraction.get("meta", {})
    image_width = int(_meta0.get("image_width") or 0)
    image_height = int(_meta0.get("image_height") or 0)

    # Phase 2 (태민): 경계 파일 → 분해 → 6-체인
    # 수식 지면이면 평문 속 `p-q`·`(x, y)` 도 수식으로 보낸다(T16 · 원장 R-85). 신호는 추출 effort
    # 라우터와 같은 한컴 수식 글꼴 비율이다. PDF 가 없는 요청(mode b)은 종전대로 꺼 둔다.
    math_page = False
    if task.pdf_data:
        from app.ai.parser.mineru_runner import _is_math_page
        math_page = await asyncio.to_thread(_is_math_page, task.pdf_data, max(0, task.page_no - 1))
    # 추출이 버린 본문 글(#1284) — 원본 글자층에는 있는데 MinerU 가 못 읽어 묵자에 없는 글. 경계 손실 목록 중 대조 잡음을
    # 거른 것만 그 자리 요소에 R1 로 단다(품질 검사). 끄기 `LOST_TEXT_FLAG=0`.
    #   걸친 글 요소가 있으면 그 줄을 원본 글자층으로 그 요소에 넣는다(#1303, `preprocessor.lost_lines`, 끄기
    #   `LOST_TEXT_RESTORE=0`). 분해 전에 경계 요소 글을 고친다. 경계 파일은 안 바뀐다. R1 은 넣기 전 요소로 골라 수가 그대로다.
    lost_text: dict = {}
    lost_restored: dict = {}
    if _meta0.get("bbox_space") == "norm1000" and process_env("LOST_TEXT_FLAG") != "0":
        from app.ai.quality.quality_checker import lost_text_hosts
        lost_text = lost_text_hosts(extraction.get("extraction_losses"), extraction.get("elements") or [], math_page)
        if lost_text and task.pdf_data and not int(_meta0.get("page_rotation") or 0):
            try:
                import fitz
                from app.ai.preprocessor.lost_lines import restore_lost_lines
                from app.ai.preprocessor.pdf_analyzer import _coerce_pdf_bytes
                with fitz.open(stream=_coerce_pdf_bytes(task.pdf_data), filetype="pdf") as _d:
                    lost_restored = restore_lost_lines(
                        extraction.get("elements") or [], extraction.get("extraction_losses"),
                        _d[max(0, min(task.page_no - 1, _d.page_count - 1))], math_page)
            except Exception as exc:      # noqa: BLE001 — 되살리기는 덤, 실패는 격리(R1 은 그대로 남는다)
                logger.warning("빠진 줄 되살리기 건너뜀 (page=%d): %s", task.page_no, exc)
    layout_result, ext_map, _method = _parse_txt_result(extraction, page_id)
    if task.pdf_data:
        from app.ai.braille import inline_math
        inline_math.MATH_PAGE.set(math_page)
    # 표 칸 한 음절 오독(#1296) — 표 교정이 못 고친 한글 오독(정벌 → 정별)을 그 표 요소에 R4 로 짚는다. 점자 · 응답 꼴은
    # 안 바뀐다. 표 교정과 같은 층 글(`_native_text_pair`)을 본다. 끄기 `TABLE_MISREAD_FLAG=0`.
    #   추출이 이미 고친 자리(경계 요소 `table_fixes`, B3)도 R4 로 남긴다. 고침이 틀렸을 때 점역사가 볼 신호다.
    misread: dict = {}
    _tables = [e for e in extraction.get("elements") or [] if e.get("type") == "table" and "<t" in (e.get("content") or "")]
    _misread_on = _meta0.get("bbox_space") == "norm1000" and process_env("TABLE_MISREAD_FLAG") != "0"
    table_fixed = {str(e.get("id")): e["table_fixes"] for e in _tables if e.get("table_fixes")} if _misread_on else {}
    if _tables and _misread_on and task.pdf_data:
        try:
            import fitz
            from app.ai.parser.mineru_runner import table_misreads
            from app.ai.preprocessor.pdf_analyzer import _coerce_pdf_bytes
            with fitz.open(stream=_coerce_pdf_bytes(task.pdf_data), filetype="pdf") as _d:
                _pg = _d[max(0, min(task.page_no - 1, _d.page_count - 1))]
                for e in _tables:
                    spots = table_misreads(_pg, e.get("bbox"), e["content"])
                    if spots:
                        misread[str(e.get("id"))] = spots
        except Exception as exc:          # noqa: BLE001 — 표시는 있으면 좋은 것, 실패는 격리
            logger.warning("표 칸 오독 표시 건너뜀 (page=%d): %s", task.page_no, exc)
    # 읽기순서 LLM 보정(원장 C-106 · 대표 결재 2026-09-07). 비회전 쪽만 태우고,
    # 실패·순열아님·안전판이면 규칙 순서 그대로 간다. 근거·수치는 llm_order 도크스트링.
    from app.ai.parser import llm_order            # 지연 임포트(anthropic SDK 는 호출 때만)
    with stage("읽기순서 LLM") as st:
        _lo = await llm_order.apply(layout_result, ext_map,
                                    int(_meta0.get("page_rotation") or 0), (image_width, image_height))
        st.note = (f"{'적용' if _lo['applied'] else _lo['reason'] or '건너뜀'}"
                   f" · 이동비율 {_lo['ratio']}")
        # ★ 관문 G2(재구조화 §2-2) — **기존 검사를 그대로 두고 기록만** 한다.
        #   `llm_order` 의 순열 검사·안전판은 이미 규칙 순서로 조용히 돌아간다. assert 로
        #   바꾸면 쪽이 BLOCKED 이고 `-O` 면 검사가 통째로 사라진다(원안 철회).
        #   LLM 을 부르고도 못 쓴 쪽만 센다 — 안 부른 쪽(꺼짐·회전)은 되돌림이 아니다.
        if _lo["called"] and not _lo["applied"]:
            gates.gate_hit("G2", _lo["reason"] or "되돌림")
    # ★ 3-d: `doc_meta` 는 이제 두 갈래 모두에서 채워진다(재사용이면 stamp 에서 읽는다).
    #   종전의 `extraction_method` 역추론은 지웠다 — 코퍼스 PDF 를 직접 재면 STANDARD 인데
    #   실제 실행은 아닌 쪽이 있어 티어를 잘못 적었다(원장 `routing-tier-from-run-state`).
    routing_tier = doc_meta.routing_tier
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
        chain_results = await _gather_chains(
            [_run_chain_logged(label, elems, fn, i, len(active))
             for i, (label, elems, fn) in enumerate(active)])

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

    # PART 10: 레이아웃 조판 — 다운로드용 result.brf/txt 저장은 그대로 둔다.
    # 응답 contents는 조판본이 아니라 통 문자열이다(조판 가이드 §3, AI finalize 폐기).
    # ★ 별책 참조 번호는 **조판 앞에서** 채운다(2026-09-02). flatten_elements 가 초안별
    #   점자를 `flat` 에 굳혀 두므로, 그 뒤에 번호를 채우면 묵자에만 반영되고 점자 초안은
    #   번호 없는 옛 문구로 남는다 — 점역사 화면의 두 창이 다른 말을 했다.
    _order_map = {e.element_id: e.reading_order for e in layout_result.elements}
    all_llm.sort(key=lambda o: _order_map.get(o.element_id, 1_000_000))
    _number_volume_refs(all_llm, task.page_no, all_braille)

    flat: dict = {}
    if include_braille and all_braille:
        with stage("조판"):
            from app.ai.braille.layout_braille import LayoutBraille, flatten_elements
            # ★ 순서 주의: flatten이 먼저다(위 mode b 주석 참조).
            flat = await run_braille(flatten_elements, all_braille, layout_result)
            await run_braille(
                LayoutBraille().layout, all_braille, task.page_no, task.job_id,
                layout_result=layout_result,
            )

    return _build_response(
        task, page_id, doc_meta, routing_tier, image_width, image_height,
        layout_result, all_extracted, all_llm, all_braille, flat=flat,
        caption_disabled=extraction.get("meta", {}).get("caption_disabled"),
        lost_text=lost_text,
        misread=misread,
        table_fixed=table_fixed,
        lost_restored=lost_restored,
    )


def _number_volume_refs(llm_outputs: list[LLMOutput], page_no: int,
                        braille_outputs: list | None = None) -> None:
    """'별책 참조' 안의 번호를 페이지 단위로 채운다 — `그림 20-4 참조` (원장 C-28).

    번호는 정답 관행 그대로 **묵자쪽-그 쪽에서의 순번**이다(009 본책 85건 실측:
    p0004 → `그림 4-1`·`그림 4-2`, p0020 → `그림 20-1`~`20-4`). 순번은 시각 요소끼리만
    세므로 요소 하나만 봐서는 못 만든다 — 읽기 순서로 정렬된 뒤인 여기서 채운다.
    llm_outputs를 **제자리에서** 고친다(호출부가 같은 객체를 계속 쓴다).

    ★ 번호는 **점자에도** 실어야 한다(2026-09-02). 종전에는 여기서 묵자 초안만 고쳤는데,
    점역은 이 함수보다 먼저 끝나 있어 점자 쪽 초안은 번호 없는 옛 문구(`구조도 참조`)로
    남았다 — 점역사 화면의 묵자 창과 점자 창이 서로 다른 말을 했다. 그래서 같은 자리의
    점자 초안을 다시 점역해 맞춘다(참조 안은 한 줄짜리라 비용이 없다).
    """
    from app.ai.braille.translator import translate_with_breaks
    from app.ai.llm.visual_drafts import VOLREF_OPTION, volume_ref_draft

    bo_by_id = {b.element_id: b for b in (braille_outputs or [])}
    ordinal = 0
    for o in llm_outputs:
        for i, d in enumerate(o.drafts or []):
            if d.option != VOLREF_OPTION:
                continue
            ordinal += 1
            nd = volume_ref_draft(d.type_label, f"{page_no}-{ordinal}")
            o.drafts[i] = nd
            bo = bo_by_id.get(o.element_id)
            for j, bd in enumerate(bo.drafts or []) if bo else ():
                if bd.option != VOLREF_OPTION:
                    continue
                lines, breaks = translate_with_breaks(nd.text)
                bo.drafts[j] = bd.model_copy(update={
                    "text": nd.text, "braille_lines": lines, "break_points": breaks})
                if bo.selected_idx == j:
                    bo.braille_lines = lines
                    bo.break_points = breaks
                break
            break


# ── 응답 조립 ────────────────────────────────────────────────────────────

def _selected_lines(bo, flat: dict) -> list[str]:
    """BrailleOutput → `contents` 직렬화 = **항목 1개짜리 통 문자열**.

    BE proto(braille_service.proto §TextElement.contents) 계약(2026-08-05 개정):
      · `contents`는 항목이 하나다 — 조판하지 않은 통 문자열
      · 32칸 자름·면 나눔·들여쓰기·가운데 정렬은 FE(화면)·BE(다운로드)가 한다
      · **구조적 빈 줄(제목 앞뒤 등)은 `\n`으로 여기 들어 있다** — 지침 규칙이라 우리 몫
      · `RuleTrail.line_no`는 0 고정, `col_*`가 이 문자열의 문자 오프셋이다

    빈 요소는 빈 배열을 유지한다.

    ※ 이력: 2026-07-28 '항목 = 초안' → 07-31 '항목 = 32칸 조판 줄'(BE proto) →
      08-05 '항목 = 통 문자열'(조판 가이드, AI finalize 폐기). 세 번 다 직렬화 경계만 바뀌었다.
    """
    if bo is None:
        return []
    fe = flat.get(bo.element_id)
    return [fe.text] if fe else []


def _selected_breaks(bo, flat: dict) -> list[int]:
    """`contents[0]` 안에서 줄을 바꿔도 되는 자리(#1240, `layout_braille._flat_breaks`). 모르면 빈 목록."""
    fe = flat.get(bo.element_id) if bo else None
    return list(fe.breaks) if fe else []


def _draft_breaks(bo, di: int, flat: dict) -> list[int]:
    """초안 `contents[0]` 의 끊을 자리. `_draft_contents` 가 flat 초안을 못 쓰는 자리(옛 꼴로 이어 붙임)는 모른다."""
    fe = flat.get(bo.element_id) if bo else None
    return list(fe.draft_breaks[di]) if fe and di < len(fe.draft_breaks) else []


# 초안 묵자에서 내부 태그를 벗긴다 (2026-08-06).
# `<!주>…<!/주>` 는 점역기가 마커 점형으로 바꾸는 **기계 표식**이지 사람이
# 읽을 글자가 아니다. FE는 이 값을 점자와 나란히 보여 주므로(와이어프레임) 태그가 그대로
# 노출되면 안 된다. 점자(`contents`)는 손대지 않는다 — 거기선 태그가 이미 마커로 바뀌었다.
_DRAFT_TAG_RE = re.compile(r"<!/?[^>]*>")


def _print_contents(o, mode: str, etype: str, hlevel: int) -> str:
    """`text_list.contents` 에 실을 묵자 — **들여쓰기 태그를 살려서** 담는다.

    ⚠ 2026-09-02 점검. 들여쓰기가 점자에만 실리고 묵자는 전 유형이 0칸이었다
    (점자 2칸 570줄·4칸 161줄 대 묵자 0칸 1,102줄). 시각 요소만의 문제가 아니었다.

    · 시각 요소는 `diagram_opt` 가 `corrected_text` 에서 `strip_indent_tags` 로 태그를
      떼어 담는다. 칸 정보가 `tn_text` 에만 남아 화면에서 사라졌다.
    · 본문·제목·수식은 애초에 묵자 쪽에 들여쓰기를 다는 자리가 없었다. 판정은
      `LayoutBraille._first_indent` 하나뿐이고 그건 점자 경로에서만 돈다.

    **공백이 아니라 태그로 싣는다**(대표 지시): 점역사 화면에 `<!2칸>` 이 보여야 하고,
    그 글을 그대로 mode b 로 되돌리면 점역기가 같은 들여쓰기를 다시 적용한다.
    공백으로 바꾸면 왕복할 때마다 공백이 쌓이고 태그가 사라진다.

    ⚠ **mode b 는 손대지 않는다.** 계약이 `contents == [원문 그 줄]` 이다 — BE 가 보낸
    원문을 그대로 돌려주는 자리라 우리가 무엇을 더하면 편집할 때마다 덧붙는다
    (`test_mode_b_contract`).
    """
    # 선택 초안이 있으면 **그 초안**이 이 요소의 묵자다 — 점자 창(`_selected_lines`)과 같은
    # 안을 본다. 시각 요소는 `tn_text` 가 이미 `drafts[selected_idx].text` 라 값이 안 바뀌고
    # (cartoon_opt:193 · image_opt:73 · chart_graph_opt:107 · diagram_opt:759),
    # **표만 달라진다**: 표의 `tn_text` 는 선택 초안이 아니라 **점역자 주**여서
    # (table_opt:683,720) 화면에 표 내용 대신 주석 한 줄만 나갔다(대표 지적 2026-09-08).
    # 점자 창에는 격자가 있는데 묵자 창에는 주석만 있어 두 창이 다른 말을 했다.
    _drafts, _idx = (o.drafts or []), (o.selected_idx or 0)
    if 0 <= _idx < len(_drafts):
        src = _drafts[_idx].text or ""
    else:
        src = o.tn_text or ""
        if "<!" not in src:
            src = o.corrected_text or ""
    if mode == "b" or not src.strip():
        return src
    if "<!" in src:
        return src                          # 태그가 이미 있다(시각 요소)
    first = _first_indent_for(o, etype, hlevel)
    if first <= 0:
        return src
    head, _, rest = src.partition("\n")
    tagged = f"<!{first}칸>{head}"
    return tagged + ("\n" + rest if rest else "")


def _first_indent_for(o, etype: str, hlevel: int) -> int:
    """묵자 첫 줄 들여쓰기 칸 수 — **점자 조판과 같은 판정**을 쓴다.

    규칙을 두 벌로 두면 화면과 점자가 갈린다. mode a 는 점역을 안 해 `flat` 이 없으므로
    `LayoutBraille._first_indent` 를 직접 부른다.
    """
    from app.ai.braille.layout_braille import LayoutBraille
    try:
        return LayoutBraille()._first_indent(o, etype, hlevel > 0, hlevel)
    except Exception:                      # noqa: BLE001 — 판정 실패는 0칸으로 둔다
        return 0


def _draft_print_text(text: str) -> str:
    """초안 묵자 — 내부 태그 제거. 줄바꿈·공백은 배치이므로 보존한다.

    ★ F10(대표 지적) — "시각 요소 설명에는 `<!2칸>` 이 제대로 반영되는데 밑에 추천 텍스트나
      default 로 보이던 텍스트들엔 다 그런 태깅이 없다."

      `<!2칸>` 은 **지우면 안 되는 태그**다. 위 docstring 이 "줄바꿈·공백은 배치이므로
      보존한다" 고 하는데 **들여쓰기가 바로 그 배치 정보**다. 2026-08-26 새벽에 줄별
      들여쓰기를 `line_indents` 필드에서 글 안 태그로 옮기면서(#256) 이 정규식의 표적이
      됐다. `tn_text` 는 값을 그대로 실어 태그가 남으니 시각 요소 설명에는 보이고 초안
      묵자에는 안 보였다 — 대표가 본 그대로다.

      그래서 **지우지 말고 실제 공백으로 바꾼다.** 칸 수는 `strip_indent_tags` 가 이미
      돌려주므로 그걸 먼저 태워 환산한 뒤 나머지 태그를 지운다.
    """
    from app.ai.braille.tag_names import strip_indent_tags
    from app.ai.braille.translator import normalize_print_draft

    body, indents = strip_indent_tags(text or "")
    if indents:
        body = "\n".join(" " * n + ln for n, ln in zip(indents, body.split("\n")))
    # ⚠ .strip() 을 그대로 쓰면 **첫 줄 들여쓰기를 먹는다**(`<!2칸>가나다` → '가나다').
    #   앞뒤 빈 줄만 떼고 각 줄의 오른쪽 공백만 다듬는다.
    out = _DRAFT_TAG_RE.sub("", body).strip("\n")
    # ★ 점자에 깨진 묵자가 들어가면 안 된다(대표 지시 2026-08-26). 점자 경로만 정화하고
    #   여기를 빼먹어서 초안 묵자에 PUA 글자가 그대로 떴다. 남는 것은 로그로 드러낸다.
    out = normalize_print_draft(out, where="draft_print")
    return "\n".join(ln.rstrip() for ln in out.split("\n"))


def _draft_contents(bo, d, di: int, flat: dict) -> list[str]:
    """초안 하나의 `contents`. 선택 초안과 **같은 구조적 빈 줄·들여쓰기**를 단다.

    피커가 초안을 바꿔도 앞뒤 빈 줄과 들여쓰기가 달라지면 안 된다 — 둘 다 초안 내용이
    아니라 요소의 위치(제목인가 표인가)가 정하는 값이기 때문이다.
    `flatten_elements`가 초안까지 같은 규칙으로 미리 만들어 둔다.
    """
    fe = flat.get(bo.element_id) if bo else None
    if fe is None:
        return ["\n".join(d.braille_lines)] if d.braille_lines else []
    if di < len(fe.draft_texts):
        return [fe.draft_texts[di]]
    return [fe.prefix + "\n".join(d.braille_lines) + fe.suffix]


def _line_order(mode: str, order_map: dict, element_id, idx: int) -> int:
    """응답 `order`.

    mode a·c — 나열 순서(1..N). 종전과 같다. **바꾸지 않는다** — BE가 이 값이 빈틈없이
      이어진다고 보고 쓸 수 있어, 여기서 의미를 바꾸면 조용한 계약 변경이 된다.
    mode b — **원본 줄 번호**(2026-08-06). 빈 줄에서 번호가 건너뛰므로 BE가 원문에서
      빈 줄이 어디였는지 알 수 있다. `text_list`와 `braille_text_list`가 같은 값을 써야
      같은 `id`끼리 짝이 맞는다.
    """
    if mode == "b":
        return int(order_map.get(element_id) or idx + 1)
    return idx + 1


_ENV_CAPTION = object()   # _build_response 기본값 — 경계가 없는 경로(모드 b)는 요청 때 env 로 정한다


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
    flat: Optional[dict] = None,
    caption_disabled: Optional[bool] = _ENV_CAPTION,
    lost_text: Optional[dict] = None,
    misread: Optional[dict] = None,
    table_fixed: Optional[dict] = None,
    lost_restored: Optional[dict] = None,
) -> dict:
    elem_by_id = {e.element_id: e for e in layout_result.elements}
    braille_by_id = {b.element_id: b for b in braille_outputs}
    ext_by_id = {e.element_id: e for e in extracted}
    flat = flat or {}

    def _layout_trail(eid) -> list[dict]:
        """읽기순서를 옮긴 근거(#1305) — 요소 전체(line_no=-1) 규정. 쪽 상태는 안 바꾼다(R 플래그 아님)."""
        from app.ai.braille.regulations import make_rule
        ext = ext_by_id.get(eid)
        return [make_rule(r, tag="reading_order").model_dump() for r in (ext.layout_rules if ext else [])]
    # 32칸 초과는 더 이상 우리가 재는 값이 아니다 — 조판을 FE·BE가 하므로 초과 여부도
    # 거기서 정해진다. finalize 폐기로 C6 판정의 이동처가 사라져 0으로 고정한다.
    line_overflow_rate = 0.0

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
    # 번호 채우기는 조판 앞에서 이미 끝났다(위 _number_volume_refs 주석 참조).

    # PART 11: 품질 판정 — C/R 감지 후 status 결정 (COMPLETED|NEEDS_REVIEW|BLOCKED)
    from app.ai.quality.quality_checker import QualityChecker
    # 요소가 하나도 없을 때만 묵자를 다시 본다 — 빈 지면이면 C1(BLOCKED)이 아니다(T702).
    blank_page = False
    if not extracted and not llm_outputs and task.pdf_data:
        from app.ai.preprocessor.pdf_analyzer import page_is_blank
        blank_page = page_is_blank(task.pdf_data, task.page_no)
    quality_report = QualityChecker().check(
        page_id,
        layout_result=layout_result,
        extracted=extracted,
        llm_outputs=llm_outputs,
        braille_outputs=braille_outputs,
        line_overflow_rate=line_overflow_rate,
        blank_page=blank_page,
        # 응답에 실리는 통 문자열을 넘긴다 — 검사기가 조판본 대신 이걸 본다(C5 오탐).
        flat_text={str(k): fe.text for k, fe in (flat or {}).items()},
        lost_text=lost_text,
        misread=misread,
        table_fixed=table_fixed,
        lost_restored=lost_restored,
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
            # 캡셔닝을 끄고 뜬 경계로 낸 산출물이면 박아 둔다 — 이걸로 시각 축을 재면 안 된다.
            # 값은 경계 meta 에서 온다(True · False · 모름=None). 경계가 없는 모드 b 는 요청 때 env.
            "caption_disabled": (process_env("SEMOJUM_NO_CAPTION") == "1"
                                 if caption_disabled is _ENV_CAPTION else caption_disabled),
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
        # 좌표가 통째로 죽은 쪽을 응답에 알린다(R16). 고급 점역 곁의 MinerU 가 실패하면
        # bbox 가 전부 (0,0,0,0) 으로 나가는데 `image_width`·`image_height` 는 정상값이
        # 그대로 실려, 소비자가 좌표가 무의미하다는 것을 알 방법이 응답 안에 없었다 —
        # FE 는 모든 상자를 왼쪽 위 한 점에 그린다(실측 88요소 전부 0, 경고는 로그에만).
        # ⚠ 목록을 비우지는 않는다 — `id` 로 요소를 짝짓는 계약이 깨진다. 표시만 붙인다.
        if response["bounding_box_list"] and not any(
                _valid_bbox(e) for e in layout_result.elements):
            response["quality_report"].setdefault("review_flags", []).append({
                "type": "R16", "element_id": "page",
                "message": f"요소 {len(layout_result.elements)}개의 bbox 가 전부 "
                           "(0,0,0,0) 이다. 좌표가 없으니 하이라이트를 쓰지 말 것",
            })
    # 원문 목록은 mode b에도 싣는다 (2026-08-06). BE가 원문↔점역을 같은 `id`로 짝지어
    # FE에 줄 단위로 흘려보낸다 — 종전에는 mode b에서 이게 비어 있어 짝짓기가 불가능했다.
    if task.mode in ("a", "b", "c"):
        response["text_list"] = [
            {
                "id": str(o.element_id),
                "type": elem_by_id.get(o.element_id, _DUMMY_ELEM).type,
                "order": _line_order(task.mode, _order_of, o.element_id, i),
                "heading_level": getattr(
                    elem_by_id.get(o.element_id), "heading_level", None
                ) or 0,
                "ocr_confidence": _get_ocr_confidence(o.element_id, extracted),
                "tn_text": o.tn_text or "",
                "is_blocked": "[처리 불가" in o.corrected_text,
                "render_mode": o.render_mode,
                # ★ 들여쓰기를 실제 공백으로 실어 보낸다(2026-09-02 대표 지적).
                #   SPEC-INTERFACE §1-0: "조판 규칙(빈 줄·들여쓰기·가운데 정렬)은 AI 가
                #   `contents` 안에 넣어 보낸다." 그런데 시각 요소의 줄별 들여쓰기는
                #   `<!2칸>` 태그로 **`tn_text` 에만** 실려 있었다 — `corrected_text` 를
                #   그대로 담던 이 자리에는 칸 정보가 하나도 없었다.
                #   mode b 로 넘기면 들여쓰기가 살아나는 것도 그래서다(점역기가 태그를 본다).
                #   `_draft_print_text` 가 초안에 쓰는 것과 **같은 환산**을 쓴다 —
                #   태그를 지우지 않고 공백으로 바꾼다.
                "contents": [_print_contents(
                    o, task.mode,
                    elem_by_id.get(o.element_id, _DUMMY_ELEM).type,
                    getattr(elem_by_id.get(o.element_id), "heading_level", None) or 0)],
                "rule_trail": [r.model_dump() for r in o.rule_trail] + _layout_trail(o.element_id),
                # 시각 요소 대체 초안 — **묵자만** 싣는다 (2026-08-06).
                # mode a는 점역을 하지 않으므로(include_braille=False) 점자가 없다.
                # mode c는 여기 묵자와 `braille_text_list`의 묵자+점자를 함께 받는다.
                "drafts": [
                    {"text": _draft_print_text(d.text), "label": d.label,
                     # 태그가 살아 있는 묵자 — 안마다 다르다(2026-09-02 대표 지적).
                     # 종전에는 요소 하나의 `tn_text` 뿐이라 처음 고른 안의 것만 남았고,
                     # 점역사가 안을 바꿔도 화면 위칸이 안 바뀌었다.
                     "tn_text": d.text or "",
                     "contents": []}
                    for d in (o.drafts or [])
                ],
                "selected_idx": o.selected_idx,
                **_meta_fields(o.element_id),
            }
            for i, o in enumerate(llm_outputs)
        ]

    if task.mode in ("b", "c") and llm_outputs:
        response["braille_text_list"] = [
            {
                "id": str(o.element_id),
                "type": elem_by_id.get(o.element_id, _DUMMY_ELEM).type,
                "order": _line_order(task.mode, _order_of, o.element_id, i),
                "heading_level": getattr(
                    elem_by_id.get(o.element_id), "heading_level", None
                ) or 0,
                "ocr_confidence": _get_ocr_confidence(o.element_id, extracted),
                "tn_text": o.tn_text or "",
                # opt(텍스트)뿐 아니라 braille 단계 실패(요소 격리 placeholder)도 블록으로 집계.
                "is_blocked": (
                    "[처리 불가" in o.corrected_text
                    or is_blocked_braille(braille_by_id[o.element_id].braille_lines
                                          if o.element_id in braille_by_id else [])
                ),
                "render_mode": o.render_mode,
                "contents": _selected_lines(
                    braille_by_id.get(o.element_id), flat
                ),
                "breaks": _selected_breaks(braille_by_id.get(o.element_id), flat),
                # 좌표계가 통 문자열이라 flat의 것을 쓴다(layout이 재매핑한 조판 좌표 아님).
                "rule_trail": [
                    r.model_dump()
                    for r in (
                        flat[o.element_id].trail
                        if o.element_id in flat
                        else (braille_by_id[o.element_id].rule_trail
                              if o.element_id in braille_by_id else o.rule_trail)
                    )
                ] + _layout_trail(o.element_id),
                "selected_idx": (
                    braille_by_id[o.element_id].selected_idx
                    if o.element_id in braille_by_id else 0
                ),
                "drafts": [
                    {
                        # BE proto §Draft: 초안마다 자기 점자 줄을 싣는다.
                        # 선택 초안 것은 상위 contents와 같은 값이 되지만(중복),
                        # 피커가 초안별 점자를 바로 꺼내 쓸 수 있어야 한다.
                        "text": _draft_print_text(d.text),
                        "label": d.label,
                        "tn_text": d.text or "",
                        "contents": _draft_contents(
                            braille_by_id.get(o.element_id), d, di, flat
                        ),
                        "breaks": _draft_breaks(braille_by_id.get(o.element_id), di, flat),
                    }
                    for di, d in enumerate(
                        braille_by_id[o.element_id].drafts
                        if o.element_id in braille_by_id else []
                    )
                ],
                **_meta_fields(o.element_id),
            }
            for i, o in enumerate(llm_outputs)
            # ★ 쪽 번호(page_number)는 점자 목록에서 뺀다(#1262). FE · BE · 앱은 이 목록을 종류를
            #   가리지 않고 본문에 싣고 원본 쪽 번호는 자기 쪽 순번으로 매긴다. 그래서 이 요소가
            #   본문에 홀로 선 줄로 찍혔다(dev · val 1,714/1,746쪽, 정답 본문 0쪽).
            #   `text_list` · `bounding_box_list` 에는 남긴다. result.txt 페이지행은 layout 이 따로 본다.
            if elem_by_id.get(o.element_id, _DUMMY_ELEM).type != "page_number"
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
        # B-09(원장) — 폰트 사설영역(PUA) 글리프가 점역에서 공백으로 사라진다. 어느 아이콘이
        # 어느 말인지 모르는 것은 추측해 옮기지 않되(pm 결재 2026-08-22), **조용히 지우지도
        # 않는다**: 글리프 코드와 횟수를 남기고 그 쪽을 NEEDS_REVIEW로 세워 점역사가 원본을
        # 보게 한다. 실측 근거 — print 3,182쪽 중 339쪽(10.7%)에 PUA가 있고 1,967회다.
        from app.ai.braille.translator import dropped_pua as _dropped_pua
        _pua = _dropped_pua("\n".join(
            c for e in (response.get("text_list") or []) for c in (e.get("contents") or [])))
        if _pua and "quality_report" in response:
            _codes = ", ".join(f"U+{ord(ch):04X}×{n}" for ch, n in _pua.most_common())
            response["quality_report"].setdefault("review_flags", []).append(
                {"type": "R15", "element_id": "page",
                 "message": f"글꼴 사설영역 글리프 {sum(_pua.values())}자가 점역에서 빠졌다 — 원본 확인 필요 ({_codes})"})
            if response.get("status") == "COMPLETED":
                response["status"] = "NEEDS_REVIEW"
                response["quality_report"]["status"] = "NEEDS_REVIEW"
        # 기호표에도 braillify 에도 없는 기호가 조용히 사라진다(`가▶나` → 가나, T25).
        # PUA(R15)와 같은 원칙이다 — 지우되 세고, 그 쪽을 NEEDS_REVIEW 로 세운다.
        from app.ai.braille.translator import dropped_symbols as _dropped_symbols
        _sym = _dropped_symbols("\n".join(
            c for e in (response.get("text_list") or []) for c in (e.get("contents") or [])))
        if _sym and "quality_report" in response:
            _chars = ", ".join(f"{ch}(U+{ord(ch):04X})×{n}" for ch, n in _sym.most_common())
            response["quality_report"].setdefault("review_flags", []).append(
                {"type": "R17", "element_id": "page",
                 "message": f"점자 기호가 없는 기호 {sum(_sym.values())}자가 점역에서 빠졌다 — 원본 확인 필요 ({_chars})"})
            if response.get("status") == "COMPLETED":
                response["status"] = "NEEDS_REVIEW"
                response["quality_report"]["status"] = "NEEDS_REVIEW"
        # 규정(제19~25항)에 점형이 없는 옛한글 음절도 같은 원칙이다(#1098) — 음절 하나만 빠지고 나머지는
        # 적히지만, 빠진 자리는 점역사가 원문과 맞대지 않으면 못 찾는다. 무엇으로 적을지는 자문 대상이다.
        from app.ai.braille.translator import dropped_old_jamo as _dropped_old_jamo
        _old = _dropped_old_jamo("\n".join(
            c for e in (response.get("text_list") or []) for c in (e.get("contents") or [])))
        if _old and "quality_report" in response:
            _syls = ", ".join(f"{s}×{n}" for s, n in _old.most_common())
            response["quality_report"].setdefault("review_flags", []).append(
                {"type": "R18", "element_id": "page",
                 "message": f"규정에 점형이 없는 옛한글 음절 {sum(_old.values())}개가 점역에서 빠졌다 — 원본 확인 필요 ({_syls})"})
            if response.get("status") == "COMPLETED":
                response["status"] = "NEEDS_REVIEW"
                response["quality_report"]["status"] = "NEEDS_REVIEW"
    except Exception as exc:  # noqa: BLE001 — 등급 실패가 점역 결과를 막지 않는다
        logger.warning("검수 등급 산출 실패(무시): %s", exc)

    # ── 관문 기록 (재구조화 §2-2) ─────────────────────────────────────────
    # G4 는 **읽기 전용**이다. 최종 셀열에서 허용 문자(점자 블록·공백·개행) 밖이 몇 자
    # 남았는지 세기만 하고 고치지 않는다 — 여기서 고치면 이 자리가 새 결함의 출처가 된다.
    # 정방향 이물질 자(`temp/l8/fwd_artifact.py`)와 같은 잣대라 그 수치를 제품 경로에서도
    # 확인할 수 있다(설계 §5 12: 100% 를 어느 스크립트가 쟀는지 못 찾았다).
    # ⚠ `is_blocked` 요소는 뺀다. `[처리 불가: …]` 는 **빈 결과 금지**(불변 규칙 1)가 일부러
    #   남기는 자리표시고 `is_blocked` 가 이미 그 사실을 알린다. 세면 옛 코퍼스 1,131쪽 중
    #   51쪽(4.51%)이 G4 로 뜨는데 **전부 그 자리표시**였다(2026-09-08 실측). 같은 사실을 두 번
    #   말하면 진짜 신호(마크업이 셀로 샌 자리)가 그 안에 묻힌다.
    try:
        _foreign = gates.count_foreign_cells(
            c for e in (response.get("braille_text_list") or [])
            if not e.get("is_blocked") for c in (e.get("contents") or []))
        if _foreign:
            gates.gate_hit("G4", "점자밖문자", sum(_foreign.values()))
            logger.warning("G4 셀열에 점자 밖 문자 %d자 (%s)", sum(_foreign.values()),
                           ", ".join(f"U+{ord(ch):04X}×{n}" for ch, n in _foreign.most_common(6)))
        _gflags = gates.gate_flags()
        if _gflags and "quality_report" in response:
            response["quality_report"].setdefault("review_flags", []).extend(_gflags)
    except Exception as exc:  # noqa: BLE001 — 기록 한 줄이 쪽을 죽이면 안 된다
        logger.warning("관문 기록 실패(무시): %s", exc)

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

_last_job_id: str | None = None


async def run(task: PageTask) -> dict:
    """파이프라인 진입점. 300초 하드 타임아웃 강제."""
    start_request()   # 요청 단위 API 카운터 초기화
    # LLM 캐시 격리 열쇠(재구조화 3-e · 대표 결재 "(B) 고객별 격리").
    # 요청에 고객 식별자는 없다 — `job_id` 가 지금 쓸 수 있는 가장 고운 단위이고,
    # job 격리는 고객 격리보다 좁으므로 결재를 어기지 않는다(고객 사이엔 안 샌다).
    llm_cache.set_scope(task.job_id)
    # 관문 계수기(재구조화 §2-2)는 **쪽마다** 새로 판다. 여러 쪽이 한 프로세스에서 겹쳐
    # 도는데 전역으로 세면 옆 쪽 발동이 이 쪽 review_flags 에 얹힌다(gates 도크스트링).
    gates.gate_reset()
    _ITEM_CODE_FORM_JOB.set((task.item_code_form or "").upper())
    # 한글 · 영어 정자(#1235) — 요청 낱값을 쪽 단위 문맥 값으로 놓는다. 끈 값도 늘 놓는다: 한 문맥에서
    #   쪽을 이어 돌리는 러너가 앞 쪽 값을 물려받지 않게. `run_braille` · `to_thread` 가 문맥을 복사해 점역 풀까지 간다.
    _KOREAN_GRADE1.set(bool(task.korean_grade1))
    _ENGLISH_GRADE1.set(bool(task.english_grade1))
    _CHOICES_ONE_PER_LINE.set(bool(task.choices_one_per_line))   # 조판(flatten · layout)도 `run_braille` 로 같은 문맥에서 돈다
    # 판 지문(0-c) — 점역사 피드백이 며칠 뒤에 올 때 어느 커밋·어느 프롬프트였는지 되짚는 줄.
    # ★ health_check 는 model_manager 를 거쳐 torch 를 끌고 온다. 모듈 최상단에서 부르면
    #   pipeline import 그래프가 바뀌고, torch 없는 빠른 게이트 레인이 통째로 깨진다.
    #   여기서 늦게 부르고, 그 레인에서는 지문 줄만 건너뛴다(제품 경로엔 torch 가 늘 있다).
    try:
        from app.core.health_check import build_stamp
    except ImportError:
        pass
    else:
        logger.info("판 %s job=%s page=%d", build_stamp(), task.job_id, task.page_no)
    # 캡셔닝 잠금(`result_builder._caption_fatal`)은 **한 job 안에서** 같은 설정성 오류를
    # 요소 수만큼 다시 맞지 않으려고 건다. 그런데 푸는 자리가 테스트밖에 없어, 키가 잠깐
    # 흔들려 한 번 잠기면 **그 뒤 다른 job 까지** 서버를 재시작할 때까지 통째로 '생략'으로
    # 나갔다. job 이 바뀌면 푼다 — 잠금은 job 안에서 그대로 산다.
    # ※ 여러 job 이 페이지 단위로 겹쳐 들어오면 이 값이 오가며 쪽마다 한 번씩 풀린다.
    #   그래도 한 쪽(요소 200개) 안에서는 잠금이 살아 있으므로 원래 목적은 지켜진다.
    # ※ result_builder 는 openai 를 끌고 온다 — 그게 없는 빠른 게이트 레인에서는 건너뛴다.
    global _last_job_id
    if task.job_id != _last_job_id:
        _last_job_id = task.job_id
        try:
            from app.ai.builder.result_builder import reset_caption_fatal
        except ImportError:
            pass
        else:
            reset_caption_fatal()
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
        logger.info(llm_counter_line())   # 재구조화 3-a — 끄기 팔 확인은 이 줄의 call=0
        # 요소별 검수 신호는 **쪽 단위 요약 한 줄**로만 남긴다(#788). BE·FE 가 안 읽기로
        # 했으므로 우리가 여기서 본다 — 요소마다 찍으면 쪽당 수십 줄이라 로그가 못 쓰게 된다.
        logger.info(review_signal_line(result.get("braille_text_list") or []))
        # 캡셔닝이 꺼진 채 **멀쩡한 척** 나가는 응답을 우리가 알아야 한다(#788).
        # 이 산출물로 시각 축을 재면 안 된다 — 설명이 통째로 빠져 있다.
        if (result.get("processing_meta") or {}).get("caption_disabled"):
            logger.warning("⚠ 캡셔닝 꺼짐(SEMOJUM_NO_CAPTION=1) — 시각자료 설명 없는 "
                           "산출물이다. 시각 축 측정 금지 (job=%s page=%d)",
                           task.job_id, task.page_no)
        for _line in breakdown_lines():   # 파트별 LLM 사용 내역(디버깅·비용 추적)
            logger.info(_line)
        # 원가는 성공·타임아웃·예외 **셋 다** 싣는다 — 막혔어도 돈은 나갔다.
        result["usage"] = {**usage_report(), "layout_type": _page_layout_type(result)}
        _record_metrics(result, elapsed_ms)
        return result

    except asyncio.TimeoutError:
        elapsed_ms = int((time.monotonic() - start) * 1000)
        logger.warning("⛔ BLOCKED(타임아웃) %.1fs · API %s  (job=%s page=%d)",
                       elapsed_ms / 1000, api_summary(), task.job_id, task.page_no)
        logger.info(llm_counter_line())
        result = _build_timeout_response(task, elapsed_ms)
        # 원가는 성공·타임아웃·예외 **셋 다** 싣는다 — 막혔어도 돈은 나갔다.
        result["usage"] = {**usage_report(), "layout_type": _page_layout_type(result)}
        _record_metrics(result, elapsed_ms)
        return result

    except Exception as exc:
        elapsed_ms = int((time.monotonic() - start) * 1000)
        logger.exception("⛔ BLOCKED(예외) %.1fs job=%s page=%d: %s",
                         elapsed_ms / 1000, task.job_id, task.page_no, exc)
        result = _build_exception_response(task, elapsed_ms, exc)
        # 원가는 성공·타임아웃·예외 **셋 다** 싣는다 — 막혔어도 돈은 나갔다.
        result["usage"] = {**usage_report(), "layout_type": _page_layout_type(result)}
        _record_metrics(result, elapsed_ms)
        return result


def _record_metrics(result: dict, elapsed_ms: int) -> None:
    """PART 11 후반: 페이지 메트릭 기록. 실패해도 응답에 영향 금지."""
    try:
        from app.ai.quality.metrics_collector import MetricsCollector
        MetricsCollector().record(result, elapsed_ms=elapsed_ms)
    except Exception as exc:
        logger.warning("메트릭 수집 실패(무시): %s", exc)
