"""E2E 점역 검수 보고서 생성기 (단일 진입점).

`storage/jobs/`에 이미 쌓인 파이프라인 결과를 골라 사람이 검수 가능한 HTML 보고서로
시각화한다. 보고서는 `test/report/{MMDD_HHMMSS}/`에 자체완결(self-contained)로 생성된다
(페이지 이미지·블록 썸네일을 폴더 안으로 복사하므로 폴더째 옮겨도 깨지지 않는다).

보고서 한 페이지의 구성:
  - 원본 PDF 페이지 이미지 1장(통째)에 레이아웃 블록을 번호 박스로 오버레이.
  - 그 아래 레이아웃 블록(요소)별 카드를 읽기순서대로 적층. 각 카드는
    원본 영역 썸네일 + 모드별 단계 대조 열을 담는다.

모드별 대조 열(요소 데이터 가용성에 맞춤):
  - a : 원본텍스트 / opt(점자변환용)            ← 추출만, 점역 없음
  - b : opt / 점자(BRF) / 역점역                ← source_text 입력(원본추출·이미지 없음)
  - c : 원본텍스트 / opt / 점자(BRF) / 역점역   ← 통합 E2E

데이터 출처:
  - 레이아웃·번호 = response.json `bounding_box_list` (+ image_width/height)
  - 원본텍스트     = 경계 파일 data/{pno}_txt_result.json
  - opt           = type/*/*_opt.json (element_id별 corrected_text)
  - 점자(BRF)     = response.json `braille_text_list`
  - 역점역         = braille_back.decode (검증 보조)

사용법(작업 디렉토리 = code/AI/, conda env=semojum):
    python test/report_builder.py                      # 대화형: storage/jobs에서 선택
    python test/report_builder.py --all                # 전체 job 시각화
    python test/report_builder.py --jobs 국어복합,수학수식  # 이름 일부로 선택
    python test/report_builder.py --run --modes a,b,c  # 파이프라인부터 실행 후 시각화
"""
from __future__ import annotations

import argparse
import html
import json
import shutil
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

try:  # 역점역(검증 보조) — 없으면 빈 칸
    from app.utils.braille_back import decode as _braille_decode
except Exception:  # noqa: BLE001
    _braille_decode = None

try:  # 블록 썸네일 크롭 — 없으면 썸네일 생략(보고서는 정상)
    from PIL import Image
except Exception:  # noqa: BLE001
    Image = None

STORAGE = Path("storage/jobs")
REPORT_ROOT = Path(__file__).parent / "report"
DATA_DIR = Path(__file__).parent / "data"

# 모드별 대조 열: (헤더, 데이터 키). 키는 _block_value가 해석한다.
COLS: dict[str, list[tuple[str, str]]] = {
    "a": [("① 원본텍스트", "raw"), ("② opt(점자변환용)", "opt")],
    "b": [("opt(점자변환용)", "opt"), ("점자(BRF)", "brf"), ("역점역", "rev")],
    "c": [("① 원본텍스트", "raw"), ("② opt(점자변환용)", "opt"),
          ("③ 점자(BRF)", "brf"), ("④ 역점역", "rev")],
}

