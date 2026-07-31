"""배포 서버 자체 점검 — BE 연동 전에 우리 쪽만으로 결과가 나오는지 확인한다.

BE가 붙는 것과 **같은 경로**로 때린다: gRPC over TLS, authority 오버라이드,
실제 교과서 PDF 1장씩. 그래서 "서버가 떴다"가 아니라 "BE가 받을 응답이 쓸 만한가"를 본다.

점검 항목
  1. 연결      TLS 핸드셰이크 · authority 검증
  2. 계약      contents == drafts[selected_idx].contents · rule_trail 좌표 범위
               · 32칸 초과 없음 · 빈 응답 없음
  3. 내용      정답 BRL 대비 셀 포함률(스모크용 근사 — 정식 채점은 tools/kpi/kpi_v2.py)
  4. 성능      페이지별 소요시간 · 서버 보고 processing_time_ms
  5. 품질      status 분포 · C(치명)/R(검토) 플래그 집계

사용 (작업 디렉토리 = code/AI/)
  python test/server_selftest.py                      # dev 6페이지, localhost
  python test/server_selftest.py --pages 12
  python test/server_selftest.py --host 172.31.47.101:50051   # BE 관점에서 원격 확인
  python test/server_selftest.py --out /tmp/selftest.json

※ dev split만 쓴다. test 120쌍은 동결 홀드아웃이라 스모크에 쓰지 않는다.
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
import time
from collections import Counter
from pathlib import Path

AI = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(AI))
sys.path.insert(0, str(AI / "test"))

import grpc                                                    # noqa: E402
from protos.generated import braille_service_pb2 as pb         # noqa: E402
from protos.generated import braille_service_pb2_grpc as pbg   # noqa: E402
from corpus_metrics import gold_unicode, cells_only            # noqa: E402

INPUT = AI / "test/test_data/input"
MANIFEST = AI / "test/test_data/dataset/split_manifest.csv"
CERT = Path("/etc/ssl/semojum/server.crt")
MAX_MSG = 20 * 1024 * 1024
CELL_W = 32
VISUAL = {"image", "cartoon", "chart_graph", "table", "diagram"}


def pick_pages(n: int) -> list[tuple[str, str]]:
    """dev split에서 과목을 골고루 섞어 n장. 과목 순환이라 한 과목에 쏠리지 않는다."""
    by_sub: dict[str, list[str]] = {}
    with open(MANIFEST, encoding="utf-8") as f:
        for r in csv.DictReader(f):
            if r["split"] == "dev":
                by_sub.setdefault(r["subject"], []).append(r["page"])
    subs = sorted(by_sub)
    out: list[tuple[str, str]] = []
    i = 0
    while len(out) < n and subs:
        s = subs[i % len(subs)]
        pages = by_sub[s]
        k = i // len(subs)
        if k < len(pages):
            out.append((s, pages[k]))
        i += 1
        if i > len(subs) * 60:
            break
    return out


def check_element(el, errs: list[str], where: str) -> None:
    """BE proto 계약 검증 — 여기서 걸리면 BE 화면이 깨진다."""
    cs = list(el.contents)
    ds = list(el.drafts)

    if el.is_blocked:
        return                                   # 처리 불가 요소는 계약 검사 제외

    if ds:
        si = el.selected_idx
        if not 0 <= si < len(ds):
            errs.append(f"{where} selected_idx={si}가 drafts({len(ds)}) 범위 밖")
        elif cs != list(ds[si].contents):
            errs.append(f"{where} contents != drafts[{si}].contents")
        if any(not d.label for d in ds):
            errs.append(f"{where} 라벨 없는 초안 있음")

    for t in el.rule_trail:
        if t.line_no >= 0 and t.line_no >= len(cs):
            errs.append(f"{where} rule_trail.line_no={t.line_no} ≥ contents({len(cs)})")
            break

    for j, ln in enumerate(cs):
        if "\n" in ln:
            errs.append(f"{where} contents[{j}]에 개행 — 줄 배열 계약 위반")
            break
        if len(ln) > CELL_W:
            errs.append(f"{where} contents[{j}] {len(ln)}칸 (32칸 초과)")
            break


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="127.0.0.1:50051")
    ap.add_argument("--authority", default="semo-jum.com")
    ap.add_argument("--cert", default=str(CERT))
    ap.add_argument("--pages", type=int, default=6)
    ap.add_argument("--timeout", type=float, default=300.0)
    ap.add_argument("--out", default="storage/selftest.json")
    ap.add_argument("--insecure", action="store_true",
                    help="TLS 없이 붙는다(로컬 .env가 TLS_ENABLED=false일 때)")
    ap.add_argument("--reuse", action="store_true",
                    help="같은 job_id를 다시 써서 추출 캐시를 재사용(계약만 빠르게 볼 때)")
    a = ap.parse_args()

    # job_id를 실행마다 다르게 준다. 같은 id면 pipeline이 경계 파일을 재사용해
    # 추출을 통째로 건너뛰고(0.2초) '빠르다'는 착시를 만든다 — 실제 경로가 안 재진다.
    run_tag = "reuse" if a.reuse else f"r{int(time.time())}"

    pages = pick_pages(a.pages)
    print(f"=== AI 서버 자체 점검 ===")
    print(f"  대상   {a.host}  (authority={a.authority})")
    print(f"  페이지 {len(pages)}장 · dev split")
    print(f"  인증서 {'(사용 안 함 — --insecure)' if a.insecure else a.cert}")
    print("-" * 72)

    opts = [("grpc.max_receive_message_length", MAX_MSG),
            ("grpc.max_send_message_length", MAX_MSG)]
    if a.insecure:
        ch = grpc.insecure_channel(a.host, options=opts)
    else:
        cert_p = Path(a.cert)
        if not cert_p.exists():
            print(f"★ 인증서를 못 찾았다: {cert_p}\n"
                  f"  TLS를 안 쓰는 환경이면 --insecure 를 붙이세요.")
            sys.exit(1)
        cred = grpc.ssl_channel_credentials(cert_p.read_bytes())
        ch = grpc.secure_channel(
            a.host, cred, options=opts + [("grpc.ssl_target_name_override", a.authority)])
    try:
        grpc.channel_ready_future(ch).result(timeout=20)
    except grpc.FutureTimeoutError:
        print("★ 연결 실패 — 서버가 안 떴거나 TLS/authority 불일치")
        sys.exit(1)
    stub = pbg.BrailleServiceStub(ch)
    print("연결 OK (TLS 핸드셰이크 통과)\n")

    rows, all_errs = [], []
    status_c, crit_c, flag_c, type_c = Counter(), Counter(), Counter(), Counter()
    tier_c = Counter()
    flag_msgs: dict[str, str] = {}     # 플래그 종류별 대표 메시지 1개
    confs: list[float] = []

    print(f"{'과목':<9}{'쪽':>4} {'티어':<9}{'상태':<14}{'요소':>5}{'시각':>5}"
          f"{'초':>7}{'정답대비':>9}")
    print("-" * 78)

    for subj, pg in pages:
        pdf = INPUT / f"input_{subj}_page{pg}.pdf"
        if not pdf.exists():
            print(f"{subj:<8}{pg:>5}  PDF 없음 — 건너뜀")
            continue
        req = pb.BrailleRequest(job_id=f"selftest-{run_tag}-{subj}-{pg}", page_no=1,
                                total_pages=1, pdf_data=pdf.read_bytes(),
                                mode="c", source_text="")
        t0 = time.time()
        try:
            res = stub.ProcessPage(req, timeout=a.timeout)
        except grpc.RpcError as e:
            print(f"{subj:<8}{pg:>5}  RPC 실패 {e.code().name}")
            all_errs.append(f"{subj} p{pg}: RPC {e.code().name}")
            rows.append({"subject": subj, "page": pg, "rpc_error": e.code().name})
            continue
        el_s = time.time() - t0

        errs: list[str] = []
        bl = list(res.braille_text_list)
        n_vis = 0
        our_cells = []
        for el in bl:
            type_c[el.type] += 1
            confs.append(el.ocr_confidence)
            if el.type in VISUAL:
                n_vis += 1
            check_element(el, errs, f"{subj} p{pg} #{el.order}({el.type})")
            our_cells.append(cells_only("".join(el.contents)))

        if not bl:
            errs.append(f"{subj} p{pg}: braille_text_list 비어 있음")

        gold = gold_unicode(subj, pg)
        cover = None
        if gold:
            g = cells_only(gold)
            hit = sum(len(c) for c in our_cells if c and c in g)
            tot = sum(len(c) for c in our_cells) or 1
            cover = hit / tot

        status_c[res.status] += 1
        tier = res.processing_meta.routing_tier_used or "?"
        tier_c[tier] += 1
        for c in res.quality_report.critical_errors:
            crit_c[c.type] += 1
            flag_msgs.setdefault(c.type, c.message)
        for fl in res.quality_report.review_flags:
            flag_c[fl.type] += 1
            flag_msgs.setdefault(fl.type, fl.message)
        all_errs += errs

        cov_s = f"{cover*100:>7.1f}%" if cover is not None else "     — "
        mark = "" if not errs else f"  ★계약 {len(errs)}"
        print(f"{subj:<9}{pg:>4} {tier:<9}{res.status:<14}{len(bl):>5}{n_vis:>5}"
              f"{el_s:>7.1f}{cov_s}{mark}")

        rows.append({
            "subject": subj, "page": pg, "status": res.status,
            "elements": len(bl), "visual": n_vis,
            "elapsed_s": round(el_s, 2),
            "server_ms": res.processing_meta.processing_time_ms,
            "routing_tier": tier,
            "gold_coverage": round(cover, 4) if cover is not None else None,
            "critical": [c.type for c in res.quality_report.critical_errors],
            "flags": [f.type for f in res.quality_report.review_flags],
            "contract_errors": errs,
        })

    print("-" * 72)
    ok = [r for r in rows if "rpc_error" not in r]
    times = [r["elapsed_s"] for r in ok]
    covs = [r["gold_coverage"] for r in ok if r.get("gold_coverage") is not None]
    print(f"\n【결과】 {len(ok)}/{len(rows)}장 응답")
    print(f"  상태      {dict(status_c)}")
    if times:
        print(f"  소요      평균 {sum(times)/len(times):.1f}초 · "
              f"최소 {min(times):.1f} · 최대 {max(times):.1f}")
    if covs:
        print(f"  정답대비  평균 {sum(covs)/len(covs)*100:.1f}% "
              f"(요소 셀열이 정답 페이지 안에 그대로 있는 비율 — 스모크 근사)")
    print(f"  라우팅    {dict(tier_c)}"
          f"   ← ZERO=텍스트레이어 직접추출(MinerU 미사용) / STANDARD·QUALITY=MinerU")
    print(f"  요소유형  {dict(type_c.most_common(8))}")
    if confs:
        lo = sum(1 for c in confs if c < 0.85)
        print(f"  신뢰도    평균 {sum(confs)/len(confs):.2f} · 0.85 미만 {lo}/{len(confs)}개")
    if crit_c:
        print(f"  치명(C)   {dict(crit_c)}")
    if flag_c:
        print(f"  검토(R)   {dict(flag_c)}")
    if flag_msgs:
        print("  플래그 사유(종류별 예시)")
        for k in sorted(flag_msgs):
            print(f"    · {k}: {flag_msgs[k][:70]}")

    print(f"\n【계약 검증】 {'통과 — 위반 0건' if not all_errs else f'★ 위반 {len(all_errs)}건'}")
    for e in all_errs[:12]:
        print(f"    · {e}")
    if len(all_errs) > 12:
        print(f"    … 외 {len(all_errs)-12}건")

    out = Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({
        "host": a.host, "authority": a.authority, "pages": len(rows),
        "status": dict(status_c), "critical": dict(crit_c), "flags": dict(flag_c),
        "types": dict(type_c), "contract_errors": all_errs, "rows": rows,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n상세: {out}")

    sys.exit(1 if (all_errs or len(ok) != len(rows)) else 0)


if __name__ == "__main__":
    main()
