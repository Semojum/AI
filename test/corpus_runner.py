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


# 신규 코퍼스(2026-08-05 구축, 묵자↔점자 2,940쌍 / 12권).
# `code/AI/` **바깥**에 둔다 — 저작권 검토 전까지 GitHub에 올라가면 안 된다(corpus/README).
CORPUS_2027 = Path(os.environ.get(
    "SEMOJUM_CORPUS_ROOT", str(Path(__file__).resolve().parents[3] / "corpus")))


# ── manifest / 선택 ──────────────────────────────────────────────────────
def load_manifest(corpus: str = "frozen") -> list[dict]:
    """`{subject, page, split, _pdf, _gold}` 목록.

    두 코퍼스를 같은 모양으로 만든다.
      frozen — 기존 동결 코퍼스(구판 수능특강 6과목 1,251쌍). 경로는 이름 규약으로 만든다.
      2027   — 신규 코퍼스(12권 2,940쌍). manifest가 경로를 직접 들고 있다.

    ★ 신규 쪽은 `subject`에 **책**을 쓴다. 분할 단위가 쪽이 아니라 책이기 때문이다
      (같은 책은 머리말·표 양식·점역자주 문구가 같아 쪽으로 나누면 새어 나간다).
    """
    if corpus == "frozen":
        with MANIFEST.open(encoding="utf-8") as f:
            return [{**r, "_pdf": INPUT / f"input_{r['subject']}_page{r['page']}.pdf",
                     "_gold": OUTPUT / f"output_{r['subject']}_page{r['page']}.brl"}
                    for r in csv.DictReader(f)]

    mf = CORPUS_2027 / "split_manifest.csv"
    if not mf.exists():
        raise SystemExit(f"신규 코퍼스 manifest 없음: {mf}\n"
                         f"  SEMOJUM_CORPUS_ROOT 로 위치를 지정하거나 corpus/를 준비할 것")
    rows = []
    with mf.open(encoding="utf-8") as f:
        for r in csv.DictReader(f):
            rows.append({
                "subject": r["book_id"],          # 분할 단위 = 책
                "page": f"{int(r['page']):04d}",  # 정렬용 고정폭
                "split": r["split"],
                "domain": r["domain"],
                "vol": r["vol"],
                "_pdf": CORPUS_2027 / r["print"],
                "_gold": CORPUS_2027 / r["braille"],
            })
    return rows


# (subject, vol, page) → manifest 행. 경로가 코퍼스마다 달라 이름 규약으로 만들 수 없다.
#
# ★ 2026-08-22 — 키에 **권(vol)**을 넣었다. 대표 승인.
#   신규 코퍼스는 같은 (book_id, page)가 **본책(body)과 정답해설(ans)에 둘 다** 있다.
#   종전 키가 (subject, page)뿐이라 뒤엣것(ans)이 앞엣것(body)을 덮었다. 규모:
#       dev-2027   900행 중 208 충돌(23.1%) · val 846 중 137(16.2%) · holdout 1,171 중 334(28.5%)
#   결과가 셋이었다 — ① 같은 page_NNN에 두 번 써서 **body 계산을 하고 버렸다**(GPU 낭비)
#   ② `original_p{쪽}.pdf`도 덮였다 ③ 재개용 done 사전이 둘 중 하나만 완료로 봤다.
#   채점 쪽 영향은 dev 총편집의 22.5%가 이중 계상이고 본책 208쪽이 한 번도 안 채점됐다.
#   빠지는 쪽이 늘 **어려운 본책**이라 지표가 낙관으로 약 3.8p 기울었다(eval 실측).
#   ⚠ A/B 상대 비교는 양쪽이 같은 버그를 타서 안 뒤집힌다. 정정 대상은 절대 수치다.
_ROW_BY_KEY: dict[tuple[str, str, str], dict] = {}


def row_key(r: dict) -> tuple[str, str, str]:
    """(과목, 권, 묵자쪽). 구 코퍼스(frozen)는 권이 없어 빈 문자열이 된다."""
    return (r["subject"], r.get("vol", ""), r["page"])