CSS = """
body{font-family:-apple-system,'Segoe UI',Roboto,'Noto Sans KR',sans-serif;margin:0;background:#f4f5f7;color:#1a1a1a}
header{background:#1f2937;color:#fff;padding:16px 24px}
header h1{margin:0;font-size:20px}
.wrap{max-width:1600px;margin:0 auto;padding:24px}
table{border-collapse:collapse;width:100%;background:#fff;box-shadow:0 1px 3px rgba(0,0,0,.1)}
th,td{border:1px solid #e5e7eb;padding:8px 10px;text-align:left;vertical-align:top;font-size:13px}
th{background:#f3f4f6;font-weight:600}
a{color:#2563eb;text-decoration:none}a:hover{text-decoration:underline}
.tier-ZERO{color:#059669;font-weight:600}.tier-STANDARD{color:#d97706;font-weight:600}.tier-QUALITY{color:#dc2626;font-weight:600}
.st-COMPLETED{color:#059669}.st-BLOCKED,.st-ERROR{color:#dc2626;font-weight:600}.st-NEEDS_REVIEW{color:#d97706}
.meta{font-size:12px;color:#6b7280}
.braille{font-family:'Noto Sans Symbols2','Segoe UI Symbol',monospace;font-size:16px;line-height:1.6;white-space:pre-wrap;word-break:break-all}
.src{white-space:pre-wrap;color:#374151;font-size:12px}
.rev{color:#065f46;background:#ecfdf5}
.badge{display:inline-block;padding:1px 7px;border-radius:10px;font-size:11px;background:#e5e7eb;margin-right:4px}
.badge.rm{background:#dbeafe;color:#1e40af}.badge.tn{background:#fef3c7;color:#92400e}.badge.bl{background:#fecaca;color:#991b1b}
.pagecard{background:#fff;border-radius:6px;box-shadow:0 1px 3px rgba(0,0,0,.1);margin-bottom:28px;overflow:hidden}
.pagehd{background:#eef2ff;padding:10px 16px;font-weight:600;border-bottom:1px solid #e5e7eb}
.pagebody{display:flex;gap:20px;padding:16px;align-items:flex-start}
.imgcol{flex:0 0 auto;position:sticky;top:12px}
.blockcol{flex:1;min-width:0}
.imgwrap{position:relative;display:inline-block;line-height:0}
.pageimg{width:480px;max-width:100%;border:1px solid #d1d5db;border-radius:4px;display:block}
.mk{position:absolute;border:2px solid #ef4444;box-sizing:border-box;border-radius:2px;background:rgba(239,68,68,.06)}
.mk b{position:absolute;top:-1px;left:-1px;background:#ef4444;color:#fff;font-size:11px;font-weight:700;line-height:1.2;padding:0 4px;border-radius:2px 0 4px 0}
.blockcard{border:1px solid #e5e7eb;border-radius:6px;margin:0 0 14px;overflow:hidden}
.blockcard.blocked{border-color:#fca5a5}
.blockhd{background:#f9fafb;padding:7px 12px;border-bottom:1px solid #e5e7eb;font-size:12px}
.bidx{display:inline-block;min-width:20px;height:20px;line-height:20px;text-align:center;background:#ef4444;color:#fff;border-radius:50%;font-weight:700;font-size:12px;margin-right:8px}
.blockbody{display:flex;gap:12px;padding:12px}
.thumb{flex:0 0 auto}
.thumb img{max-width:200px;max-height:220px;border:1px solid #d1d5db;border-radius:4px}
.thumb .noimg{width:120px;color:#9ca3af;font-size:11px;text-align:center;padding:18px 6px;border:1px dashed #d1d5db;border-radius:4px}
.cols{flex:1;min-width:0}
.cols th{width:120px;white-space:nowrap;background:#f3f4f6}
.cols td{word-break:break-word;overflow-wrap:anywhere}
pre.report{background:#0f172a;color:#e2e8f0;padding:14px;border-radius:6px;overflow:auto;font-size:12px;line-height:1.5}
"""

_CIRCLED = "①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮⑯⑰⑱⑲⑳"


def esc(s) -> str:
    return html.escape(str(s if s is not None else ""))


def _circled(n: int) -> str:
    return _CIRCLED[n - 1] if 1 <= n <= len(_CIRCLED) else str(n)


def _load(p: Path):
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return None


def _reverse(braille_lines: list[str], *, math: bool = False) -> str:
    """점자(BRF) → 한국어 텍스트 역점역(검증 보조).

    math=True면 수식 구역으로 디코드(요소 type=formula). 텍스트 속 인라인 수식은
    decode가 토큰별로 자동 판별하므로 일반 요소는 math=False로 둔다.
    """
    if not _braille_decode or not braille_lines:
        return ""
    try:
        return _braille_decode("\n".join(braille_lines), math=math)
    except Exception:  # noqa: BLE001
        return "(역점역 실패)"


# ── 페이지 데이터 수집 ──────────────────────────────────────────────

