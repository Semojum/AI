"""E2E 테스트 러너 — test/data/*.pdf를 파이프라인에 통과시켜 storage 양식으로 조립.

서버(gRPC) 없이 pipeline.run()을 페이지 단위로 직접 호출한다. BE 연동 중단 중
AI 파트 단독 검증용. 각 (슬라이스, 모드) 조합을 하나의 job으로 보고,
storage/jobs/{job_id}/ 아래에 다음 양식으로 산출물을 조립한다:

    storage/jobs/{job_id}/
      state.json          # job 상태(페이지별 진행·에러)
      report.txt          # 단계별 처리시간 리포트
      input/original.pdf  # 입력 PDF
      input/page_NNN.jpg  # 페이지 렌더 이미지
      output/result.txt   # 전 페이지 병합 점역(텍스트형)
      output/result.brf   # 전 페이지 병합 점역(BRF)
      temp/page_NNN/...   # pipeline.py가 기록(경계·단계별 json·result)

사용법(작업 디렉토리 = code/AI/):
    python test/e2e_runner.py                 # 기본 매니페스트 전체
    python test/e2e_runner.py --only test_국어지문_01   # 일부만
    python test/e2e_runner.py --modes c       # 모드 한정
    python test/e2e_runner.py --no-scan       # 스캔(MinerU) 슬라이스 제외
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import shutil
import sys
import time
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import fitz  # noqa: E402

from app.core import pipeline  # noqa: E402
from app.schemas.task import PageTask  # noqa: E402

DATA_DIR = Path(__file__).parent / "data"
STORAGE = Path("storage/jobs")
RENDER_DPI = 150

# 국어(0% PUA)=ZERO → a/b/c 모두 빠름.
# 수학(PUA 과다)=pdf_analyzer가 STANDARD로 라우팅 → mode a/c는 MinerU(느림). 추출이
# 동일한 a는 생략하고 b(source_text·빠름)+c(MinerU 전체)만. 스캔 슬라이스도 c만.
# scan=True 표시는 MinerU 경유(느림) → --no-scan으로 제외 가능.
DEFAULT_MANIFEST = [
    {"slice": "test_국어지문_01", "modes": ["a", "b", "c"], "scan": False},
    {"slice": "test_국어복합_02", "modes": ["a", "b", "c"], "scan": False},
    {"slice": "test_수학수식_01", "modes": ["b", "c"], "scan": True},
    {"slice": "test_수학도형_02", "modes": ["b", "c"], "scan": True},
    {"slice": "test_수학수식_scan_01", "modes": ["c"], "scan": True},
    {"slice": "test_국어복합_scan_02", "modes": ["c"], "scan": True},
]


def _page_text(pdf_path: Path, page_idx: int) -> str:
    d = fitz.open(pdf_path)
    txt = d[page_idx].get_text().strip()
    d.close()
    return txt


def _render_pages(pdf_path: Path, input_dir: Path) -> int:
    d = fitz.open(pdf_path)
    zoom = RENDER_DPI / 72.0
    mat = fitz.Matrix(zoom, zoom)
    for i in range(len(d)):
        pix = d[i].get_pixmap(matrix=mat)
        pix.save(str(input_dir / f"page_{i + 1:03d}.jpg"))
    n = len(d)
    d.close()
    return n


async def run_job(slice_name: str, mode: str, *, scan: bool, reuse: bool = False) -> dict:
    """슬라이스 1개를 mode 1개로 전 페이지 처리하고 storage 양식으로 조립.

    reuse=True면 기존 job 디렉토리(특히 MinerU 추출 캐시)를 보존하고 opt→braille만
    재실행한다(수식 점역 등 후단만 바뀌었을 때 재추출 없이 빠르게 갱신).
    """
    pdf_path = DATA_DIR / f"{slice_name}.pdf"
    if not pdf_path.exists():
        raise FileNotFoundError(pdf_path)
    pdf_bytes = pdf_path.read_bytes()

    job_id = f"e2e-{slice_name}-{mode}"
    job_dir = STORAGE / job_id
    if job_dir.exists() and not reuse:
        shutil.rmtree(job_dir)          # 캐시 재사용 방지(매 실행 새 추출)
    input_dir = job_dir / "input"
    output_dir = job_dir / "output"
    input_dir.mkdir(parents=True, exist_ok=True)
    output_dir.mkdir(parents=True, exist_ok=True)

    shutil.copy(pdf_path, input_dir / "original.pdf")
    total_pages = _render_pages(pdf_path, input_dir)

    page_states: list[dict] = []
    started = time.time()
    for page_no in range(1, total_pages + 1):
        task = PageTask(
            job_id=job_id,
            page_no=page_no,
            total_pages=total_pages,
            pdf_data=pdf_bytes,
            mode=mode,
            source_text=_page_text(pdf_path, page_no - 1) if mode == "b" else "",
        )
        t0 = time.time()
        try:
            result = await pipeline.run(task)
            elapsed = int((time.time() - t0) * 1000)
            n_text = len(result.get("text_list", []) or [])
            n_braille = len(result.get("braille_text_list", []) or [])
            blocked = sum(
                1 for x in (result.get("braille_text_list") or result.get("text_list") or [])
                if x.get("is_blocked")
            )
            page_states.append({
                "page_no": page_no,
                "status": result.get("status"),
                "routing_tier": result.get("processing_meta", {}).get("routing_tier_used"),
                "processing_time_ms": result.get("processing_meta", {}).get("processing_time_ms", elapsed),
                "n_text_elements": n_text,
                "n_braille_elements": n_braille,
                "n_blocked": blocked,
                "critical_errors": result.get("quality_report", {}).get("critical_errors", []),
                "error": None,
            })
            # 응답 dict 자체도 보존(디버그/시각화용)
            (job_dir / "temp" / f"page_{page_no:03d}").mkdir(parents=True, exist_ok=True)
            (job_dir / "temp" / f"page_{page_no:03d}" / "response.json").write_text(
                json.dumps(result, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
            )
        except Exception as exc:  # noqa: BLE001 — 페이지 격리, 전체 job 계속
            page_states.append({
                "page_no": page_no, "status": "ERROR",
                "processing_time_ms": int((time.time() - t0) * 1000),
                "error": f"{type(exc).__name__}: {exc}",
                "traceback": traceback.format_exc(),
            })
    finished = time.time()

    _merge_outputs(job_dir, output_dir, total_pages, mode)
    state = {
        "job_id": job_id,
        "slice": slice_name,
        "mode": mode,
        "scan_path": scan,
        "total_pages": total_pages,
        "started_at": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(started)),
        "finished_at": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(finished)),
        "total_time_ms": int((finished - started) * 1000),
        "pages": page_states,
    }
    (job_dir / "state.json").write_text(
        json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    _write_report(job_dir, state)
    return state


def _merge_outputs(job_dir: Path, output_dir: Path, total_pages: int, mode: str) -> None:
    """페이지별 result.{txt,brf}를 병합. mode a는 점역 없음 → 추출 텍스트로 대체."""
    txt_parts: list[str] = []
    brf_parts: list[str] = []
    for page_no in range(1, total_pages + 1):
        rdir = job_dir / "temp" / f"page_{page_no:03d}" / "result"
        sep = f"\n{'=' * 40}  page {page_no}  {'=' * 40}\n"
        rtxt = rdir / f"{page_no:03d}_result.txt"
        rbrf = rdir / f"{page_no:03d}_result.brf"
        if rtxt.exists():
            txt_parts.append(sep + rtxt.read_text(encoding="utf-8"))
        if rbrf.exists():
            brf_parts.append(sep + rbrf.read_text(encoding="utf-8"))
    (output_dir / "result.txt").write_text("".join(txt_parts), encoding="utf-8")
    (output_dir / "result.brf").write_text("".join(brf_parts), encoding="utf-8")


def _write_report(job_dir: Path, state: dict) -> None:
    lines = [
        f"E2E 처리 리포트 — {state['job_id']}",
        f"슬라이스: {state['slice']}  모드: {state['mode']}  경로: {'SCAN/MinerU' if state['scan_path'] else 'ZERO/텍스트'}",
        f"총 페이지: {state['total_pages']}  총 시간: {state['total_time_ms']}ms",
        f"시작: {state['started_at']}  종료: {state['finished_at']}",
        "-" * 60,
        f"{'page':>4} {'status':>14} {'tier':>10} {'time(ms)':>9} {'text':>5} {'braille':>7} {'blocked':>7}",
    ]
    for p in state["pages"]:
        lines.append(
            f"{p['page_no']:>4} {str(p.get('status')):>14} {str(p.get('routing_tier','')):>10} "
            f"{p.get('processing_time_ms', 0):>9} {p.get('n_text_elements', 0):>5} "
            f"{p.get('n_braille_elements', 0):>7} {p.get('n_blocked', 0):>7}"
        )
        if p.get("error"):
            lines.append(f"       ERROR: {p['error']}")
        for ce in (p.get("critical_errors") or []):
            lines.append(f"       {ce.get('type')}: {ce.get('message')}")
    (job_dir / "report.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    ap = argparse.ArgumentParser(description="Semojum V2 AI E2E 러너")
    ap.add_argument("--only", default=None, help="슬라이스 이름 일부만(쉼표구분)")
    ap.add_argument("--modes", default=None, help="모드 한정(예: c 또는 a,c)")
    ap.add_argument("--no-scan", action="store_true", help="스캔(MinerU) 슬라이스 제외")
    ap.add_argument("--reuse", action="store_true", help="기존 추출 캐시 보존, opt→braille만 갱신")
    args = ap.parse_args()

    only = set(args.only.split(",")) if args.only else None
    modes_filter = set(args.modes.split(",")) if args.modes else None

    summary = []
    for entry in DEFAULT_MANIFEST:
        if only and entry["slice"] not in only:
            continue
        if args.no_scan and entry["scan"]:
            continue
        modes = [m for m in entry["modes"] if not modes_filter or m in modes_filter]
        for mode in modes:
            print(f"\n▶ {entry['slice']}  mode={mode}  ({'SCAN' if entry['scan'] else 'ZERO'})")
            state = asyncio.run(run_job(entry["slice"], mode, scan=entry["scan"], reuse=args.reuse))
            ok = sum(1 for p in state["pages"] if p.get("status") == "COMPLETED")
            print(f"  → {ok}/{state['total_pages']} COMPLETED, {state['total_time_ms']}ms")
            summary.append((state["job_id"], ok, state["total_pages"], state["total_time_ms"]))

    print("\n" + "=" * 60 + "\n요약")
    for job_id, ok, tot, ms in summary:
        print(f"  {job_id:40} {ok}/{tot}  {ms}ms")


if __name__ == "__main__":
    main()