def index_rows(rows: list[dict]) -> None:
    _ROW_BY_KEY.clear()
    for r in rows:
        _ROW_BY_KEY[row_key(r)] = r


def _path_of(r: dict) -> Path:
    return r["_pdf"]


def _gold_of(r: dict) -> Path:
    return r["_gold"]


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
           limit: int | None, purposive: bool) -> dict[str, list[dict]]:
    """과목 → [manifest 행, ...] 선택.

    ⚠ 여기서 고른 순번을 local_no로 쓰면 안 된다 — page_index()를 쓸 것.
      이유는 그 함수 주석 참조(2026-07-29 실측 사고).

    ★ 2026-08-22 — 쪽번호 목록에서 **행 목록**으로 바꿨다. 같은 쪽번호가 두 권에 있어
      문자열로는 두 행을 못 가른다. 그 탓에 두 자리가 조용히 틀리고 있었다:
      · `--limit`(균등 간격) — 중복이 같이 뽑혀 limit개를 채워도 유니크는 적다.
        실측 `--limit 225`: dev 816 뽑아 유니크 639(손실 177) · val 846→709(137).
        (우리 A/B 대부분인 `--limit 50`은 200/200으로 손실 0이었다.)
      · `--purposive` — 랭킹 키가 `_path_of`라 **해설 지면 점수로 본책을 매겼다.**
        충돌 208쪽 중 63%에서 본책 시각 점수가 더 높다. 그리고 같은 점수라 정렬에서
        반드시 인접해 **둘 다 뽑힌다**: dev 384 뽑아 유니크 313(손실 71·18.5%) · val 384→326.
        시각 A/B(`visual_run.sh`)가 이 두 겹에 물려 있었다.
    """
    by_sub: dict[str, list[dict]] = {}
    for r in rows:
        if split and r["split"] != split:
            continue
        if subjects and r["subject"] not in subjects:
            continue
        by_sub.setdefault(r["subject"], []).append(r)
    for sub, rs in by_sub.items():
        rs.sort(key=lambda r: r["page"])          # 안정 정렬 — 같은 쪽은 매니페스트 순(body→ans)
        if limit and len(rs) > limit:
            if purposive:
                ranked = sorted(rs, key=lambda r: visual_score(_path_of(r)), reverse=True)
                by_sub[sub] = sorted(ranked[:limit], key=lambda r: r["page"])
            else:
                # 균등 간격
                idx = sorted({round(i * (len(rs) - 1) / (limit - 1)) for i in range(limit)})
                by_sub[sub] = [rs[i] for i in idx]
    return by_sub


