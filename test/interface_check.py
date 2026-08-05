"""인터페이스 전수 점검 — BE가 건드릴 수 있는 표면을 전부 때려본다.

server_selftest.py가 "정상 요청의 결과가 쓸 만한가"를 본다면, 이 파일은
**"인터페이스가 계약대로 동작하는가"**를 본다. 정상 경로뿐 아니라
거부해야 할 것을 제대로 거부하는지까지 확인한다.

  A. 연결·TLS   정상 접속 / authority 불일치 거부 / 평문 거부 / REST https 강제
  B. gRPC       mode a·b·c 필드 채움 · id 정합 · 계약 불변식 · 잘못된 입력 방어
  C. REST       /health · /models/status · /finalize 왕복(32칸·26줄) · 없는 경로

사용 (작업 디렉토리 = code/AI/)
  python test/interface_check.py
  python test/interface_check.py --host 172.31.47.101:50051 --rest https://172.31.47.101:8080

판정: 하나라도 실패하면 exit 1. BE 연동 전 게이트로 쓴다.
"""
from __future__ import annotations

import argparse
import sys
import warnings
from pathlib import Path

AI = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(AI))
sys.path.insert(0, str(AI / "test"))

import grpc                                                    # noqa: E402
import requests                                                # noqa: E402
from protos.generated import braille_service_pb2 as pb         # noqa: E402
from protos.generated import braille_service_pb2_grpc as pbg   # noqa: E402
from app.ai.braille.constants import COLS, ROWS                 # noqa: E402

warnings.filterwarnings("ignore")          # 자체 서명 인증서 경고
CERT = "/etc/ssl/semojum/server.crt"
MAX_MSG = 20 * 1024 * 1024
CELL_W = COLS      # 32칸 (BBPG 1장1절3)
PAGE_ROWS = ROWS   # 26줄 — 단면은 본문 25 + 페이지행 1. '25줄'이 아니다
SAMPLE_TEXT = "다음 그림은 2024년 자료이다. 빈칸 □ 에 알맞은 말을 쓰시오."

RESULTS: list[tuple[str, str, bool, str]] = []   # (구역, 항목, 통과, 메모)


def rec(sec: str, name: str, ok: bool, note: str = "") -> bool:
    RESULTS.append((sec, name, ok, note))
    return ok


def chan(host: str, cert: str | None, authority: str | None):
    opts = [("grpc.max_receive_message_length", MAX_MSG),
            ("grpc.max_send_message_length", MAX_MSG)]
    if cert is None:
        return grpc.insecure_channel(host, options=opts)
    if authority:
        opts.append(("grpc.ssl_target_name_override", authority))
    return grpc.secure_channel(host, grpc.ssl_channel_credentials(
        Path(cert).read_bytes()), options=opts)


def reachable(ch, timeout: float = 8.0) -> bool:
    try:
        grpc.channel_ready_future(ch).result(timeout=timeout)
        return True
    except grpc.FutureTimeoutError:
        return False


