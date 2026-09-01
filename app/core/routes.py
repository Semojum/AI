"""REST 엔드포인트 — 헬스체크·모델 상태 + 마감 조판(/finalize).

점자 '변환'(이미지→점자)은 반드시 gRPC(grpc_server.py)로만 처리한다.
/finalize는 변환이 아니라 **조판(페이지 조립)** 전용 — 점역사가 편집한 블록을
점자 규정(NLD)대로 페이지로 조립해 회신한다(모델·braillify 미사용, 순수 규칙).
"""

from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel, Field

router = APIRouter()


@router.get("/health")
async def health_check():
    from app.core.health_check import get_health
    return get_health()


@router.get("/models/status")
async def models_status():
    from app.core.health_check import get_models_status
    return get_models_status()


# ── 마감 조판 (/finalize) ────────────────────────────────────────────────────
# 점역사가 블록 단위로 편집한 점자(이미 32칸 줄)를 받아 NLD 규정대로 페이지 조립.
# 블록 간 빈 줄(제목 단계별)·25줄 페이지 나눔·페이지행(원본번호·꼬리말·점자번호) 적용.

class FinalizeBlock(BaseModel):
    """점역사 편집 블록 1개 (요소 단위). lines = 32칸으로 조판된 점자 줄.

    ★ 두 형식을 모두 받는다(2026-07-28) — BE는 응답의 `contents`를 그대로 되돌려주면 된다.
      · 줄 배열      ["줄1", "줄2"]        (종전 형식)
      · 요소 1항목   ["줄1\\n줄2"]          (현재 `contents` 형식)
    `normalized_lines()`가 어느 쪽이든 줄 배열로 펴 준다.
    """
    id: str = ""
    type: str = "text"          # text|title|formula|table|image|cartoon|chart_graph|list_item|header_footer|page_number|...
    heading_level: int = 0      # 제목 단계(빈 줄 규칙). 0=본문
    order: int = 0              # 문서 읽기 순서
    lines: list[str] = Field(default_factory=list)  # 점자 줄(U+2800, 각 ≤32칸) 또는 줄바꿈 결합 1항목

    def normalized_lines(self) -> list[str]:
        """`lines`를 줄 배열로 정규화(줄바꿈 결합 항목을 펴 준다)."""
        out: list[str] = []
        for ln in self.lines:
            out.extend(ln.split("\n") if "\n" in ln else [ln])
        return out


class FinalizeRequest(BaseModel):
    job_id: str = ""
    page_no: int = 1            # 이 페이지의 시작 점자 페이지 번호
    total_pages: int = 1
    blocks: list[FinalizeBlock] = Field(default_factory=list)


class BraillePage(BaseModel):
    page_no: int                # 점자 페이지 번호
    lines: list[str]            # 32칸 × 25줄 (페이지행 포함)


class FinalizeResponse(BaseModel):
    job_id: str
    page_number: int            # 요청 시작 페이지 번호
    pages: list[BraillePage]    # 조립된 점자 페이지들(원본 1쪽이 여러 점자쪽이 될 수 있음)
    brf: str                    # 전체 BRF 텍스트(줄바꿈 join) — 파일 저장용


@router.post("/finalize", response_model=FinalizeResponse)
async def finalize_page(req: FinalizeRequest) -> FinalizeResponse:
    """편집 블록 → NLD 페이지 조립. (점자 변환 아님 — 규칙 기반 조판만.)"""
    from app.ai.braille.layout_braille import LayoutBraille

    pages = LayoutBraille().finalize(
        [{**b.model_dump(), "lines": b.normalized_lines()} for b in req.blocks],
        page_no=req.page_no,
    )
    brf = "\n".join(line for page in pages for line in page)
    return FinalizeResponse(
        job_id=req.job_id,
        page_number=req.page_no,
        pages=[BraillePage(page_no=req.page_no + i, lines=pg) for i, pg in enumerate(pages)],
        brf=brf,
    )