# ── 페이지 번호 안정화 — 2026-07-29 ────────────────────────────────────────
# local_no(= storage/jobs/.../temp/page_NNN 디렉토리 번호)를 **선택된 부분집합의 순번**으로
# 쓰면 --limit 값에 따라 같은 번호가 다른 묵자 페이지를 가리킨다.
# 실제 사고: `--split test --limit 2`(스모크)가 과목당 [첫 페이지, 마지막 페이지]를
# local_no 1·2로 처리해 두었는데, 이어서 돌린 전량 실행은 두 번째 페이지에 li=2를 부여했다.
# 결과로 **6개 과목 전부 page_002/가 엉뚱한 페이지 내용을 갖게** 됐고, 그 6쪽이
# 홀드아웃 전체 편집의 18.8%를 차지해 점수를 76.55%로 끌어내렸다(제외 시 80.0%).
# → local_no는 **그 과목·split의 전체 페이지 목록에서의 위치**로 고정한다.
#   부분집합으로 돌리든 전량으로 돌리든 같은 묵자 페이지는 항상 같은 번호를 쓴다.
def build_page_index(rows: list[dict], split: str | None,
                     subjects: set[str] | None) -> dict[tuple[str, str, str], int]:
    """(과목, 권, 묵자쪽) → local_no. 선택 범위와 무관하게 안정적.

    ★ 2026-08-22 — **행 위치**로 번호를 준다(유니크 기준으로 다시 매기지 않는다).
      종전에도 중복을 포함한 채 enumerate했고 `out[(sub,pg)]`에 **마지막 위치**가 남았다.
      즉 승자인 ans가 이미 `i+1`을 쓰고 있고 `i`는 비어 있었다. 행마다 자기 위치를 주면
      **ans는 번호가 그대로고 body가 빈 `i`를 가져간다.**
      실측(2026-08-22): dev 900행 중 692 유지·208 이동, val 709/137, holdout 837/334이고
      **셋 다 기존 번호와 충돌 0**이다. 기존 산출물이 통째로 살아남고 새로 돌 쪽만 679다
      (전면 재추출 2,917쪽 대비 23%). 유니크 재번호로 갔으면 004는 245쪽 중 239쪽이
      바뀌어 전면 재추출이었다.
    """
    by_sub: dict[str, list[dict]] = {}
    for r in rows:
        if split and r["split"] != split:
            continue
        if subjects and r["subject"] not in subjects:
            continue
        by_sub.setdefault(r["subject"], []).append(r)
    out: dict[tuple[str, str, str], int] = {}
    for sub, rs in by_sub.items():
        for i, r in enumerate(sorted(rs, key=lambda x: x["page"]), start=1):
            out[row_key(r)] = i
    return out


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
def bar(cur: int, total: int, *, ok: int, review: int, blocked: int, fail: int, to: int, eta: float, label: str):
    w = 26
    fill = int(w * cur / total) if total else w
    etas = f"{int(eta//60)}m{int(eta%60):02d}s" if eta > 0 else "--"
    sys.stdout.write(
        f"\r[{'#'*fill}{'.'*(w-fill)}] {cur}/{total} "
        f"ok{ok} rv{review} blk{blocked} fail{fail} to{to} ETA{etas} {label[:30]:<30}"
    )
    sys.stdout.flush()