def _opt_map(page_dir: Path) -> dict[str, str]:
    """type/*/*_opt.json 전체를 모아 {element_id: corrected_text}. 모든 모드 공통 opt 출처."""
    out: dict[str, str] = {}
    type_dir = page_dir / "type"
    if not type_dir.exists():
        return out
    for opt_file in sorted(type_dir.glob("*/*_opt.json")):
        data = _load(opt_file) or []
        for item in data if isinstance(data, list) else []:
            eid = item.get("element_id")
            if eid is not None:
                out[str(eid)] = item.get("corrected_text", "") or ""
    return out


def _raw_map(page_dir: Path, pno: int) -> dict[str, str]:
    """경계 파일 data/{pno}_txt_result.json → {element_id: content}. (b는 보통 없음)"""
    raw_doc = _load(page_dir / "data" / f"{pno:03d}_txt_result.json") or {}
    return {str(el.get("id")): el.get("content", "") for el in (raw_doc.get("elements") or [])}


def _bbox_map(resp: dict) -> dict[str, dict]:
    return {str(b.get("id")): b for b in (resp.get("bounding_box_list") or [])}


def _crop_thumb(img, bbox: dict, dst: Path) -> bool:
    """원본 이미지에서 bbox 영역만 잘라 dst에 저장. 성공 시 True."""
    if img is None or not bbox:
        return False
    x, y, x2, y2 = bbox.get("x", 0), bbox.get("y", 0), bbox.get("x2", 0), bbox.get("y2", 0)
    if x2 - x < 2 or y2 - y < 2:  # 0,0,0,0 등 무효 bbox
        return False
    iw, ih = img.size
    box = (max(0, x), max(0, y), min(iw, x2), min(ih, y2))
    try:
        crop = img.crop(box)
        crop.thumbnail((480, 480))  # 과대 영역 축소(파일 경량)
        dst.parent.mkdir(parents=True, exist_ok=True)
        crop.save(dst, "JPEG", quality=80)
        return True
    except Exception:  # noqa: BLE001
        return False


def _overlay_markers(markers: list[tuple[int, dict]], iw: int, ih: int) -> str:
    """번호 박스 오버레이(원본 이미지 위, 퍼센트 절대좌표)."""
    if not iw or not ih:
        return ""
    out = []
    for idx, b in markers:
        x, y, x2, y2 = b.get("x", 0), b.get("y", 0), b.get("x2", 0), b.get("y2", 0)
        if x2 - x < 2 or y2 - y < 2:
            continue
        left, top = x / iw * 100, y / ih * 100
        w, h = (x2 - x) / iw * 100, (y2 - y) / ih * 100
        out.append(
            f'<div class="mk" style="left:{left:.2f}%;top:{top:.2f}%;'
            f'width:{w:.2f}%;height:{h:.2f}%"><b>{idx}</b></div>'
        )
    return "".join(out)


def _block_value(key: str, ctx: dict) -> str:
    if key == "raw":
        return f'<div class="src">{esc(ctx["raw"])}</div>'
    if key == "opt":
        return f'<div class="src">{esc(ctx["opt"])}</div>'
    if key == "brf":
        return f'<div class="braille">{esc(ctx["brf"])}</div>'
    if key == "rev":
        return f'<div class="src rev">{esc(ctx["rev"])}</div>'
    return ""


