"""storage/jobs/e2e-* 결과를 사람이 검수 가능한 HTML로 시각화 → test/report/.

각 job(슬라이스×모드)마다:
  - 페이지별 입력 이미지 + 요소 표(순서·유형·소스텍스트·점역·플래그)
  - 소스↔점역 대조, [처리 불가]·블록 요소 강조, rule_trail/render_mode 표기
index.html에서 전체 job 요약 표로 진입.

사용법(작업 디렉토리 = code/AI/):
    python test/report_builder.py            # storage/jobs/e2e-* 전체 시각화
"""
from __future__ import annotations

import html
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

try:
    from app.utils.braille_back import decode as _braille_decode
except Exception:  # noqa: BLE001 — 역점역 모듈 없으면 빈 칸으로
    _braille_decode = None

STORAGE = Path("storage/jobs")
OUT = Path(__file__).parent / "report"
OUT.mkdir(parents=True, exist_ok=True)


def _reverse(braille_lines: list[str]) -> str:
    """점자(BRF) → 한국어 텍스트 역점역(검증 보조)."""
    if not _braille_decode or not braille_lines:
        return ""
    try:
        return _braille_decode("\n".join(braille_lines))
    except Exception:  # noqa: BLE001
        return "(역점역 실패)"

CSS = """
body{font-family:-apple-system,'Segoe UI',Roboto,'Noto Sans KR',sans-serif;margin:0;background:#f4f5f7;color:#1a1a1a}
header{background:#1f2937;color:#fff;padding:16px 24px}
header h1{margin:0;font-size:20px}
.wrap{max-width:1600px;margin:0 auto;padding:24px}
table{border-collapse:collapse;width:100%;background:#fff;box-shadow:0 1px 3px rgba(0,0,0,.1);margin-bottom:24px}
th,td{border:1px solid #e5e7eb;padding:8px 10px;text-align:left;vertical-align:top;font-size:13px}
th{background:#f3f4f6;font-weight:600}
tr:nth-child(even) td{background:#fafafa}
a{color:#2563eb;text-decoration:none}a:hover{text-decoration:underline}
.tier-ZERO{color:#059669;font-weight:600}.tier-STANDARD{color:#d97706;font-weight:600}.tier-QUALITY{color:#dc2626;font-weight:600}
.st-COMPLETED{color:#059669}.st-BLOCKED,.st-ERROR{color:#dc2626;font-weight:600}.st-NEEDS_REVIEW{color:#d97706}
.blocked{background:#fee2e2 !important}
.braille{font-family:'Noto Sans Symbols2','Segoe UI Symbol',monospace;font-size:16px;line-height:1.6;white-space:pre-wrap;word-break:break-all}
.src{white-space:pre-wrap;color:#374151;font-size:12px}
.rev{color:#065f46;background:#ecfdf5}
table.stages{table-layout:fixed}
table.stages th:nth-child(1){width:11%}
table.stages th:nth-child(2),table.stages th:nth-child(3),table.stages th:nth-child(5){width:23%}
table.stages td{word-break:break-word;overflow-wrap:anywhere}
.imgrow{padding:14px 14px 0;text-align:center}
.pageimg{max-width:46%;border:1px solid #d1d5db;border-radius:4px}
.meta{font-size:12px;color:#6b7280}
.badge{display:inline-block;padding:1px 7px;border-radius:10px;font-size:11px;background:#e5e7eb;margin-right:4px}
.badge.rm{background:#dbeafe;color:#1e40af}.badge.tn{background:#fef3c7;color:#92400e}.badge.bl{background:#fecaca;color:#991b1b}
.pagecard{background:#fff;border-radius:6px;box-shadow:0 1px 3px rgba(0,0,0,.1);margin-bottom:28px;overflow:hidden}
.pagehd{background:#eef2ff;padding:10px 16px;font-weight:600;border-bottom:1px solid #e5e7eb}
.flex{display:flex;gap:20px;padding:16px;align-items:flex-start}
.flex .col{flex:1;min-width:0}
pre.report{background:#0f172a;color:#e2e8f0;padding:14px;border-radius:6px;overflow:auto;font-size:12px;line-height:1.5}
"""