# ── job 실행 ─────────────────────────────────────────────────────────────
async def run_subject(subject: str, sel_rows: list[dict], tag: str, *,
                      reuse: bool, force: bool, prog: dict,
                      page_index: dict | None = None) -> dict:
    job_id = f"corpus-{tag}-{subject}"
    job_dir = STORAGE / job_id
    input_dir = job_dir / "input"
    input_dir.mkdir(parents=True, exist_ok=True)

    state_path = job_dir / "run_state.json"
    # ★ 2026-08-22 — 재개용 키에도 권을 넣는다. 쪽번호만으로는 두 권 중 하나만 완료로 보고
    #   나머지 하나를 영영 건너뛴다.
    #
    #   ⚠ **옛 run_state 호환이 여기서 한 번 어긋났다(실측 사고).** 수정 전에 쓰인 기록에는
    #     `vol`이 없다. 그걸 `""`로 읽으면 새 행의 `"body"`·`"ans"`와 **한 건도 안 맞아
    #     900쪽을 통째로 다시 돌린다**(208쪽만 새로 돌면 되는 자리에서 GPU 2.5시간 낭비).
    #     옛 기록이 가리키는 실체는 **그 쪽에서 실제로 돌았던 행 = 정렬 목록의 마지막 행**이다
    #     (구 코드가 마지막 위치를 썼기 때문). 그래서 그 행의 권으로 채워 넣는다.
    last_vol_of: dict[str, str] = {}
    for r in sel_rows:
        last_vol_of[r["page"]] = r.get("vol", "")     # 정렬 순 → 마지막이 남는다
    done: dict[tuple[str, str], dict] = {}
    if state_path.exists() and not force:
        try:
            # ★ 2026-08-22 — 재개 조건에 NEEDS_REVIEW를 포함한다(기존 버그).
            #   NEEDS_REVIEW는 **정상 산출**이다 — 점자를 다 만들고 검토 플래그만 붙은 상태다
            #   (아래 prog 집계 주석의 2026-07-17 사고와 같은 오해). 그런데 재개 사전이
            #   COMPLETED만 담아서, 실측상 dev 900쪽 중 **625쪽이 NEEDS_REVIEW라 매번 다시
            #   돌았다.** 202쪽만 건너뛰던 것이 이 한 줄로 692쪽이 된다.
            #   BLOCKED·TIMEOUT·ERROR는 그대로 다시 돈다 — 그건 진짜 실패다.
            for p in json.loads(state_path.read_text())["pages"]:
                if p.get("status") not in ("COMPLETED", "NEEDS_REVIEW"):
                    continue
                vol = p.get("vol") or last_vol_of.get(p["page"], "")
                done[(vol, p["page"])] = p
        except Exception:
            done = {}

    page_states: list[dict] = []
    for pos, r in enumerate(sel_rows, start=1):
        pg, vol = r["page"], r.get("vol", "")
        # local_no는 선택 범위와 무관하게 고정한다(위 build_page_index 주석의 사고 참조).
        li = (page_index or {}).get(row_key(r), pos)
        pdf = _path_of(r)
        gold = _gold_of(r)
        prog["cur"] += 1
        elapsed = time.time() - prog["t0"]
        eta = (elapsed / prog["cur"]) * (prog["total"] - prog["cur"]) if prog["cur"] else 0
        bar(prog["cur"], prog["total"], ok=prog["ok"], review=prog["review"], blocked=prog["blocked"],
            fail=prog["fail"], to=prog["to"], eta=eta, label=f"{subject} p{pg}")

        if (vol, pg) in done:  # 재개: 이미 완료
            page_states.append(done[(vol, pg)])
            prog["ok"] += 1
            continue

        render_page(pdf, input_dir, li)
        # ★ 2026-08-22 — 파일명에 권을 넣는다. 종전에는 두 권이 같은 이름으로 덮어썼다.
        shutil.copy(pdf, input_dir / (f"original_{vol}_p{pg}.pdf" if vol else f"original_p{pg}.pdf"))
        task = PageTask(job_id=job_id, page_no=li, total_pages=len(sel_rows),
                        pdf_data=pdf.read_bytes(), mode="c", source_text="")
        t0 = time.time()
        # ★ 2026-08-22 — run_state에 권을 **명시로** 적는다(eval 제안). 채점기·분석 스크립트가
        #   권을 읽을 수 있어야 한다. 오늘 사고가 커진 이유가 권이 어디에도 안 적혀 있어서였다.
        rec = {"page": pg, "vol": vol, "local_no": li, "gold": str(gold),
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
            # ★ NEEDS_REVIEW를 blocked로 세면 안 된다. 점자를 정상 생성하고 검토 플래그만
            #   붙은 상태라, 초안 생성기에선 정상 결과다. 한데 묶었더니 진행바가 "blk18"로
            #   찍혀 44%가 막힌 것처럼 보였다(2026-07-17). BLOCKED(C1·C7 등)만 blocked다.
            prog[{"COMPLETED": "ok", "NEEDS_REVIEW": "review"}.get(rec["status"], "blocked")] += 1
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
        # 캡셔닝을 끄고 돈 런이면 남긴다 — 나중에 이 산출물로 시각 축을 재는 사고를 막는다.
        "caption_disabled": os.environ.get("SEMOJUM_NO_CAPTION") == "1",
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


def empty_caption_tally(summaries: list[dict]) -> tuple[int, int]:
    """(시각요소 수, 빈 캡션 수). 런 밖에서도 같은 잣대로 다시 세려고 함수로 뺐다."""
    cap_tot = cap_fail = 0
    for s in summaries:
        for p in s["pages"]:
            for f in (STORAGE / s["job_id"] / "temp" /
                      f"page_{p['local_no']:03d}" / "data").glob("*_txt_result.json"):
                try:
                    els = json.loads(f.read_text(encoding="utf-8")).get("elements", [])
                except (OSError, ValueError):
                    continue
                for e in els:
                    if e.get("type") in ("image", "cartoon", "chart_graph", "diagram"):
                        cap_tot += 1
                        cap_fail += "CAPTION_FAILED" in (e.get("flags") or [])
    return cap_tot, cap_fail


# ── main ─────────────────────────────────────────────────────────────────
def main():
    ap = argparse.ArgumentParser(description="Semojum V2 코퍼스 러너(mode c)")
    ap.add_argument("--corpus", choices=["frozen", "2027"], default="frozen",
                    help="frozen=기존 동결 코퍼스 · 2027=신규 12권")
    ap.add_argument("--split", default=None,
                    help="frozen: dev|val|test · 2027: dev-2027|val-2027|holdout-2027")
    ap.add_argument("--subjects", default=None, help="과목 한정(쉼표구분)")
    ap.add_argument("--limit", type=int, default=None, help="과목당 페이지 상한")
    ap.add_argument("--purposive", action="store_true", help="시각요소 풍부 페이지 우선 선택")
    ap.add_argument("--tag", default=None, help="job 태그(기본 split 또는 custom)")
    ap.add_argument("--reuse", action="store_true", help="추출 캐시 보존, opt→braille만 재실행")
    ap.add_argument("--force", action="store_true", help="완료 페이지도 재실행")
    ap.add_argument("--no-caption", action="store_true",
                    help="시각자료 캡셔닝을 끄고 돈다(생략 처리). 기호 층 A/B용 — "
                         "이 산출물로 시각 축을 재면 안 된다. run_state와 응답 메타에 표시된다")
    args = ap.parse_args()
    if getattr(args, "no_caption", False):
        os.environ["SEMOJUM_NO_CAPTION"] = "1"      # result_builder가 이걸 본다
        print("⚠ 캡셔닝 끔 — 시각 요소는 생략 처리로 나간다. 이 산출물로 시각 축을 재지 말 것.")

    if not os.environ.get("MINERU_BIN"):
        print("⚠ MINERU_BIN 미설정 — STANDARD 라우팅 페이지는 빈 추출이 될 수 있음.")

    # ★ 캡셔닝 키 사전 점검(2026-08-10). 키가 없으면 anthropic 클라이언트가 요청을 보내기도
    #   전에 TypeError("Could not resolve authentication method")로 죽고, _do_caption이
    #   요소를 살리려 빈 캡션 + CAPTION_FAILED로 넘긴다 — 페이지 status는 NEEDS_REVIEW라
    #   러너 요약만 보면 정상으로 보인다. 실제 사고: sub400-dev2027(2026-08-06, 816쪽)이
    #   이 상태로 3.5시간을 돌아 시각요소 371/371이 전부 빈 캡션이 됐고, 그 캐시로 잰
    #   "시각자료 26.1%"는 캡션 품질이 아니라 스텁 껍데기를 재고 있었다.
    #   키는 .env가 아니라 셸 환경변수로 들어온다(운영 .env에 ANTHROPIC_API_KEY 없음).
    #   워크트리에서 돌릴 때 셸이 프로필을 안 읽으면 그대로 재현된다.
    if os.environ.get("CAPTION_BACKEND", "anthropic") == "anthropic":
        from app.core.config import config as _cfg
        if not _cfg.anthropic_api_key:
            print("⚠ ANTHROPIC_API_KEY 없음 — 시각자료 캡션이 **전부** 빈다. "
                  "이 런은 시각 축 채점에 쓸 수 없다. (export ANTHROPIC_API_KEY=…)")

    # ★ 영구 MinerU 서비스 연결. ensure_started는 main.py(서버 모드)만 부르고 있어서
    #   오프라인 러너는 get_url()=None → 페이지마다 vLLM 엔진을 새로 띄웠다(기동 ~45s/페이지,
    #   2026-07-17 실측: api-url 사용 0회·자체 기동 31회). MINERU_API_URL이 있으면 health만
    #   확인하고 즉시 연결, 없으면 자동 기동을 시도한다(실패해도 CLI 폴백으로 동작은 한다).
    from app.ai.parser import mineru_service
    url = mineru_service.ensure_started()
    print(f"MinerU 서비스: {url or 'CLI 폴백(페이지마다 엔진 기동 — 느림)'}")

    rows = load_manifest(args.corpus)
    index_rows(rows)
    subjects = set(args.subjects.split(",")) if args.subjects else None
    sel = select(rows, args.split, subjects, args.limit, args.purposive)
    page_index = build_page_index(rows, args.split, subjects)
    if not sel:
        print("선택된 페이지 없음."); return
    tag = args.tag or args.split or "custom"

    total = sum(len(v) for v in sel.values())
    print(f"=== 코퍼스 러너 tag={tag} mode=c | 과목 {len(sel)} · 페이지 {total} ===")
    for sub, rs in sorted(sel.items()):
        # ★ 라벨 규칙 10 — 뽑은 수와 **유니크 수**를 함께 찍는다. 갈리면 키가 모자란 것이다.
        uniq = len({row_key(r) for r in rs})
        upg = len({r["page"] for r in rs})
        print(f"  {sub:<8} {len(rs)}p (유니크 {uniq} · 쪽번호 {upg}): "
              f"{' '.join(r['page'] for r in rs)}")
    print("-" * 60)

    prog = {"cur": 0, "total": total, "ok": 0, "review": 0, "blocked": 0, "fail": 0, "to": 0, "t0": time.time()}
    summaries = []
    for sub in sorted(sel):
        s = asyncio.run(run_subject(sub, sel[sub], tag, reuse=args.reuse,
                                    force=args.force, prog=prog,
                                    page_index=page_index))
        summaries.append(s)
    print()  # 상태바 줄바꿈
    print("-" * 60)
    print(f"완료: COMPLETED{prog['ok']} NEEDS_REVIEW{prog['review']} BLOCKED{prog['blocked']} fail{prog['fail']} "
          f"timeout{prog['to']} / {total}  ({int(time.time()-prog['t0'])}s)")
    # ★ MinerU 조용한 폴백 집계(2026-08-08). 추출이 실패·타임아웃하면 파이프라인이
    #   텍스트레이어 폴백으로 내려가는데, 그 경고는 WARNING이라 러너 로그에 안 찍히고
    #   페이지 status는 COMPLETED/NEEDS_REVIEW로 남는다 — 런이 조용히 다른 물건이 된다.
    #   실제 사고: 한 GPU에 라운드 3개를 동시에 물렸더니 무거운 쪽이 60초 상한을 넘겨
    #   B면 33쪽·C면 42쪽이 폴백으로 떨어졌고, 그 차이가 A/B 판정에 ±1p로 섞여 들어갔다.
    #   폴백이 1쪽이라도 있으면 그 런은 다른 런과 비교하면 안 된다.
    fb = [(s["job_id"], p["page"]) for s in summaries for p in s["pages"]
          if p.get("tier") not in (None, "ZERO")
          and not list((STORAGE / s["job_id"] / "temp" /
                        f"page_{p['local_no']:03d}" / "mineru_raw").glob("*_content_list.json"))]
    if fb:
        print(f"⚠ MinerU 추출 폴백 {len(fb)}쪽 — 이 런은 A/B 비교에 쓰지 말 것"
              f" (동시 실행·GPU 경합 확인): {[f'{j.split(chr(45))[-1]} p{p}' for j, p in fb[:10]]}")

    # ★ 빈 캡션 집계(2026-08-10). 위 폴백 집계와 같은 이유다 — 캡셔닝이 실패해도 요소는
    #   빈 캡션 + CAPTION_FAILED로 살아남고(불변규칙 1) 페이지는 NEEDS_REVIEW로 끝나서,
    #   러너 요약만 보면 정상 런과 구별이 안 된다. 빈 캡션이 많으면 시각 축 점수는
    #   캡션 품질이 아니라 '생략' 스텁을 재는 것이 되므로 그 런은 시각 축에 못 쓴다.
    #   원인 둘 다 조용하다: (1) 키 없음 → 전량 실패, (2) thinking 미차단 → 산발 빈 응답.
    cap_tot, cap_fail = empty_caption_tally(summaries)
    if cap_fail:
        pct = cap_fail / cap_tot
        print(f"{'⚠⚠' if pct >= 0.2 else '⚠'} 빈 캡션 {cap_fail}/{cap_tot}개 ({pct:.0%})"
              + (" — 시각 축 채점에 쓰지 말 것. ANTHROPIC_API_KEY·캡셔닝 로그 확인"
                 if pct >= 0.2 else " — 산발 실패, 로그 확인"))

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