def _block_cards(resp: dict, raw: dict, opt: dict, mode: str,
                 bbox_map: dict, crop_rel: dict[str, str]) -> tuple[str, list[tuple[int, dict]]]:
    """레이아웃 블록별 카드 + 오버레이 마커 목록을 반환."""
    text_list = resp.get("text_list") or []
    braille_list = resp.get("braille_text_list") or []
    braille_map = {b["id"]: b for b in braille_list}
    base = text_list if text_list else braille_list  # a/c=text, b=braille
    base = sorted(base, key=lambda it: it.get("order", 0) or 0)

    cols = COLS.get(mode, COLS["c"])
    show_index = mode in ("a", "c")  # b는 bbox 없음 → 번호 없음
    cards, markers = [], []
    for n, it in enumerate(base, 1):
        eid = str(it["id"])
        bitem = braille_map.get(it["id"], {})
        brf_lines = bitem.get("contents", []) or []
        is_formula = it.get("type") == "formula" or "formula" in (it.get("render_mode") or "")
        ctx = {
            "raw": raw.get(eid, ""),
            "opt": opt.get(eid, ""),
            "brf": "\n".join(brf_lines),
            "rev": _reverse(brf_lines, math=is_formula),
        }

        # 헤더 배지
        badges = [f'<span class="badge">{esc(it.get("type"))}</span>',
                  f'<span class="badge rm">{esc(it.get("render_mode", ""))}</span>']
        hl = it.get("heading_level") or 0
        if hl:
            badges.append(f'<span class="badge" style="background:#ede9fe;color:#5b21b6">제목L{hl}</span>')
        if it.get("tn_text"):
            badges.append(f'<span class="badge tn">주:{esc(it["tn_text"])[:18]}</span>')
        blocked = it.get("is_blocked") or bitem.get("is_blocked")
        if blocked:
            badges.append('<span class="badge bl">처리불가</span>')

        bbox = bbox_map.get(eid)
        if show_index and bbox:
            markers.append((n, bbox))
        idx_html = f'<span class="bidx">{n}</span>' if show_index else ""
        conf = it.get("ocr_confidence", 0) or 0
        bbox_meta = ""
        if bbox:
            bbox_meta = f' · <span class="meta">({bbox.get("x")},{bbox.get("y")})–({bbox.get("x2")},{bbox.get("y2")})</span>'
        head = (f'<div class="blockhd">{idx_html}{"".join(badges)}'
                f'<span class="meta"> · 순서 {esc(it.get("order"))} · conf {conf:.2f}</span>{bbox_meta}</div>')

        # 썸네일(a/c, bbox 있을 때)
        thumb = ""
        if show_index:
            rel = crop_rel.get(eid)
            if rel:
                thumb = f'<div class="thumb"><img src="{rel}"></div>'
            else:
                thumb = '<div class="thumb"><div class="noimg">영역 없음</div></div>'

        rows = "".join(
            f"<tr><th>{esc(hdr)}</th><td>{_block_value(key, ctx)}</td></tr>"
            for hdr, key in cols
        )
        body = f'<div class="blockbody">{thumb}<table class="cols">{rows}</table></div>'
        cls = " blocked" if blocked else ""
        cards.append(f'<div class="blockcard{cls}">{head}{body}</div>')

    return "\n".join(cards), markers


# ── job/index 빌드 ──────────────────────────────────────────────────

def _copy_page_images(job_dir: Path, out_dir: Path, job_id: str) -> None:
    src_in = job_dir / "input"
    if not src_in.exists():
        return
    dst = out_dir / "assets" / job_id
    dst.mkdir(parents=True, exist_ok=True)
    for img in sorted(src_in.glob("page_*.jpg")):
        shutil.copy(img, dst / img.name)