def esc(s) -> str:
    return html.escape(str(s if s is not None else ""))


def _load(p: Path):
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None


def _elem_rows(response: dict, raw_extract: dict) -> str:
    """response.json + 원본 추출 → 요소별 5단계 대조 행.

    레이아웃 / 원본 텍스트변환 / 점자변환용 텍스트변환(opt) / 점자변환(BRF) / 역점역변환.
    """
    text_list = response.get("text_list") or []           # opt corrected_text (점자변환용)
    braille_map = {b["id"]: b for b in (response.get("braille_text_list") or [])}
    # 순서 기준 = text_list(읽기순). braille 없으면(mode a) text_list만.
    items = text_list or list(braille_map.values())
    rows = []
    for it in items:
        eid = it["id"]
        bitem = braille_map.get(eid, {})

        # 1) 레이아웃
        hl = it.get("heading_level") or 0
        badges = [f'<span class="badge">{esc(it.get("type"))}</span>',
                  f'<span class="badge rm">{esc(it.get("render_mode",""))}</span>']
        if hl:
            badges.append(f'<span class="badge" style="background:#ede9fe;color:#5b21b6">제목L{hl}</span>')
        if it.get("tn_text"):
            badges.append(f'<span class="badge tn">주:{esc(it["tn_text"])[:18]}</span>')
        blocked = it.get("is_blocked") or bitem.get("is_blocked")
        if blocked:
            badges.append('<span class="badge bl">처리불가</span>')
        layout_cell = (f'<div class="meta">#{esc(it.get("order"))} · conf '
                       f'{it.get("ocr_confidence",0):.2f}</div>' + "".join(badges))

        # 2) 원본 텍스트변환 (PDF→추출 원문, opt 이전)
        raw_txt = raw_extract.get(str(eid), "")
        # 3) 점자변환용 텍스트변환 (opt corrected_text)
        opt_txt = " ".join(it.get("contents", []) or [])
        # 4) 점자변환 (BRF)
        braille_lines = bitem.get("contents", []) or []
        braille = "\n".join(braille_lines)
        # 5) 역점역변환 (BRF→한국어)
        rev = _reverse(braille_lines)

        cls = ' class="blocked"' if blocked else ""
        rows.append(
            f"<tr{cls}><td>{layout_cell}</td>"
            f'<td class="src">{esc(raw_txt)}</td>'
            f'<td class="src">{esc(opt_txt)}</td>'
            f'<td class="braille">{esc(braille)}</td>'
            f'<td class="src rev">{esc(rev)}</td></tr>'
        )
    return "\n".join(rows)