# ── 계약 불변식(BE proto) ────────────────────────────────────────────────
# ⚠ 줄 배열·32칸 규칙은 `braille_text_list`에만 적용한다.
#   `text_list.contents`는 점자가 아니라 **묵자 원문 1항목**이라(pipeline `_build_response`)
#   문단 개행이 들어 있는 게 정상이다. 여기에 점자 규칙을 대면 오탐이 난다.
def contract_errors(res) -> list[str]:
    errs: list[str] = []
    for el in list(res.braille_text_list):
        w = f"#{el.order}({el.type})"
        if el.is_blocked:
            continue
        cs, ds = list(el.contents), list(el.drafts)
        if ds:
            if not 0 <= el.selected_idx < len(ds):
                errs.append(f"{w} selected_idx 범위 밖")
            elif cs != list(ds[el.selected_idx].contents):
                errs.append(f"{w} contents != drafts[selected_idx].contents")
            if any(not d.label for d in ds):
                errs.append(f"{w} 라벨 없는 초안")
        for t in el.rule_trail:
            if t.line_no >= 0 and t.line_no >= len(cs):
                errs.append(f"{w} rule_trail.line_no 범위 초과")
                break
        for j, ln in enumerate(cs):
            if "\n" in ln:
                errs.append(f"{w} contents[{j}] 개행 포함")
                break
            if len(ln) > CELL_W:
                errs.append(f"{w} contents[{j}] {len(ln)}칸 초과")
                break
    return errs


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="127.0.0.1:50051")
    ap.add_argument("--rest", default="https://127.0.0.1:8080")
    ap.add_argument("--authority", default="semo-jum.com")
    ap.add_argument("--cert", default=CERT)
    ap.add_argument("--pdf", default=None, help="시험용 단일 페이지 PDF")
    ap.add_argument("--timeout", type=float, default=300.0)
    a = ap.parse_args()

    pdf_path = Path(a.pdf) if a.pdf else (
        AI / "test/test_data/input/input_생물_page004.pdf")
    pdf = pdf_path.read_bytes() if pdf_path.exists() else b""

    print("=== 인터페이스 전수 점검 ===")
    print(f"  gRPC {a.host}   REST {a.rest}   authority={a.authority}")
    print(f"  시험 PDF {pdf_path.name} ({len(pdf):,} bytes)\n")

    # ── A. 연결·TLS ────────────────────────────────────────────────────
    ok_cert = Path(a.cert).exists()
    rec("A 연결", "서버 인증서 파일 존재", ok_cert, a.cert)
    if not ok_cert:
        print("★ 인증서가 없어 진행 불가"); summary(); sys.exit(1)

    ch = chan(a.host, a.cert, a.authority)
    ok = reachable(ch)
    rec("A 연결", "TLS 접속 (정상 인증서 + authority)", ok)
    if not ok:
        print("★ 서버에 못 붙었다"); summary(); sys.exit(1)
    stub = pbg.BrailleServiceStub(ch)

    bad = chan(a.host, a.cert, "wrong-host.example")
    rec("A 연결", "authority 불일치 → 거부", not reachable(bad, 6.0),
        "틀린 이름으로 붙으면 실패해야 정상")

    plain = chan(a.host, None, None)
    plain_ok = reachable(plain, 6.0)
    if plain_ok:                       # 채널은 열려도 RPC가 막히면 정상
        try:
            pbg.BrailleServiceStub(plain).ProcessPage(
                pb.BrailleRequest(job_id="x", page_no=1, total_pages=1,
                                  pdf_data=b"", mode="c"), timeout=8)
            plain_rpc = True
        except grpc.RpcError:
            plain_rpc = False
    else:
        plain_rpc = False
    rec("A 연결", "평문(비TLS) → 거부", not plain_rpc, "TLS 강제 확인")

    try:
        h = requests.get(f"{a.rest}/health", verify=False, timeout=10)
        rec("A 연결", "REST https /health", h.status_code == 200, f"{h.status_code}")
        hj = h.json()
    except Exception as exc:                       # noqa: BLE001
        rec("A 연결", "REST https /health", False, str(exc)[:60]); hj = {}

    try:
        requests.get(f"{a.rest.replace('https://', 'http://')}/health",
                     timeout=6)
        rec("A 연결", "REST 평문 http → 거부", False, "http로 붙어졌다")
    except Exception:                              # noqa: BLE001
        rec("A 연결", "REST 평문 http → 거부", True, "https 강제 확인")

    # ── B. gRPC ────────────────────────────────────────────────────────
    def call(mode: str, *, data: bytes = pdf, text: str = "", jid: str = "ifchk"):
        return stub.ProcessPage(pb.BrailleRequest(
            job_id=f"{jid}-{mode}", page_no=1, total_pages=1,
            pdf_data=data, mode=mode, source_text=text), timeout=a.timeout)

    # mode c — 전 필드
    c = None
    try:
        c = call("c")
        rec("B gRPC", "mode c 응답", True, f"{len(c.braille_text_list)}요소")
        rec("B gRPC", "  job_id 반향", c.job_id == "ifchk-c", c.job_id)
        rec("B gRPC", "  status 값 유효",
            c.status in ("COMPLETED", "NEEDS_REVIEW", "BLOCKED"), c.status)
        rec("B gRPC", "  page_number 반향", c.page_number == 1, str(c.page_number))
        rec("B gRPC", "  processing_meta 채움",
            bool(c.processing_meta.routing_tier_used), c.processing_meta.routing_tier_used)
        rec("B gRPC", "  bounding_box_list 존재", len(c.bounding_box_list) > 0,
            f"{len(c.bounding_box_list)}개")
        rec("B gRPC", "  text_list 존재", len(c.text_list) > 0, f"{len(c.text_list)}개")
        rec("B gRPC", "  braille_text_list 존재", len(c.braille_text_list) > 0,
            f"{len(c.braille_text_list)}개")
        # 2026-08-05: image_resolution(문자열) → image_width·image_height(int) 복원.
        rec("B gRPC", "  image_width·height 채움",
            c.image_width > 0 and c.image_height > 0,
            f"{c.image_width}x{c.image_height}")
        bb_ids = {b.id for b in c.bounding_box_list}
        tl_ids = {t.id for t in c.text_list}
        rec("B gRPC", "  bounding_box ↔ text_list id 정합",
            bool(tl_ids) and tl_ids <= bb_ids,
            f"text_list 중 bbox 없는 것 {len(tl_ids - bb_ids)}개")
        # text_list는 묵자 원문 1항목(점자 아님) — BE가 헷갈리는 자리라 명시 검사한다.
        rec("B gRPC", "  text_list = 묵자 1항목",
            all(len(t.contents) == 1 for t in c.text_list),
            f"항목 수 {sorted({len(t.contents) for t in c.text_list})}")
        rec("B gRPC", "  text_list에 점자 없음",
            not any(any(0x2800 <= ord(ch) <= 0x28FF for ch in "".join(t.contents))
                    for t in c.text_list),
            "묵자만 담겨야 정상")
        errs = contract_errors(c)
        rec("B gRPC", "  계약 불변식(braille만)", not errs,
            "위반 0" if not errs else f"위반 {len(errs)}: {errs[0][:50]}")
        cells = "".join("".join(e.contents) for e in c.braille_text_list)
        rec("B gRPC", "  점자 유니코드 범위",
            bool(cells) and all(0x2800 <= ord(x) <= 0x28FF or x in " \n" for x in cells),
            f"{len(cells):,}자")
    except grpc.RpcError as e:
        rec("B gRPC", "mode c 응답", False, e.code().name)

    # mode a — 점자 없이 레이아웃·텍스트만
    try:
        m = call("a")
        rec("B gRPC", "mode a 응답", True, m.status)
        rec("B gRPC", "  점자 없음(설계)", len(m.braille_text_list) == 0,
            f"{len(m.braille_text_list)}개")
        rec("B gRPC", "  bounding_box·text_list 있음",
            len(m.bounding_box_list) > 0 and len(m.text_list) > 0,
            f"bbox {len(m.bounding_box_list)} · text {len(m.text_list)}")
    except grpc.RpcError as e:
        rec("B gRPC", "mode a 응답", False, e.code().name)

    # mode b — source_text 점역
    try:
        b = call("b", data=b"", text=SAMPLE_TEXT)
        rec("B gRPC", "mode b 응답", True, b.status)
        got = "".join("".join(e.contents) for e in b.braille_text_list)
        rec("B gRPC", "  source_text 점역됨", bool(got.strip()), f"{len(got)}자")
        rec("B gRPC", "  수표(⠼) 삽입", "⠼" in got,
            "숫자 2024가 수표를 달았는가 — C5")
        rec("B gRPC", "  bounding_box 없음(설계)", len(b.bounding_box_list) == 0,
            f"{len(b.bounding_box_list)}개")
        rec("B gRPC", "  계약 불변식", not contract_errors(b))
    except grpc.RpcError as e:
        rec("B gRPC", "mode b 응답", False, e.code().name)

    # 방어 — 잘못된 입력에도 죽지 않아야 한다
    try:
        z = call("c", data=b"")
        rec("B gRPC", "빈 PDF → 크래시 없이 응답", True, z.status)
    except grpc.RpcError as e:
        rec("B gRPC", "빈 PDF → 크래시 없이 응답", False, e.code().name)

    try:
        u = call("zzz")
        rec("B gRPC", "알 수 없는 mode → 기본 처리", True, f"{u.status}")
    except grpc.RpcError as e:
        rec("B gRPC", "알 수 없는 mode → 기본 처리", False, e.code().name)

    try:
        n = call("c", data=b"%PDF-1.4 broken")
        rec("B gRPC", "깨진 PDF → 크래시 없이 응답", True, n.status)
    except grpc.RpcError as e:
        rec("B gRPC", "깨진 PDF → 크래시 없이 응답", False, e.code().name)

    # ── C. REST ────────────────────────────────────────────────────────
    for k in ("status", "grpc_port", "rest_port", "models"):
        rec("C REST", f"/health 필드 {k}", k in hj, str(hj.get(k))[:40])
    rec("C REST", "/health hcxt_loaded", bool(hj.get("models", {}).get("hcxt_loaded")),
        str(hj.get("models", {}).get("hcxt_loaded")))

    try:
        ms = requests.get(f"{a.rest}/models/status", verify=False, timeout=10)
        rec("C REST", "/models/status", ms.status_code == 200, f"{ms.status_code}")
    except Exception as exc:                       # noqa: BLE001
        rec("C REST", "/models/status", False, str(exc)[:60])

    # /finalize 왕복 — BE는 응답 contents를 그대로 되돌려주면 된다
    try:
        if c is None:
            raise RuntimeError("mode c 응답이 없어 왕복 검사 불가")
        blocks = [{"id": e.id, "type": e.type, "heading_level": e.heading_level,
                   "order": e.order, "lines": list(e.contents)}
                  for e in c.braille_text_list[:8]]
        fr = requests.post(f"{a.rest}/finalize", verify=False, timeout=60, json={
            "job_id": "ifchk", "page_no": 1, "total_pages": 1, "blocks": blocks})
        ok = fr.status_code == 200
        fj = fr.json() if ok else {}
        rec("C REST", "/finalize 왕복(응답 contents 그대로)", ok, f"{fr.status_code}")
        pages = fj.get("pages") or []
        rec("C REST", "  pages 반환", bool(pages), f"{len(pages)}쪽")
        if pages:
            widths = [len(l) for p in pages for l in p.get("lines", [])]
            rec("C REST", "  32칸 이내", all(w <= CELL_W for w in widths),
                f"최대 {max(widths) if widths else 0}칸")
            rec("C REST", f"  {PAGE_ROWS}줄 이내",
                all(len(p.get("lines", [])) <= PAGE_ROWS for p in pages),
                f"최대 {max(len(p.get('lines', [])) for p in pages)}줄 "
                f"(본문 {PAGE_ROWS-1} + 페이지행 1)")
        rec("C REST", "  brf 문자열 반환", bool(fj.get("brf")), f"{len(fj.get('brf',''))}자")
    except Exception as exc:                       # noqa: BLE001
        rec("C REST", "/finalize 왕복(응답 contents 그대로)", False, str(exc)[:60])

    try:
        fe = requests.post(f"{a.rest}/finalize", verify=False, timeout=20,
                           json={"job_id": "e", "page_no": 1, "total_pages": 1, "blocks": []})
        rec("C REST", "/finalize 빈 blocks → 200", fe.status_code == 200, f"{fe.status_code}")
    except Exception as exc:                       # noqa: BLE001
        rec("C REST", "/finalize 빈 blocks → 200", False, str(exc)[:60])

    try:
        nf = requests.get(f"{a.rest}/nope", verify=False, timeout=10)
        rec("C REST", "없는 경로 → 404", nf.status_code == 404, f"{nf.status_code}")
    except Exception as exc:                       # noqa: BLE001
        rec("C REST", "없는 경로 → 404", False, str(exc)[:60])

    summary()


def summary() -> None:
    print(f"{'':<2}{'항목':<44}{'':<6}{'메모'}")
    print("-" * 92)
    sec = None
    for s, name, ok, note in RESULTS:
        if s != sec:
            print(f"\n[{s}]")
            sec = s
        mark = "통과" if ok else "★실패"
        print(f"  {name:<44}{mark:<6}{note}")
    bad = [r for r in RESULTS if not r[2]]
    print("\n" + "-" * 92)
    print(f"총 {len(RESULTS)}항목 · 통과 {len(RESULTS)-len(bad)} · 실패 {len(bad)}")
    if bad:
        print("\n실패 목록")
        for s, name, _, note in bad:
            print(f"  · [{s}] {name}  {note}")
    print("\n" + ("전 항목 통과 — BE 연동 가능" if not bad
                  else "★ 실패 항목이 있다. 위 목록 확인"))
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