def build_job(job_dir: Path, out_dir: Path) -> dict | None:
    state = _load(job_dir / "state.json")
    if not state:
        return None
    job_id = state["job_id"]
    mode = state.get("mode", "c")
    _copy_page_images(job_dir, out_dir, job_id)

    parts = [
        f"<header><h1>{esc(job_id)}</h1>"
        f'<div class="meta">슬라이스 {esc(state["slice"])} · 모드 {esc(mode)} · '
        f'{"SCAN/MinerU" if state.get("scan_path") else "ZERO/텍스트"} · '
        f'{state["total_pages"]}p · {state["total_time_ms"]}ms</div></header>',
        '<div class="wrap"><p><a href="index.html">← 전체 목록</a></p>',
    ]
    report_txt_path = job_dir / "report.txt"
    if report_txt_path.exists():
        parts.append(f'<pre class="report">{esc(report_txt_path.read_text(encoding="utf-8"))}</pre>')

    blocked_total = 0
    for ps in state["pages"]:
        pno = ps["page_no"]
        page_dir = job_dir / "temp" / f"page_{pno:03d}"
        resp = _load(page_dir / "response.json") or {}
        st = ps.get("status", "?")
        blocked_total += ps.get("n_blocked", 0) or 0
        hd = (
            f'<div class="pagehd">page {pno} · '
            f'<span class="st-{esc(st)}">{esc(st)}</span> · '
            f'<span class="tier-{esc(ps.get("routing_tier", ""))}">{esc(ps.get("routing_tier", ""))}</span> · '
            f'{ps.get("processing_time_ms", 0)}ms · text {ps.get("n_text_elements", 0)} · '
            f'braille {ps.get("n_braille_elements", 0)} · 블록 {ps.get("n_blocked", 0)}</div>'
        )
        if ps.get("error"):
            parts.append(f'<div class="pagecard">{hd}'
                         f'<div style="padding:12px;color:#dc2626">ERROR: {esc(ps["error"])}</div></div>')
            continue

        raw = _raw_map(page_dir, pno)
        opt = _opt_map(page_dir)
        bbox_map = _bbox_map(resp)
        iw, ih = resp.get("image_width") or 0, resp.get("image_height") or 0

        # 블록 썸네일 크롭(a/c, PIL 있을 때)
        crop_rel: dict[str, str] = {}
        img_src = job_dir / "input" / f"page_{pno:03d}.jpg"
        if mode in ("a", "c") and Image is not None and img_src.exists() and bbox_map:
            with Image.open(img_src) as pim:
                pim = pim.convert("RGB")
                for eid, bbox in bbox_map.items():
                    rel = f"assets/{job_id}/crops/p{pno:03d}_{eid[:8]}.jpg"
                    if _crop_thumb(pim, bbox, out_dir / rel):
                        crop_rel[eid] = rel

        cards, markers = _block_cards(resp, raw, opt, mode, bbox_map, crop_rel)

        img_rel = f"assets/{job_id}/page_{pno:03d}.jpg"
        if mode in ("a", "c") and (out_dir / img_rel).exists():
            overlay = _overlay_markers(markers, iw, ih)
            img_col = (f'<div class="imgcol"><div class="imgwrap">'
                       f'<img class="pageimg" src="{img_rel}">{overlay}</div></div>')
        else:
            img_col = ""  # b: 원본추출·bbox 없음 → 블록만

        body = f'<div class="pagebody">{img_col}<div class="blockcol">{cards}</div></div>'
        parts.append(f'<div class="pagecard">{hd}{body}</div>')

    parts.append("</div>")
    page_html = (
        f"<!doctype html><html lang=ko><head><meta charset=utf-8>"
        f"<title>{esc(job_id)}</title><style>{CSS}</style></head>"
        f"<body>{''.join(parts)}</body></html>"
    )
    (out_dir / f"{job_id}.html").write_text(page_html, encoding="utf-8")
    ok = sum(1 for p in state["pages"] if p.get("status") == "COMPLETED")
    return {
        "job_id": job_id, "slice": state["slice"], "mode": mode,
        "scan": state.get("scan_path"), "pages": state["total_pages"],
        "ok": ok, "blocked": blocked_total, "ms": state["total_time_ms"],
    }


def build_index(summaries: list[dict], out_dir: Path, meta: dict) -> None:
    rows = []
    for s in sorted(summaries, key=lambda x: x["job_id"]):
        okcls = "st-COMPLETED" if s["ok"] == s["pages"] else "st-BLOCKED"
        blkcls = ' style="color:#dc2626;font-weight:600"' if s["blocked"] else ""
        rows.append(
            f'<tr><td><a href="{esc(s["job_id"])}.html">{esc(s["job_id"])}</a></td>'
            f'<td>{esc(s["slice"])}</td><td>{esc(s["mode"])}</td>'
            f'<td class="tier-{"STANDARD" if s["scan"] else "ZERO"}">{"SCAN" if s["scan"] else "ZERO"}</td>'
            f'<td class="{okcls}">{s["ok"]}/{s["pages"]}</td>'
            f'<td{blkcls}>{s["blocked"]}</td><td>{s["ms"]}ms</td></tr>'
        )
    total_pages = sum(s["pages"] for s in summaries)
    total_ok = sum(s["ok"] for s in summaries)
    total_blocked = sum(s["blocked"] for s in summaries)
    meta_line = (
        f'생성 {esc(meta["generated_at"])} · job {len(summaries)}개 · '
        f'완료 {total_ok}/{total_pages}p · 블록 {total_blocked}'
    )
    html_doc = (
        f"<!doctype html><html lang=ko><head><meta charset=utf-8>"
        f"<title>E2E 점역 리포트 {esc(meta['stamp'])}</title>"
        f"<style>{CSS}</style></head><body>"
        f"<header><h1>Semojum V2 — E2E 점역 검수 리포트</h1>"
        f'<div class="meta">{meta_line}</div></header>'
        f'<div class="wrap"><table><tr><th>Job</th><th>슬라이스</th><th>모드</th><th>경로</th>'
        f"<th>완료</th><th>블록</th><th>시간</th></tr>{''.join(rows)}</table></div></body></html>"
    )
    (out_dir / "index.html").write_text(html_doc, encoding="utf-8")