def build_job(job_dir: Path) -> dict | None:
    state = _load(job_dir / "state.json")
    if not state:
        return None
    job_id = state["job_id"]
    parts = [f"<header><h1>{esc(job_id)}</h1>"
             f'<div class="meta">슬라이스 {esc(state["slice"])} · 모드 {esc(state["mode"])} · '
             f'{"SCAN/MinerU" if state.get("scan_path") else "ZERO/텍스트"} · '
             f'{state["total_pages"]}p · {state["total_time_ms"]}ms</div></header>',
             '<div class="wrap"><p><a href="index.html">← 전체 목록</a></p>']

    report_txt = (job_dir / "report.txt").read_text(encoding="utf-8") if (job_dir / "report.txt").exists() else ""
    parts.append(f'<pre class="report">{esc(report_txt)}</pre>')

    blocked_total = 0
    for ps in state["pages"]:
        pno = ps["page_no"]
        resp = _load(job_dir / "temp" / f"page_{pno:03d}" / "response.json") or {}
        img = job_dir / "input" / f"page_{pno:03d}.jpg"
        img_rel = ("../" + str(img).replace("\\", "/")) if img.exists() else ""
        st = ps.get("status", "?")
        blocked_total += ps.get("n_blocked", 0) or 0
        hd = (f'<div class="pagehd">page {pno} · '
              f'<span class="st-{esc(st)}">{esc(st)}</span> · '
              f'<span class="tier-{esc(ps.get("routing_tier",""))}">{esc(ps.get("routing_tier",""))}</span> · '
              f'{ps.get("processing_time_ms",0)}ms · text {ps.get("n_text_elements",0)} · '
              f'braille {ps.get("n_braille_elements",0)} · 블록 {ps.get("n_blocked",0)}</div>')
        if ps.get("error"):
            hd_extra = f'<div style="padding:12px;color:#dc2626">ERROR: {esc(ps["error"])}</div>'
            parts.append(f'<div class="pagecard">{hd}{hd_extra}</div>')
            continue
        # 원본 텍스트변환(추출 원문) = 경계 파일 data/NNN_txt_result.json
        raw_doc = _load(job_dir / "temp" / f"page_{pno:03d}" / "data" / f"{pno:03d}_txt_result.json") or {}
        raw_extract = {str(el.get("id")): el.get("content", "") for el in (raw_doc.get("elements") or [])}
        rows = _elem_rows(resp, raw_extract)
        img_block = (f'<div class="imgrow">{f"<img class=pageimg src={img_rel}>" if img_rel else ""}</div>')
        body = (
            f"{img_block}"
            '<table class="stages"><tr>'
            '<th>레이아웃</th><th>① 원본 텍스트변환</th><th>② 점자변환용 텍스트변환</th>'
            '<th>③ 점자변환(BRF)</th><th>④ 역점역변환</th></tr>'
            f'{rows}</table>'
        )
        parts.append(f'<div class="pagecard">{hd}{body}</div>')

    parts.append("</div>")
    page_html = f"<!doctype html><html lang=ko><head><meta charset=utf-8><title>{esc(job_id)}</title><style>{CSS}</style></head><body>{''.join(parts)}</body></html>"
    (OUT / f"{job_id}.html").write_text(page_html, encoding="utf-8")
    ok = sum(1 for p in state["pages"] if p.get("status") == "COMPLETED")
    return {
        "job_id": job_id, "slice": state["slice"], "mode": state["mode"],
        "scan": state.get("scan_path"), "pages": state["total_pages"],
        "ok": ok, "blocked": blocked_total, "ms": state["total_time_ms"],
    }


def build_index(summaries: list[dict]) -> None:
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
    html_doc = (
        f"<!doctype html><html lang=ko><head><meta charset=utf-8><title>E2E 점역 리포트</title>"
        f"<style>{CSS}</style></head><body>"
        f"<header><h1>Semojum V2 — E2E 점역 검수 리포트</h1>"
        f'<div class="meta">storage/jobs/e2e-* 결과 · job {len(summaries)}개</div></header>'
        f'<div class="wrap"><table><tr><th>Job</th><th>슬라이스</th><th>모드</th><th>경로</th>'
        f"<th>완료</th><th>블록</th><th>시간</th></tr>{''.join(rows)}</table></div></body></html>"
    )
    (OUT / "index.html").write_text(html_doc, encoding="utf-8")


def main() -> None:
    summaries = []
    for job_dir in sorted(STORAGE.glob("e2e-*")):
        if not job_dir.is_dir():
            continue
        s = build_job(job_dir)
        if s:
            summaries.append(s)
            print(f"  ✓ {s['job_id']}  {s['ok']}/{s['pages']}  블록{s['blocked']}")
    build_index(summaries)
    print(f"\n리포트 {len(summaries)}개 → {OUT}/index.html")


if __name__ == "__main__":
    main()