# ── 로그 조회 (T2, 2026-08-23) ──────────────────────────────────────────────
# 관리자 웹이 **터미널 접속 없이** 로그를 본다. BE·FE 저장소는 우리가 못 고치므로
# 우리 몫은 ①로그 파일 ②이 조회 엔드포인트 ③BE 가 붙을 규격 문서까지다.
#
# 폴링 조회로 낸다(웹훅 푸시가 아니라). 까닭은 `docs/SPEC-INTERFACE.md` 로그 절에 적었다 —
# 요지는 AI 서버가 BE 주소를 알아야 하는 결합을 만들지 않는 쪽이 낫고, 재시도·유실 처리를
# 우리가 떠안지 않아도 되기 때문이다.
#
# ⚠ 파일 내용·개인정보는 로그에 안 실린다(식별자와 수치까지). 이 엔드포인트는 그 파일을
#   그대로 읽어 줄 뿐이라 새로 새는 것이 없다.


class LogQuery(BaseModel):
    limit: int = Field(200, ge=1, le=2000, description="최근 몇 줄")
    level: str | None = Field(None, description="ERROR·WARNING·INFO 로 거른다")
    job_id: str | None = None
    guard: int | None = Field(None, description="캡션 가드 발동만 보려면 1·2·3")


def _read_jsonl(limit: int) -> list[dict]:
    """최근 줄만 읽는다. 회전 파일(.1)까지 훑되 통째로 메모리에 안 올린다."""
    import json
    from pathlib import Path
    from app.utils.logger import _LOG_DIR, _JSON_FILE

    out: list[dict] = []
    for name in (_JSON_FILE, f"{_JSON_FILE}.1"):
        f = Path(_LOG_DIR) / name
        if not f.exists():
            continue
        try:
            with f.open(encoding="utf-8") as fh:
                lines = fh.readlines()[-(limit * 2):]
        except OSError:
            continue
        for ln in reversed(lines):
            ln = ln.strip()
            if not ln:
                continue
            try:
                out.append(json.loads(ln))
            except ValueError:
                continue          # 회전 도중 잘린 줄 — 건너뛴다
            if len(out) >= limit * 2:
                break
        if len(out) >= limit * 2:
            break
    return out


@router.get("/logs")
async def logs(limit: int = 200, level: str | None = None,
               job_id: str | None = None, guard: int | None = None):
    """최근 로그 레코드(최신 순). 관리자 웹이 폴링한다.

    필터는 전부 선택이다. 아무것도 안 주면 최근 `limit` 줄을 준다.
    """
    q = LogQuery(limit=limit, level=level, job_id=job_id, guard=guard)
    rows = _read_jsonl(q.limit)
    if q.level:
        want = q.level.upper()
        rows = [r for r in rows if r.get("level") == want]
    if q.job_id:
        rows = [r for r in rows if r.get("job_id") == q.job_id]
    if q.guard is not None:
        rows = [r for r in rows if r.get("guard") == q.guard]
    return {"count": len(rows[:q.limit]), "records": rows[:q.limit]}


@router.get("/logs/summary")
async def logs_summary(limit: int = 2000):
    """최근 구간 요약 — 관리자 화면 첫 장에 띄울 수치.

    ★ 캡션 가드 발동 수가 여기 있다. 스캔본에서 그 가드가 실제로 몇 번 도는지는
      실사용에서 세는 수밖에 없다(원장 C-40).
    """
    import collections
    rows = _read_jsonl(limit)
    lv = collections.Counter(r.get("level", "?") for r in rows)
    guards = collections.Counter(r["guard"] for r in rows if r.get("guard"))
    codes = collections.Counter(r["code"] for r in rows if r.get("code"))
    return {
        "records": len(rows),
        "levels": dict(lv),
        "guards": {f"가드{k}": v for k, v in sorted(guards.items())},
        "codes": dict(codes),
        "jobs": len({r["job_id"] for r in rows if r.get("job_id")}),
    }