# ── 앞단: storage/jobs 선택 ─────────────────────────────────────────

def _discover_jobs() -> list[Path]:
    """state.json을 가진 storage/jobs 하위 job 디렉토리(이름순)."""
    if not STORAGE.exists():
        return []
    return sorted((d for d in STORAGE.iterdir() if d.is_dir() and (d / "state.json").exists()),
                  key=lambda d: d.name)


def _job_brief(job_dir: Path) -> str:
    st = _load(job_dir / "state.json") or {}
    ok = sum(1 for p in (st.get("pages") or []) if p.get("status") == "COMPLETED")
    path = "SCAN" if st.get("scan_path") else "ZERO"
    return (f'mode={st.get("mode","?")} · {path} · '
            f'{ok}/{st.get("total_pages","?")}p · {st.get("total_time_ms","?")}ms')


def _parse_selection(expr: str, n: int) -> list[int]:
    """'1,3,5-7,all' → 0-based 인덱스 목록."""
    expr = expr.strip().lower()
    if expr in ("all", "*", "a"):
        return list(range(n))
    picked: set[int] = set()
    for tok in expr.replace(" ", "").split(","):
        if not tok:
            continue
        if "-" in tok:
            lo, hi = tok.split("-", 1)
            if lo.isdigit() and hi.isdigit():
                picked.update(range(int(lo) - 1, int(hi)))
        elif tok.isdigit():
            picked.add(int(tok) - 1)
    return sorted(i for i in picked if 0 <= i < n)


def _select_jobs(args) -> list[Path]:
    """--run / --all / --jobs / 대화형 중 하나로 시각화 대상 job 결정."""
    if args.run:
        return _run_pipeline(args)

    jobs = _discover_jobs()
    if not jobs:
        print(f"[report] storage/jobs에 state.json을 가진 job이 없습니다 ({STORAGE}).")
        print("         먼저 --run 으로 파이프라인을 실행하거나, e2e_runner로 데이터를 만드세요.")
        return []

    if args.jobs:
        keys = [k.strip() for k in args.jobs.split(",") if k.strip()]
        sel = [d for d in jobs if any(k in d.name for k in keys)]
        if not sel:
            print(f"[report] --jobs '{args.jobs}' 와 일치하는 job 없음. 후보:")
            for d in jobs:
                print(f"    {d.name}")
        return sel
    if args.all:
        return jobs

    # 대화형 선택
    print(f"\nstorage/jobs 에서 보고서 대상 선택 ({len(jobs)}개):\n")
    for i, d in enumerate(jobs, 1):
        print(f"  {i:>2}. {d.name}   [{_job_brief(d)}]")
    if not sys.stdin.isatty():
        print("\n[report] 비대화형 입력 — 전체를 대상으로 진행합니다 (특정 선택은 --jobs/--all 사용).")
        return jobs
    raw = input("\n번호 선택 (예: 1,3,5-7 / all): ").strip()
    idxs = _parse_selection(raw, len(jobs))
    if not idxs:
        print("[report] 선택 없음 — 종료.")
        return []
    return [jobs[i] for i in idxs]


