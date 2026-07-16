"""코퍼스 러너 — split_manifest.csv 기반으로 input PDF를 파이프라인(mode c)에 통과시켜
storage/jobs 양식으로 조립하고, 정답 BRL과 페어링한다. report_builder가 그대로 소비.

설계 요지(셰이크아웃에서 확정):
- mode c 만 점자를 낸다(pipeline.py: include_braille = mode=="c"). 정답 BRL 대조이므로 c 고정.
- 추출(MinerU)=페이지당 ~84s 1회·캐시, 점역(opt→braille)=~5s. --reuse 면 추출 캐시 보존,
  opt→braille 만 재실행 → 프롬프트 튜닝 반복이 빠름.
- 과목당 1 job(corpus-{tag}-{subject}), 페이지는 page_001.. 로 적재(단일페이지 PDF·page_no clamp).
- 페이지별 체크포인트(run_state.json) → 중단 후 재개(COMPLETED 건너뜀, --force 면 무시).
- 실시간 상태바: 과목 k/K · page n/N · ok/fail/timeout · ETA.

사용(작업 디렉토리 = code/AI/, env=semojum, MINERU_BIN export):
  python test/corpus_runner.py --split dev --limit 5 --purposive   # 스모크 5p/과목
  python test/corpus_runner.py --split val                          # val 전수
  python test/corpus_runner.py --subjects 수학2,생물 --reuse        # 추출캐시 재사용
"""
from __future__ import annotations

import argparse
import asyncio
import csv
import json
import os
import shutil
import sys
import time
import traceback
from pathlib import Path

# 오프라인 코퍼스 평가는 운영 180s 페이지 예산에 묶일 이유가 없다. 무거운 MinerU 추출이
# 180s를 넘기면 C7 BLOCKED가 되므로, app 모듈(config 싱글톤) import 전에 기본값을 늘린다.
# (운영 .env 는 그대로 180s 유지 — 여기서만 env 미설정 시 600s 로 올린다.)
os.environ.setdefault("PAGE_TIMEOUT_SECONDS", "600")

sys.path.insert(0, str(Path(__file__).parent.parent))

import fitz  # noqa: E402

from app.core import pipeline  # noqa: E402
from app.schemas.task import PageTask  # noqa: E402

AI = Path(__file__).parent.parent
TD = AI / "test/test_data"
INPUT = TD / "input"
OUTPUT = TD / "output"
MANIFEST = TD / "dataset/split_manifest.csv"
STORAGE = Path("storage/jobs")
RENDER_DPI = 150
# 러너 외부 타임아웃. 파이프라인 내부 타임아웃(PAGE_TIMEOUT_SECONDS, 운영 180s)보다 커야 한다.
# 오프라인 코퍼스 평가는 MinerU 추출이 무거운 페이지에서 180s를 넘길 수 있어 둘 다 늘린다.
PAGE_TIMEOUT = float(os.environ.get("CORPUS_PAGE_TIMEOUT", "650"))  # 초(파이프라인 내부보다 크게)


# ── manifest / 선택 ──────────────────────────────────────────────────────
def load_manifest() -> list[dict]:
    with MANIFEST.open(encoding="utf-8") as f:
        return list(csv.DictReader(f))


def visual_score(pdf: Path) -> int:
    """페이지 시각요소 풍부도(이미지+드로잉 수) — 의도표집 랭킹용."""
    try:
        d = fitz.open(pdf)
        p = d[0]
        n = len(p.get_images()) + len(p.get_drawings())
        d.close()
        return n
    except Exception:
        return 0


def select(rows: list[dict], split: str | None, subjects: set[str] | None,
           limit: int | None, purposive: bool) -> dict[str, list[str]]:
    """과목 → [page,...] 선택."""
    by_sub: dict[str, list[str]] = {}
    for r in rows:
        if split and r["split"] != split:
            continue
        if subjects and r["subject"] not in subjects:
            continue
        by_sub.setdefault(r["subject"], []).append(r["page"])
    for sub, pages in by_sub.items():
        pages.sort()
        if limit and len(pages) > limit:
            if purposive:
                ranked = sorted(
                    pages,
                    key=lambda pg: visual_score(INPUT / f"input_{sub}_page{pg}.pdf"),
                    reverse=True,
                )
                by_sub[sub] = sorted(ranked[:limit])
            else:
                # 균등 간격
                idx = sorted({round(i * (len(pages) - 1) / (limit - 1)) for i in range(limit)})
                by_sub[sub] = [pages[i] for i in idx]
    return by_sub


