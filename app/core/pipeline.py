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
from app.core.limits import run_braille
from app.schemas.task import PageTask
from app.utils.logger import get_logger
from app.utils.req_log import (
    api_summary,
    breakdown_lines,
    elapsed,
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
    re.compile(r"^(?:ⓒ|©|Copyright\b)", re.IGNORECASE),  # 저작권 고지
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
_EXTRACTION_REFUSAL_RES = (
    # '읽을 수 있는 글자가 없다' 계열
    re.compile(r"\bno\s+(?:discernible|legible|readable|recognizable|visible)\s+"
               r"(?:text|characters|words|content)", re.IGNORECASE),
    re.compile(r"\bno\s+text\s+(?:is\s+)?(?:present|visible|detected|found)\b", re.IGNORECASE),
    # 'OCR 결과가 없다/빈 문자열이다' 계열 — 추출 작업 자체를 자기언급
    re.compile(r"\bno\s+OCR\s+output\b", re.IGNORECASE),
    re.compile(r"\bOCR\s+output\s+(?:is|would\s+be|should\s+be)\s+(?:an?\s+)?empty",
               re.IGNORECASE),
    re.compile(r"\b(?:cannot|can(?:'|no)t|unable\s+to)\s+(?:be\s+)?"
               r"(?:generate|generated|extract|extracted|perform|performed|produce|produced)\b"
               r"[^.]{0,40}\bOCR\b", re.IGNORECASE),
    # 모델 사과·자기소개 계열(문두 한정)
    re.compile(r"^\s*(?:I'?m\s+sorry|I\s+am\s+sorry|As\s+an\s+AI\b)", re.IGNORECASE),
    # ★ 한국어 짝(2026-09-03). 위 패턴이 전부 영어라, 한국어로 답하는 모델이 쓴
    #   해설문은 한 줄도 안 걸려 초안에 그대로 실렸다(FE QA S-7).
    re.compile(r"(?:읽을\s*수\s*있는|판독\s*가능한|인식(?:할\s*수\s*있는|되는))\s*"
               r"(?:글자|문자|텍스트|내용)[가이]?\s*(?:없|보이지\s*않)"),
    re.compile(r"(?:텍스트|글자|내용)[가이]?\s*(?:전혀\s*)?(?:없습니다|없음|보이지\s*않습니다)"),
    re.compile(r"(?:추출|판독|인식)(?:할\s*수\s*(?:없|가\s*없)|이\s*(?:불가|되지\s*않))"),
    re.compile(r"^\s*(?:죄송(?:합니다|하지만)|저는\s*(?:AI|인공지능))"),
    re.compile(r"^\s*이\s*(?:이미지|페이지|지면)에(?:는|서는)?\s*[^.\n]{0,20}"
               r"(?:없습니다|없음|보이지\s*않습니다)"),
)


def _is_extraction_refusal(content: str) -> bool:
    """요소 content가 '추출 모델이 못 읽었다고 쓴 해설문'인가(본문 텍스트가 아님)."""
    c = re.sub(r"\s+", " ", _HF_TAG_RE.sub("", content or "")).strip()
    if not c:
        return False
    return any(p.search(c) for p in _EXTRACTION_REFUSAL_RES)


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

async def _gather_chains(coros):
    """체인들을 모아 실행. 요소 격리(불변 규칙 3)를 위해 예외를 값으로 돌려준다.

    ★ `CHAIN_SEQUENTIAL=1`이면 gather 대신 **순차 await**로 돈다(2026-08-21).
      진단 전용 스위치다 — 같은 입력에 산출이 갈리는 쪽이 있는데(NULL 두 벌 1/709,
      실험 두 벌 34/709), 그 원인이 체인 동시 실행의 공유 상태인지 가리려면 순차 조건이
      필요하다. 순차에서도 갈리면 동시성이 아니고, 안 갈리면 동시성이 원인이다.
      기본은 꺼져 있고, 켜면 느려지므로 운영에서는 쓰지 않는다.
    """
    if os.environ.get("CHAIN_SEQUENTIAL") == "1":
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


def _graft_text(mnr_els: list[dict], llm_els: list[dict]) -> int:
    """**MinerU 요소를 기준으로 두고** LLM 이 읽은 글자만 갈아 끼운다.

    고급 점역의 몫은 "MinerU 가 한자로 깨뜨리는 글자를 제대로 읽는 것"이지 지면 구조를
    다시 잡는 것이 아니다(2026-09-03 대표 지시). 그래서 **레이아웃·좌표·읽기순서·유형·
    캡션 연결은 MinerU 것을 그대로 쓰고** 글자만 바꾼다. 이렇게 해야 bbox 가 보통 경로와
    똑같이 맞는다.

    ⚠ 종전에는 반대로 했다 — LLM 요소 목록을 기준으로 두고 좌표만 얹었다. 그러면 LLM 이
      쪼갠 단위와 MinerU 레이아웃이 어긋나 **FE 하이라이트가 글자와 안 맞았다.**

    짝짓기는 정규화한 앞 80자의 유사도(0.45 이상)다. 한 LLM 요소는 한 번만 쓴다.
    짝을 못 찾은 MinerU 요소는 **원래 글자를 지킨다** — 비우면 내용이 사라진다.
    """
    import difflib
    import re as _re

    def norm(t: str) -> str:
        return _re.sub(r"[\s\W_]+", "", (t or ""))[:80]

    used: set[int] = set()
    hit = 0
    for el in mnr_els:
        a = norm(el.get("content"))
        if len(a) < 4:
            continue
        best, best_r = -1, 0.45
        for j, m in enumerate(llm_els):
            if j in used:
                continue
            r = difflib.SequenceMatcher(None, a, norm(m.get("content"))).ratio()
            if r > best_r:
                best, best_r = j, r
        if best >= 0:
            txt = llm_els[best].get("content") or ""
            if txt.strip():
                el["content"] = txt
                used.add(best)
                hit += 1
    return hit


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
    # ZERO 티어(텍스트 레이어가 멀쩡한 쪽)는 그대로 둔다. 거기서는 원본 글자를 그대로
    # 옮기는 편이 정확하고, 고급 점역이 노리는 것은 깨진 지면이다.
    advanced_used = ""
    mnr: tuple[list[dict], int, int, str] | None = None
    if task.advanced_ai and doc_meta.routing_tier != "ZERO":
        from app.ai.parser import opus_fallback as _llm
        if _llm.advanced_available():
            img = _page_image_path(task)
            if img:
                # ★ MinerU 를 **끄지 않고 같이 돌린다**(2026-09-03 대표 지시). 고급 점역은
                #   내용을 잘 읽지만 좌표를 못 준다 — 종전에는 이 경로에서 bbox 가 통째로
                #   (0,0,0,0) 이라 FE 하이라이트가 아예 안 떴다. LLM 은 API·MinerU 는 GPU 라
                #   서로 안 막으므로 나란히 돌리면 벽시계는 둘 중 긴 쪽이다.
                llm_job = asyncio.create_task(
                    asyncio.to_thread(_llm.extract_advanced, str(img))
                )
                mnr_job = asyncio.create_task(_extract_via_models(task, doc_meta))
                els, used = await llm_job
                try:
                    mnr = await mnr_job
                except Exception as exc:  # noqa: BLE001 — 좌표가 없을 뿐 내용은 살린다
                    logger.warning("고급 점역 곁의 MinerU 실패(좌표 없이 진행): %s", exc)
                    mnr = None
                if els:
                    advanced_used = used
                    logger.info("고급 점역 추출 채택: %s %d요소 (page=%d)",
                                used, len(els), task.page_no)
        if not advanced_used:
            logger.warning("고급 점역 추출 실패 — MinerU 로 되돌린다 (page=%d)", task.page_no)

    if advanced_used:
        method = "LLM_VISION"
        if mnr and mnr[0]:
            # ★ **MinerU 가 기준이다**(2026-09-03 대표 지시). 고급 점역의 몫은 MinerU 가
            #   한자로 깨뜨리는 글자를 제대로 읽는 것이지 지면 구조를 다시 잡는 것이
            #   아니다. 레이아웃·좌표·읽기순서·유형·캡션 연결을 MinerU 것으로 두고
            #   글자만 갈아 끼우면 bbox 가 보통 경로와 **똑같이** 맞는다.
            elements = mnr[0]
            n = _graft_text(elements, els)
            image_width, image_height, bbox_space = mnr[1], mnr[2], mnr[3]
            logger.info("고급 점역 글자 이식 %d/%d 요소 (page=%d)",
                        n, len(elements), task.page_no)
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
        elements = _blocks_with_bbox(blocks) or _blocks_from_text(pdf_text)
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
        if n := tag_boxed_elements(elements, rects, _page_w):
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
                elements.extend(add)
                logger.info("그림 회수 %d개 (page=%d)", len(add), task.page_no)

    # QA용 쪽 이미지 보관(기본 off — KEEP_PAGE_IMAGE=1로만 켠다, 대표 결정 2026-08-07).
    # 평소에는 처리 후 원본을 안 남긴다(저작권·디스크). QA 기간에만 켜면 bbox·읽기순서·
    # 표 오분류를 **쪽 위에 겹쳐 눈으로** 볼 수 있다. 렌더는 Opus 폴백과 같은 자리를 쓴다.
    if os.environ.get("KEEP_PAGE_IMAGE") == "1":
        _page_image_path(task)

    # Opus 비전 폴백(D-05, 기본 off — OPUS_EXTRACT_FALLBACK=1 opt-in): 추출이 빈약한
    # 페이지만 claude-opus-4-8이 직접 읽는다. 실측상 저품질 페이지에서만 유효(3~4배),
    # 중간 품질은 득실 반반이라 빈약 신호(요소 수·글자수)일 때만 트리거.
    from app.ai.parser import opus_fallback
    if (not advanced_used) and opus_fallback.enabled() and opus_fallback.is_meager(elements):
        img = _page_image_path(task)
        if img:
            better = await asyncio.to_thread(opus_fallback.extract, str(img))
            if better and not opus_fallback.is_meager(better):
                logger.warning("Opus 추출 폴백 채택: %d→%d요소 (page=%d)",
                               len(elements), len(better), task.page_no)
                elements, method = better, "OPUS_VISION"

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
# 기하 정렬을 걸 수 있는 최대 열 수. 교재 쪽은 많아야 3단이다. 이보다 많이 잡히면
# 열 모형이 안 맞는 쪽(회전 페이지·비정형 글상자)이라 원순서를 그대로 둔다.
# 실측(2026-08-07, dev2027 189 · devall 172 · valall 868쪽, 요소단위 τ. 열 우선 정렬 적용 후):
#   상한 없음 0.909/0.805/0.826 → ≤3열 0.909/0.908/0.888. 4~8열로 올려도 값이 같다(평탄).
_MAX_COLS = 3


def _valid_bbox(b: BBoxItem) -> bool:
    return b.bbox[2] > b.bbox[0] and b.bbox[3] > b.bbox[1]


def _reorder_by_geometry(items: list[BBoxItem], rotation: int = 0) -> None:
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
        _reorder_columns(items, rotation)


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


def _reorder_columns(items: list[BBoxItem], rotation: int = 0) -> None:
    """H3: 열 클러스터링 읽기순서.

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

    # 1-b) ★ 열이 너무 많으면 손대지 않는다. 교재 쪽은 많아야 3단인데 x-겹침 열이 10~30개로
    #   나오는 쪽이 실제로 있다 — 270° 회전 페이지(외국어 영역)와 비정형 글상자 배치다.
    #   그런 쪽에서 기하 정렬을 걸면 읽기순서가 통째로 뒤집힌다(실측 τ 1.00 → −1.00,
    #   valall 47쪽 평균 0.677 → −0.442). 모형이 안 맞는 쪽은 추출기 순서를 믿는다.
    if len(clusters) > _MAX_COLS:
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
        return
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
        run = best = 1
        for _a, _c in zip(ranks, ranks[1:]):
            run = run + 1 if _c == _a + 1 else 1
            best = max(best, run)
        contiguous = best == len(ranks) or (best >= 3 and best >= len(ranks) - 1)
        narrow = (max(b.bbox[2] for b in cl) - min(b.bbox[0] for b in cl)) \
            <= 0.5 * (hull1 - hull0)
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
    main = sorted(main, key=_ykey) if (viol > 1 or hard) else by_mineru

    # 5) 새 본문 순서 = main → 이동 열(x0 순, 각 y-정렬). 비본문은 원 슬롯 유지.
    deferred.sort(key=lambda cl: min(b.bbox[0] for b in cl))
    new_body = main + [b for cl in deferred for b in sorted(cl, key=lambda x: x.bbox[1])]
    body_ids = {id(b) for b in body}
    it = iter(new_body)
    seq = [next(it) if id(b) in body_ids else b
           for b in sorted(items, key=lambda b: b.reading_order)]
    for k, b in enumerate(seq, start=1):
        b.reading_order = k


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
        for grp in groups:
            child = dict(el)
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
_BOX_TITLE_PROMOTABLE = frozenset({
    "보기", "개념 체크", "수능 기본 문제", "수능 실전 문제",
    "자료 플러스", "개념 플러스", "기출 플러스", "학습의 길잡이", "학습 활동",
})
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


# 낱말 갈림을 볼 때 양쪽 끝이 진짜 글자인지 확인한다 — 태그·기호 줄을 거른다.
_WORD_EDGE_RE = re.compile(r"[0-9A-Za-z가-힣]$")
_WORD_HEAD_RE = re.compile(r"^[0-9A-Za-z가-힣]")


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
            if sep and (fits or _LIST_HEAD_RE.match(nxt)):
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
        content = el.get("content", "") or ""
        if etype in _PARA_JOIN_TYPES:
            content = _join_wrapped_lines(content)
        else:
            content = _join_split_words(content)      # 낱말 갈림은 유형을 안 가린다
        content = _promote_box_title(_split_inline_choices(content))
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
        refused = _is_extraction_refusal(content)
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
            )

    _reorder_by_geometry(bbox_items, int(meta.get("page_rotation") or 0))
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
        braille_outputs = await run_braille(TableBraille().translate, llm_outputs)
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
        from app.ai.braille.cartoon_braille import CartoonBraille
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
        from app.ai.braille.chart_graph_braille import ChartGraphBraille
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
        from app.ai.braille.diagram_braille import DiagramBraille
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


def _mode_b_segments(src: str) -> list[tuple[int, str, str]]:
    """mode b source_text → [(원본 줄 번호, 요소 유형, 텍스트)].

    `<!표>…<!/표>`는 여러 줄에 걸쳐도 **요소 하나**로 묶어 표 체인에 보낸다. 줄 단위로
    쪼개면 `<!행>`만 든 조각이 생겨 표 구조가 복원 불가능해진다. 나머지는 종전대로
    줄 하나 = 요소 하나(빈 줄은 요소를 만들지 않고 번호만 건너뛴다 — 2026-08-06).
    """
    def _lines(a: int, b: int) -> list[tuple[int, str, str]]:
        base = src.count("\n", 0, a) + 1
        return [(base + i, "text", ln)
                for i, ln in enumerate(src[a:b].split("\n")) if ln.strip()]

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
        src_lines = _mode_b_segments(_mode_b_html_tables_to_tags(task.source_text or ""))
        if not src_lines:                       # 내용이 없으면 빈 응답(빈 결과 금지 규칙은
            src_lines = [(1, "text", task.source_text or "")]   # 플레이스홀더가 담당)
        line_ids = [uuid4() for _ in src_lines]
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
    from app.ai.llm.visual_drafts import LABELS, VOLREF_IDX, volume_ref_draft

    bo_by_id = {b.element_id: b for b in (braille_outputs or [])}
    ordinal = 0
    for o in llm_outputs:
        for i, d in enumerate(o.drafts or []):
            if d.label != LABELS[VOLREF_IDX]:
                continue
            ordinal += 1
            nd = volume_ref_draft(d.type_label, f"{page_no}-{ordinal}")
            o.drafts[i] = nd
            bo = bo_by_id.get(o.element_id)
            for j, bd in enumerate(bo.drafts or []) if bo else ():
                if bd.label != LABELS[VOLREF_IDX]:
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
) -> dict:
    elem_by_id = {e.element_id: e for e in layout_result.elements}
    braille_by_id = {b.element_id: b for b in braille_outputs}
    ext_by_id = {e.element_id: e for e in extracted}
    flat = flat or {}
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
            # 캡셔닝을 끄고 돈 산출물이면 박아 둔다 — 이걸로 시각 축을 재면 안 된다.
            "caption_disabled": os.getenv("SEMOJUM_NO_CAPTION") == "1",
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
                "rule_trail": [r.model_dump() for r in o.rule_trail],
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
                    or any("[처리 불가" in ln for ln in (
                        braille_by_id[o.element_id].braille_lines
                        if o.element_id in braille_by_id else []
                    ))
                ),
                "render_mode": o.render_mode,
                "contents": _selected_lines(
                    braille_by_id.get(o.element_id), flat
                ),
                # 좌표계가 통 문자열이라 flat의 것을 쓴다(layout이 재매핑한 조판 좌표 아님).
                "rule_trail": [
                    r.model_dump()
                    for r in (
                        flat[o.element_id].trail
                        if o.element_id in flat
                        else (braille_by_id[o.element_id].rule_trail
                              if o.element_id in braille_by_id else o.rule_trail)
                    )
                ],
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
                    }
                    for di, d in enumerate(
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
        # 원가는 성공·타임아웃·예외 **셋 다** 싣는다 — 막혔어도 돈은 나갔다.
        result["usage"] = {**usage_report(), "layout_type": _page_layout_type(result)}
        _record_metrics(result, elapsed_ms)
        return result

    except asyncio.TimeoutError:
        elapsed_ms = int((time.monotonic() - start) * 1000)
        logger.warning("⛔ BLOCKED(타임아웃) %.1fs · API %s  (job=%s page=%d)",
                       elapsed_ms / 1000, api_summary(), task.job_id, task.page_no)
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