def _run_pipeline(args) -> list[Path]:
    """--run: test/data PDF를 파이프라인에 통과시켜 storage/jobs 생성 후 그 job들을 반환."""
    import asyncio
    from test import e2e_runner

    only = set(args.only.split(",")) if args.only else None
    modes_override = args.modes.split(",") if args.modes else None
    known = {e["slice"]: e for e in e2e_runner.DEFAULT_MANIFEST}

    manifest = []
    for pdf in sorted(DATA_DIR.glob("*.pdf")):
        name = pdf.stem
        if only and name not in only:
            continue
        base = known.get(name)
        if base is not None:
            scan, modes = base["scan"], list(base["modes"])
        else:
            scan = ("scan" in name) or ("수학" in name) or ("도형" in name)
            modes = ["c"]
        if modes_override:
            modes = list(modes_override)
        if args.no_scan and scan:
            continue
        manifest.append({"slice": name, "modes": modes, "scan": scan})

    if not manifest:
        print(f"[report] --run 대상 문서 없음 (DATA_DIR={DATA_DIR}, only={only}).")
        return []

    if args.load_models:
        from app.core.model_manager import model_manager
        print("[report] HyperCLOVA X(ClovaX) 로드 중… (수 분 소요)")
        asyncio.run(asyncio.to_thread(model_manager._load_hcxt))
        print(f"[report] 모델 상태: {model_manager.get_status()}")
    else:
        print("[report] 모델 미로드 — opt는 GPT-4o/rule-based 폴백 경로")

    produced: list[Path] = []
    for entry in manifest:
        for mode in entry["modes"]:
            label = "SCAN/MinerU" if entry["scan"] else "ZERO/텍스트"
            print(f"▶ {entry['slice']}  mode={mode}  ({label})")
            try:
                asyncio.run(e2e_runner.run_job(entry["slice"], mode, scan=entry["scan"], reuse=args.reuse))
            except Exception as exc:  # noqa: BLE001
                print(f"  ✗ 실행 실패: {type(exc).__name__}: {exc}")
                continue
            job_dir = STORAGE / f"e2e-{entry['slice']}-{mode}"
            if (job_dir / "state.json").exists():
                produced.append(job_dir)
    return produced


def main() -> None:
    ap = argparse.ArgumentParser(description="Semojum V2 E2E 점역 검수 보고서 생성기")
    ap.add_argument("--all", action="store_true", help="storage/jobs 전체를 시각화")
    ap.add_argument("--jobs", default=None, help="job 이름 일부로 선택(쉼표구분, 예: 국어복합,수학수식)")
    ap.add_argument("--run", action="store_true", help="시각화 전에 파이프라인부터 실행(test/data → storage/jobs)")
    # --run 옵션
    ap.add_argument("--only", default=None, help="[--run] 슬라이스 이름만(쉼표구분)")
    ap.add_argument("--modes", default=None, help="[--run] 모드 강제(예: c 또는 a,b,c)")
    ap.add_argument("--no-scan", action="store_true", help="[--run] 수학/scan(MinerU) 제외")
    ap.add_argument("--reuse", action="store_true", help="[--run] 추출 캐시 보존, opt→braille만 갱신")
    ap.add_argument("--load-models", action="store_true", help="[--run] HyperCLOVA X 실모델 로드")
    args = ap.parse_args()

    targets = _select_jobs(args)
    if not targets:
        sys.exit(1)

    stamp = time.strftime("%m%d_%H%M%S")
    out_dir = REPORT_ROOT / stamp
    out_dir.mkdir(parents=True, exist_ok=True)
    if Image is None:
        print("[report] ⚠ Pillow 미설치 — 블록 썸네일 생략(보고서는 정상 생성).")
    print(f"[report] 출력 폴더: {out_dir}  ·  대상 job {len(targets)}개\n")

    summaries = []
    for job_dir in targets:
        s = build_job(job_dir, out_dir)
        if s:
            summaries.append(s)
            print(f"  ✓ {s['job_id']}  {s['ok']}/{s['pages']}  블록{s['blocked']}")
        else:
            print(f"  ✗ {job_dir.name}  (state.json 없음/손상)")

    meta = {"stamp": stamp, "generated_at": time.strftime("%Y-%m-%d %H:%M:%S")}
    build_index(summaries, out_dir, meta)
    print(f"\n{'=' * 60}\n보고서 {len(summaries)}개 job → {out_dir}/index.html")


if __name__ == "__main__":
    main()