# ── 렌더/병합(e2e_runner 양식) ───────────────────────────────────────────
def render_page(pdf: Path, dst: Path, page_no: int) -> None:
    d = fitz.open(pdf)
    zoom = RENDER_DPI / 72.0
    pix = d[0].get_pixmap(matrix=fitz.Matrix(zoom, zoom))
    pix.save(str(dst / f"page_{page_no:03d}.jpg"))
    d.close()


def page_text(pdf: Path) -> str:
    d = fitz.open(pdf)
    t = d[0].get_text().strip()
    d.close()
    return t


# ── 상태바 ───────────────────────────────────────────────────────────────
def bar(cur: int, total: int, *, ok: int, blocked: int, fail: int, to: int, eta: float, label: str):
    w = 26
    fill = int(w * cur / total) if total else w
    etas = f"{int(eta//60)}m{int(eta%60):02d}s" if eta > 0 else "--"
    sys.stdout.write(
        f"\r[{'#'*fill}{'.'*(w-fill)}] {cur}/{total} "
        f"ok{ok} blk{blocked} fail{fail} to{to} ETA{etas} {label[:30]:<30}"
    )
    sys.stdout.flush()


# ── job 실행 ─────────────────────────────────────────────────────────────
async def run_subject(subject: str, pages: list[str], tag: str, *,
                      reuse: bool, force: bool, prog: dict) -> dict:
    job_id = f"corpus-{tag}-{subject}"
    job_dir = STORAGE / job_id
    input_dir = job_dir / "input"
    input_dir.mkdir(parents=True, exist_ok=True)

    state_path = job_dir / "run_state.json"
    done: dict[str, dict] = {}
    if state_path.exists() and not force:
        try:
            done = {p["page"]: p for p in json.loads(state_path.read_text())["pages"]
                    if p.get("status") == "COMPLETED"}
        except Exception:
            done = {}

    page_states: list[dict] = []
    for li, pg in enumerate(pages, start=1):
        pdf = INPUT / f"input_{subject}_page{pg}.pdf"
        gold = OUTPUT / f"output_{subject}_page{pg}.brl"
        prog["cur"] += 1
        elapsed = time.time() - prog["t0"]
        eta = (elapsed / prog["cur"]) * (prog["total"] - prog["cur"]) if prog["cur"] else 0
        bar(prog["cur"], prog["total"], ok=prog["ok"], blocked=prog["blocked"],
            fail=prog["fail"], to=prog["to"], eta=eta, label=f"{subject} p{pg}")

        if pg in done:  # 재개: 이미 완료
            page_states.append(done[pg])
            prog["ok"] += 1
            continue

        render_page(pdf, input_dir, li)
        shutil.copy(pdf, input_dir / f"original_p{pg}.pdf")
        task = PageTask(job_id=job_id, page_no=li, total_pages=len(pages),
                        pdf_data=pdf.read_bytes(), mode="c", source_text="")
        t0 = time.time()
        rec = {"page": pg, "local_no": li, "gold": str(gold),
               "gold_exists": gold.exists()}
        try:
            res = await asyncio.wait_for(pipeline.run(task), timeout=PAGE_TIMEOUT)
            (job_dir / "temp" / f"page_{li:03d}").mkdir(parents=True, exist_ok=True)
            (job_dir / "temp" / f"page_{li:03d}" / "response.json").write_text(
                json.dumps(res, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
            pm = res.get("processing_meta", {})
            rec.update({
                "status": res.get("status"),
                "tier": pm.get("routing_tier_used"),
                "time_ms": int((time.time() - t0) * 1000),
                "n_text": len(res.get("text_list") or []),
                "n_braille": len(res.get("braille_text_list") or []),
                "critical": [c.get("type") for c in
                             res.get("quality_report", {}).get("critical_errors", [])],
                "error": None,
            })
            # BLOCKED(C7 타임아웃 등)는 ok가 아니다 — 상태별로 분리 집계.
            prog["ok" if rec["status"] == "COMPLETED" else "blocked"] += 1
        except asyncio.TimeoutError:
            rec.update({"status": "TIMEOUT", "time_ms": int((time.time() - t0) * 1000),
                        "error": f"timeout>{PAGE_TIMEOUT}s"})
            prog["to"] += 1
        except (Exception, SystemExit) as exc:  # SystemExit도 격리(라이브러리 sys.exit 방어)
            rec.update({"status": "ERROR", "time_ms": int((time.time() - t0) * 1000),
                        "error": f"{type(exc).__name__}: {exc}",
                        "traceback": traceback.format_exc()})
            prog["fail"] += 1
        page_states.append(rec)
        # 페이지마다 체크포인트 저장(중단 대비)
        _save_state(job_dir, job_id, subject, tag, page_states)

    _save_state(job_dir, job_id, subject, tag, page_states)
    return {"job_id": job_id, "pages": page_states}


def _save_state(job_dir: Path, job_id: str, subject: str, tag: str, pages: list[dict]):
    (job_dir).mkdir(parents=True, exist_ok=True)
    (job_dir / "run_state.json").write_text(json.dumps({
        "job_id": job_id, "subject": subject, "tag": tag,
        "updated": time.strftime("%Y-%m-%d %H:%M:%S"),
        "pages": pages,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    _write_e2e_state(job_dir, job_id, subject, pages)


def _write_e2e_state(job_dir: Path, job_id: str, subject: str, pages: list[dict]):
    """report_builder 호환 state.json — run_state 필드를 e2e 양식으로 매핑.
    (page_no←local_no, routing_tier←tier, processing_time_ms←time_ms 등)"""
    e2e_pages = [{
        "page_no": p.get("local_no"),
        "status": p.get("status"),
        "routing_tier": p.get("tier"),
        "processing_time_ms": p.get("time_ms", 0),
        "n_text_elements": p.get("n_text", 0),
        "n_braille_elements": p.get("n_braille", 0),
        "n_blocked": 0,
        "critical_errors": [{"type": t} for t in (p.get("critical") or [])],
        "error": p.get("error"),
        "src_page": p.get("page"),
    } for p in pages]
    total_ms = sum(p.get("time_ms", 0) or 0 for p in pages)
    scan = any(p.get("tier") == "STANDARD" for p in pages)
    (job_dir / "state.json").write_text(json.dumps({
        "job_id": job_id, "slice": subject, "mode": "c", "scan_path": scan,
        "total_pages": len(pages), "total_time_ms": total_ms, "pages": e2e_pages,
    }, ensure_ascii=False, indent=2), encoding="utf-8")


# ── main ─────────────────────────────────────────────────────────────────
def main():
    ap = argparse.ArgumentParser(description="Semojum V2 코퍼스 러너(mode c)")
    ap.add_argument("--split", choices=["dev", "val", "test"], default=None)
    ap.add_argument("--subjects", default=None, help="과목 한정(쉼표구분)")
    ap.add_argument("--limit", type=int, default=None, help="과목당 페이지 상한")
    ap.add_argument("--purposive", action="store_true", help="시각요소 풍부 페이지 우선 선택")
    ap.add_argument("--tag", default=None, help="job 태그(기본 split 또는 custom)")
    ap.add_argument("--reuse", action="store_true", help="추출 캐시 보존, opt→braille만 재실행")
    ap.add_argument("--force", action="store_true", help="완료 페이지도 재실행")
    args = ap.parse_args()

    if not os.environ.get("MINERU_BIN"):
        print("⚠ MINERU_BIN 미설정 — STANDARD 라우팅 페이지는 빈 추출이 될 수 있음.")

    rows = load_manifest()
    subjects = set(args.subjects.split(",")) if args.subjects else None
    sel = select(rows, args.split, subjects, args.limit, args.purposive)
    if not sel:
        print("선택된 페이지 없음."); return
    tag = args.tag or args.split or "custom"

    total = sum(len(v) for v in sel.values())
    print(f"=== 코퍼스 러너 tag={tag} mode=c | 과목 {len(sel)} · 페이지 {total} ===")
    for sub, pgs in sorted(sel.items()):
        print(f"  {sub:<8} {len(pgs)}p: {' '.join(pgs)}")
    print("-" * 60)

    prog = {"cur": 0, "total": total, "ok": 0, "blocked": 0, "fail": 0, "to": 0, "t0": time.time()}
    summaries = []
    for sub in sorted(sel):
        s = asyncio.run(run_subject(sub, sel[sub], tag, reuse=args.reuse,
                                    force=args.force, prog=prog))
        summaries.append(s)
    print()  # 상태바 줄바꿈
    print("-" * 60)
    print(f"완료: COMPLETED{prog['ok']} BLOCKED{prog['blocked']} fail{prog['fail']} "
          f"timeout{prog['to']} / {total}  ({int(time.time()-prog['t0'])}s)")
    # 실패/타임아웃 페이지 목록
    bad = [(s["job_id"], p["page"], p["status"], p.get("error"))
           for s in summaries for p in s["pages"]
           if p.get("status") not in ("COMPLETED",)]
    if bad:
        print("문제 페이지:")
        for jid, pg, st, err in bad[:30]:
            print(f"  {jid} p{pg}: {st} {err or ''}")


if __name__ == "__main__":
    main()
