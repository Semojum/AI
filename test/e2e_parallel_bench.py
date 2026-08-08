"""E2E 병렬 처리 시간 측정 — 동시 N인이 M쪽을 올릴 때 무엇이 얼마나 걸리는가.

BE가 실제로 하는 것을 그대로 흉내낸다: 쪽마다 단일 페이지 PDF를 gRPC `ProcessPage`로
보내고, 사용자마다 **순차**로 다음 쪽을 보낸다(사람 한 명은 한 번에 한 쪽만 올린다).
사용자끼리는 동시다.

측정하는 것
  · 쪽당 소요시간(사용자별·전체 분포)
  · 파트별 점유 구간 — 서버가 `storage/metrics/ai_metrics.jsonl`에 싣는 `stages`를 읽어
    "어느 자원이 언제 붐볐는지"를 겹쳐 그린다
  · 배압 — `RESOURCE_EXHAUSTED`로 튕긴 횟수
  · 외부 LLM 분당 상한 대기(`llm_wait_s`)

쓰는 법
    python test/e2e_parallel_bench.py --addr 127.0.0.1:50051 --users 2 --pages 10
    python test/e2e_parallel_bench.py --addr 172.31.47.101:50051 --users 2 --pages 10 \
        --metrics /srv/semojum/AI/storage/metrics/ai_metrics.jsonl

⚠ 이 스크립트는 **서버를 띄우지 않는다**. 측정 대상 서버가 이미 떠 있어야 한다.
⚠ 실호출이라 외부 API 과금이 발생한다. 쪽 수를 먼저 확인할 것.
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

AI = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(AI))

import grpc                                                       # noqa: E402

from protos.generated import braille_service_pb2 as pb            # noqa: E402
from protos.generated import braille_service_pb2_grpc as pb_grpc  # noqa: E402


def _load_pdfs(src: Path, n: int) -> list[tuple[str, bytes]]:
    """측정용 단일 페이지 PDF n개. 파일이 모자라면 있는 만큼 돌려쓴다."""
    files = sorted(p for p in src.glob("*.pdf"))
    if not files:
        raise SystemExit(f"PDF가 없다: {src}")
    return [(files[i % len(files)].name, files[i % len(files)].read_bytes())
            for i in range(n)]


def _purge_jobs(root: Path) -> int:
    """이전 측정이 남긴 `bench-u*` 잡을 지운다.

    ★ 안 지우면 측정이 통째로 거짓말이 된다. 파이프라인은 경계 파일
      (`temp/page_NNN/data/*_txt_result.json`)이 이미 있으면 **추출을 건너뛴다**.
      실제로 재실행 때 한 쪽이 24.6초 → 0.55초로 나왔다(추출을 안 한 것).
    """
    import shutil

    n = 0
    for d in sorted(root.glob("bench-u*")):
        shutil.rmtree(d, ignore_errors=True)
        n += 1
    return n


def _channel(addr: str, cert: str, sni: str):
    """측정 대상 채널. 운영 서버는 TLS라 인증서를 줘야 붙는다.

    ★ 인증서 CN·SAN이 도메인(`semo-jum.com`)이라 IP로 붙으면 TLS가 거절한다
      ("Peer name … is not in peer certificate"). `sni`로 이름을 맞춰 준다.
    """
    opts = [("grpc.max_send_message_length", 32 * 1024 * 1024),
            ("grpc.max_receive_message_length", 32 * 1024 * 1024)]
    if not cert:
        return grpc.insecure_channel(addr, options=opts)
    with open(cert, "rb") as f:
        creds = grpc.ssl_channel_credentials(root_certificates=f.read())
    if sni:
        opts.append(("grpc.ssl_target_name_override", sni))
    return grpc.secure_channel(addr, creds, options=opts)


def _run_user(addr: str, uid: int, pdfs: list[tuple[str, bytes]],
              mode: str, t_origin: float, cert: str = "", sni: str = "") -> list[dict]:
    """사용자 한 명 — 쪽을 **순차**로 올린다. 사용자끼리는 동시."""
    rows = []
    ch = _channel(addr, cert, sni)
    stub = pb_grpc.BrailleServiceStub(ch)
    job = f"bench-u{uid}"
    for i, (name, data) in enumerate(pdfs, 1):
        req = pb.BrailleRequest(job_id=job, page_no=i, total_pages=len(pdfs),
                                pdf_data=data, mode=mode)
        t0 = time.monotonic()
        row = {"user": uid, "page": i, "file": name,
               "start_s": round(t0 - t_origin, 3)}
        try:
            resp = stub.ProcessPage(req, timeout=300)
            row.update(status=resp.status,
                       elements=len(resp.braille_text_list) or len(resp.text_list),
                       server_ms=resp.processing_meta.processing_time_ms,
                       tier=resp.processing_meta.routing_tier_used)
        except grpc.RpcError as exc:
            row.update(status=f"RPC_{exc.code().name}", elements=0, server_ms=0, tier="")
        row["wall_s"] = round(time.monotonic() - t0, 3)
        row["end_s"] = round(time.monotonic() - t_origin, 3)
        rows.append(row)
        print(f"  u{uid} p{i:<3} {row['status']:<20} {row['wall_s']:>6.2f}s "
              f"(서버 {row['server_ms']/1000:>5.2f}s · 요소 {row['elements']})", flush=True)
    ch.close()
    return rows


def _read_metrics(path: Path, since: float) -> list[dict]:
    """서버 메트릭에서 이번 측정 구간의 레코드만 고른다."""
    if not path.exists():
        print(f"  (메트릭 없음: {path} — 파트별 점유 구간은 생략)")
        return []
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            r = json.loads(line)
        except json.JSONDecodeError:
            continue
        if r.get("job_id", "").startswith("bench-u"):
            out.append(r)
    return out[-int(since):] if since else out


def _report(rows: list[dict], metrics: list[dict], users: int, pages: int) -> None:
    ok = [r for r in rows if r["status"] in ("COMPLETED", "NEEDS_REVIEW")]
    exhausted = [r for r in rows if "RESOURCE_EXHAUSTED" in r["status"]]
    walls = sorted(r["wall_s"] for r in ok)
    total = max((r["end_s"] for r in rows), default=0)

    print(f"\n{'='*62}\n동시 {users}인 × {pages}쪽 = {len(rows)}쪽\n{'='*62}")
    print(f"  전체 소요        {total:>7.1f}s")
    print(f"  성공 / 배압튕김  {len(ok)} / {len(exhausted)}")
    if walls:
        print(f"  쪽당 소요        중앙 {statistics.median(walls):>5.1f}s · "
              f"평균 {sum(walls)/len(walls):>5.1f}s · "
              f"p95 {walls[int(len(walls)*.95)]:>5.1f}s · 최대 {walls[-1]:>5.1f}s")
        print(f"  처리량           {len(ok)/total*60:>7.1f} 쪽/분  "
              f"(사용자당 {len(ok)/total*60/users:.1f} 쪽/분)")

    if not metrics:
        return
    # 파트별 점유 — 여러 쪽의 구간을 합쳐 "그 파트가 총 몇 초를 붙잡았나"를 본다.
    agg: dict[str, list[float]] = {}
    for m in metrics:
        for s in m.get("stages") or []:
            agg.setdefault(s["label"], []).append(s["ms"] / 1000)
    if agg:
        print(f"\n  파트별 점유 (쪽당 초)")
        print(f"    {'파트':<12}{'중앙':>7}{'평균':>8}{'최대':>8}{'합계':>9}{'비중':>8}")
        print("    " + "─" * 50)
        grand = sum(sum(v) for v in agg.values()) or 1
        for lbl, v in sorted(agg.items(), key=lambda kv: -sum(kv[1])):
            v = sorted(v)
            print(f"    {lbl:<12}{statistics.median(v):>7.2f}{sum(v)/len(v):>8.2f}"
                  f"{v[-1]:>8.2f}{sum(v):>9.1f}{sum(v)/grand*100:>7.1f}%")
    wait = sum(m.get("llm_wait_s", 0) for m in metrics)
    print(f"\n  외부 LLM 상한 대기 총 {wait:.1f}s "
          f"{'← 상한이 물렸다(값을 확인할 것)' if wait > 1 else '(상한 미발동 = 정상)'}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--addr", default="127.0.0.1:50051")
    ap.add_argument("--users", type=int, default=2)
    ap.add_argument("--pages", type=int, default=10)
    ap.add_argument("--mode", default="c")
    ap.add_argument("--pdf-dir", default=str(AI / "test/test_data/input"))
    ap.add_argument("--metrics", default=str(AI / "storage/metrics/ai_metrics.jsonl"))
    ap.add_argument("--out", default=str(AI / "storage/metrics/e2e_bench.json"))
    ap.add_argument("--tls-cert", default="",
                    help="서버 인증서. 주면 TLS로 붙는다(운영 서버는 필수)")
    ap.add_argument("--tls-name", default="",
                    help="인증서 CN·SAN. IP로 붙을 때 이름을 맞춘다 (예: semo-jum.com)")
    ap.add_argument("--jobs-dir", default=str(AI / "storage/jobs"),
                    help="측정 전 지울 bench 잡 위치. 원격 서버 측정 시엔 서버에서 지울 것")
    a = ap.parse_args()

    pdfs = _load_pdfs(Path(a.pdf_dir), a.pages)
    print(f"대상 {a.addr} · 동시 {a.users}인 × {a.pages}쪽 (mode {a.mode})")
    print(f"PDF {len(set(n for n, _ in pdfs))}종 사용")
    jobs_root = Path(a.jobs_dir)
    if jobs_root.exists():
        n = _purge_jobs(jobs_root)
        print(f"이전 bench 잡 {n}개 삭제 (경계 파일이 남으면 추출을 건너뛰어 측정이 거짓이 된다)")
    else:
        print(f"⚠ {jobs_root} 없음 — 원격 서버라면 **서버에서** bench-u* 잡을 먼저 지울 것")
    print()

    t_origin = time.monotonic()
    with ThreadPoolExecutor(max_workers=a.users) as pool:
        futs = [pool.submit(_run_user, a.addr, u + 1, pdfs, a.mode, t_origin,
                            a.tls_cert, a.tls_name)
                for u in range(a.users)]
        rows = [r for f in futs for r in f.result()]

    metrics = _read_metrics(Path(a.metrics), a.users * a.pages)
    _report(rows, metrics, a.users, a.pages)

    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    Path(a.out).write_text(json.dumps({"rows": rows, "metrics": metrics},
                                      ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\n  원자료 → {a.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
