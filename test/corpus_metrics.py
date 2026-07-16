"""Process 0 — 측정 프레임. 우리 점역 출력 ↔ 정답 BRL 대조 지표.

정답(output_*.brl)은 Braille ASCII(BRF), 우리 출력(response.braille_text_list)은 유니코드 점자.
braille_ascii.ascii_to_unicode(backtick="cell") 로 정답을 유니코드로 정규화한 뒤 비교한다.
⚠ backtick="cell" 필수 — 코퍼스 BRF에서 백틱은 ⠈(초성 ㄱ)이다(2026-07-13 수정 전에는 공백으로
읽어 정답의 ㄱ초성이 전부 사라진 채 채점됐다 → 지표가 과소평가됐음).

지표(사전 정의 — 이게 측정의 정본):
  1) cell_sim        셀 단위 정규화 편집거리 유사도(공백 포함). 1 - NED.
  2) cell_sim_ns     공백 셀 제거 후 유사도 — 띄어쓰기 정책 차이를 배제한 순수 셀 정확도.
  3) token_recall    정답 어절(공백분리) 중 우리 출력에 부분문자열로 존재하는 비율.
                     (§3 함정: PDF 추출 텍스트는 공백이 비대칭 → 부분문자열 기준. verify_match 계열.)
  4) token_prec      우리 어절 중 정답에 존재하는 비율. token_f1 = 조화평균.
  5) order_tau       읽기순서 상관(Kendall τ). 양쪽에 1회만 등장하는 어절의 등장위치 순위상관.
                     +1=순서 완전보존, 0=무상관, -1=역순.
  6) (보류) caption  시각자료 설명 품질 — 정답에서 캡션 스팬 분리가 필요해 자동화 보류, Process 3 정성검토.
  7) 수정비용 프록시(KPI=점역사 수정시간 정렬, 2026-07-13):
     우리 출력→정답으로 고치는 데 필요한 편집을 어절 시퀀스 정렬(LCS)로 추정.
       edit_insert_cell 점역사가 타이핑해 넣어야 할 셀 수(정답에만 있음)
       edit_delete_cell 지워야 할 셀 수(우리 출력에만 있음)
       edit_moved_tok   재배치 어절 수(양쪽 diff에 모두 등장 = 위치만 틀림 — 블록 이동 비용)
       edit_move_ops    이동으로 분류된 diff 블록 수(≥50% 어절이 반대편 diff에 존재)
       edit_regions     셀 diff 영역 수 = 점역사가 찾아가야 할 위치 수(검증·찾기 비용 프록시)
       edit_cost_norm   (삽입+삭제) 셀 / 정답 셀 — 0=수정 없음, 1≈전면 재작성
     ⚠ 프록시다: 셀 1개 오타도 어절 1개 replace로 잡히고, 시간 가중치(이동≫삽입≫삭제)는
     태민 캘리브레이션 사항. 개선 방향 판단은 "이 숫자들이 줄어드는가"로.

파이프라인 건전성(성공/타임아웃/에러/티어/시간)은 run_state.json에서 별도 집계(품질과 분리).

채점 대상 = response.json이 존재하는 모든 페이지(status 무관). NEEDS_REVIEW를 채점에서
빼면 문제 페이지가 점수에서 사라져 "플래그를 제대로 달수록 점수가 좋아지는" 편향이 생긴다.
status는 per_page에 실어 별도 집계한다. pipeline_ok_rate = 출력 산출(COMPLETED+NEEDS_REVIEW)/전체.

사용(작업 디렉토리 = code/AI/):
  python test/corpus_metrics.py --tag smoke                 # storage/jobs/corpus-smoke-* 채점
  python test/corpus_metrics.py --tag dev --baseline        # baseline.json 으로 동결
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.utils.braille_ascii import ascii_to_unicode  # noqa: E402

AI = Path(__file__).parent.parent
OUTPUT = AI / "test/test_data/output"
STORAGE = Path("storage/jobs")
REPORT = AI / "test/report"
SPACE = "⠀"  # U+2800

# 객관적 합격 기준(베이스라인 동결 후 baseline+Δ 로 갱신. 초기값=절대 하한 가드).
THRESHOLDS = {
    "cell_sim_ns": 0.70,   # 순수 셀 정확도 하한
    "token_f1": 0.70,
    "order_tau": 0.80,
    "pipeline_ok_rate": 0.95,
}


# ── 정규화 ───────────────────────────────────────────────────────────────
def gold_unicode(subject: str, page: str) -> str | None:
    p = OUTPUT / f"output_{subject}_page{page}.brl"
    if not p.exists():
        return None
    # backtick="cell": 코퍼스 BRF의 백틱은 ⠈(초성 ㄱ)이다. 기본값("space")으로 읽으면
    # 정답에서 ㄱ초성이 전부 삭제돼(국가→가) 우리 출력의 정상 ⠈가 오류로 잡힌다.
    return ascii_to_unicode(p.read_text(encoding="utf-8"), backtick="cell")


def linearize(braille_text_list: list[dict]) -> str:
    """braille_text_list(요소별 contents=줄 리스트) → 읽기순서 선형 점자 문자열."""
    parts: list[str] = []
    for el in braille_text_list:
        c = el.get("contents")
        if isinstance(c, list):
            parts.append("\n".join(c))
        elif isinstance(c, str):
            parts.append(c)
    return "\n".join(parts)


def cells_only(s: str) -> str:
    """점자 셀만(공백·개행 제거)."""
    return "".join(ch for ch in s if 0x2800 <= ord(ch) <= 0x28FF and ch != SPACE)


def flat(s: str) -> str:
    """개행→공백 셀, 연속공백 1개로."""
    s = s.replace("\n", SPACE)
    out, prev_sp = [], False
    for ch in s:
        sp = ch == SPACE or ch == " "
        if sp and prev_sp:
            continue
        out.append(SPACE if sp else ch)
        prev_sp = sp
    return "".join(out).strip(SPACE)


def tokens(s: str) -> list[str]:
    return [t for t in flat(s).split(SPACE) if t]


# ── 거리/상관 ────────────────────────────────────────────────────────────
def lev_ratio(a: str, b: str) -> float:
    """정규화 Levenshtein 유사도 = 1 - dist/max(len)."""
    if not a and not b:
        return 1.0
    if not a or not b:
        return 0.0
    la, lb = len(a), len(b)
    prev = list(range(lb + 1))
    for i in range(1, la + 1):
        cur = [i] + [0] * lb
        ca = a[i - 1]
        for j in range(1, lb + 1):
            cost = 0 if ca == b[j - 1] else 1
            cur[j] = min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + cost)
        prev = cur
    return 1.0 - prev[lb] / max(la, lb)


def kendall_tau(pairs: list[tuple[int, int]]) -> float | None:
    """(gold_rank, our_rank) 쌍들의 Kendall τ. 쌍 2개 미만이면 None."""
    n = len(pairs)
    if n < 2:
        return None
    conc = disc = 0
    for i in range(n):
        for j in range(i + 1, n):
            s = (pairs[i][0] - pairs[j][0]) * (pairs[i][1] - pairs[j][1])
            if s > 0:
                conc += 1
            elif s < 0:
                disc += 1
    tot = conc + disc
    return (conc - disc) / tot if tot else None


# ── 수정비용 프록시 ──────────────────────────────────────────────────────
def edit_cost(gold_ns: str, our_ns: str, gtok: list[str], otok: list[str]) -> dict:
    """점역사가 우리 출력을 정답으로 고치는 편집량 추정.

    삽입/삭제는 셀 단위 diff로 잰다 — 어절 완전일치 기준은 띄어쓰기 정책 차이
    (§3 함정: 어절 분리 비대칭) 때문에 한 셀 오타도 어절 전체 삽입+삭제로 잡혀
    과대 추정된다. 이동(재배치)만 어절 단위로 감지: 양쪽 diff에 똑같은 어절이
    모두 등장하면 내용은 맞고 위치만 틀린 것.
    ⚠ 이동 어절의 셀은 삽입/삭제 셀 수에도 포함된다(순수 이동도 지웠다 다시 넣는
    비용으로 계상) — 별도 가중치 캘리브레이션은 태민 사항.
    """
    from collections import Counter
    from difflib import SequenceMatcher

    # 셀 단위: 삽입/삭제 셀 수 + diff 영역 수(찾기 비용)
    sm = SequenceMatcher(a=gold_ns, b=our_ns, autojunk=False)
    ins_cells = del_cells = regions = 0
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "equal":
            continue
        regions += 1
        ins_cells += i2 - i1   # 정답에만 → 점역사가 타이핑해 넣어야 함
        del_cells += j2 - j1   # 우리 출력에만 → 지워야 함

    # 어절 단위: 이동(재배치) 감지
    smt = SequenceMatcher(a=gtok, b=otok, autojunk=False)
    gold_missing: Counter = Counter()
    ours_extra: Counter = Counter()
    b_runs: list[list[str]] = []
    for tag, i1, i2, j1, j2 in smt.get_opcodes():
        if tag == "equal":
            continue
        if tag in ("delete", "replace"):
            gold_missing.update(gtok[i1:i2])
        if tag in ("insert", "replace"):
            ours_extra.update(otok[j1:j2])
            b_runs.append(otok[j1:j2])
    moved = sum((gold_missing & ours_extra).values())
    move_ops = 0
    for run in b_runs:
        if run and sum(1 for t in run if gold_missing.get(t)) / len(run) >= 0.5:
            move_ops += 1

    return {
        "edit_insert_cell": ins_cells,
        "edit_delete_cell": del_cells,
        "edit_moved_tok": moved,
        "edit_move_ops": move_ops,
        "edit_regions": regions,
        "edit_cost_norm": round((ins_cells + del_cells) / max(len(gold_ns), 1), 4),
    }


# ── 페어 채점 ────────────────────────────────────────────────────────────
def score_pair(our_uni: str, gold_uni: str) -> dict:
    our_flat, gold_flat = flat(our_uni), flat(gold_uni)
    our_ns, gold_ns = cells_only(our_uni), cells_only(gold_uni)
    gtok, otok = tokens(gold_uni), tokens(our_uni)

    # 토큰 overlap(부분문자열 기준, 길이 2셀 이상만 — 잡음 억제)
    g2 = [t for t in gtok if len(t) >= 2]
    o2 = [t for t in otok if len(t) >= 2]
    our_join, gold_join = our_ns, gold_ns  # 공백 무시 연결
    rec = sum(1 for t in g2 if t in our_join) / len(g2) if g2 else 0.0
    prec = sum(1 for t in o2 if t in gold_join) / len(o2) if o2 else 0.0
    f1 = (2 * prec * rec / (prec + rec)) if (prec + rec) else 0.0

    # 읽기순서: 양쪽에 정확히 1회만 등장하는 어절의 위치 순위상관
    from collections import Counter
    gc, oc = Counter(g2), Counter(o2)
    uniq = [t for t in g2 if gc[t] == 1 and oc.get(t) == 1]
    gpos = {t: i for i, t in enumerate(g2)}
    opos = {t: o2.index(t) for t in uniq}
    pairs = sorted(((gpos[t], opos[t]) for t in uniq))
    tau = kendall_tau(pairs)

    return {
        "cell_sim": round(lev_ratio(our_flat, gold_flat), 4),
        "cell_sim_ns": round(lev_ratio(our_ns, gold_ns), 4),
        "token_recall": round(rec, 4),
        "token_prec": round(prec, 4),
        "token_f1": round(f1, 4),
        "order_tau": round(tau, 4) if tau is not None else None,
        "n_gold_tok": len(g2),
        "n_our_tok": len(o2),
        "n_order_anchor": len(uniq),
        "len_gold_cell": len(gold_ns),
        "len_our_cell": len(our_ns),
        **edit_cost(gold_ns, our_ns, gtok, otok),
    }


# ── job 그룹 채점 ────────────────────────────────────────────────────────
def score_tag(tag: str) -> dict:
    jobs = sorted(STORAGE.glob(f"corpus-{tag}-*"))
    if not jobs:
        print(f"job 없음: corpus-{tag}-*"); return {}
    per_page, health = [], {"COMPLETED": 0, "NEEDS_REVIEW": 0, "TIMEOUT": 0, "ERROR": 0,
                            "other": 0, "tier": {}, "times_ms": []}
    for job in jobs:
        st = job / "run_state.json"
        if not st.exists():
            continue
        state = json.loads(st.read_text())
        subject = state["subject"]
        for p in state["pages"]:
            status = p.get("status")
            health[status if status in health else "other"] = \
                health.get(status if status in health else "other", 0) + 1
            if status in ("COMPLETED", "NEEDS_REVIEW"):
                t = p.get("tier")
                health["tier"][t] = health["tier"].get(t, 0) + 1
                if p.get("time_ms"):
                    health["times_ms"].append(p["time_ms"])
            page = p["page"]
            resp = job / "temp" / f"page_{p['local_no']:03d}" / "response.json"
            gold = gold_unicode(subject, page)
            if not resp.exists() or gold is None:
                continue
            r = json.loads(resp.read_text())
            our = linearize(r.get("braille_text_list") or [])
            m = score_pair(our, gold)
            m.update({"subject": subject, "page": page, "status": status})
            per_page.append(m)
    return {"tag": tag, "per_page": per_page, "health": health}


def aggregate(per_page: list[dict]) -> dict:
    keys = ["cell_sim", "cell_sim_ns", "token_recall", "token_prec", "token_f1", "order_tau",
            "edit_insert_cell", "edit_delete_cell", "edit_moved_tok", "edit_move_ops",
            "edit_regions", "edit_cost_norm"]
    def mean(k, rows):
        vals = [r[k] for r in rows if r.get(k) is not None]
        return round(statistics.mean(vals), 4) if vals else None
    agg = {"overall": {k: mean(k, per_page) for k in keys}, "n": len(per_page), "by_subject": {}}
    st_counts: dict[str, int] = {}
    for r in per_page:
        st = r.get("status") or "unknown"
        st_counts[st] = st_counts.get(st, 0) + 1
    agg["scored_by_status"] = st_counts
    subs = sorted({r["subject"] for r in per_page})
    for s in subs:
        rows = [r for r in per_page if r["subject"] == s]
        agg["by_subject"][s] = {**{k: mean(k, rows) for k in keys}, "n": len(rows)}
    return agg


def print_report(res: dict, agg: dict):
    h = res["health"]
    done, review = h.get("COMPLETED", 0), h.get("NEEDS_REVIEW", 0)
    tot = done + review + h.get("TIMEOUT", 0) + h.get("ERROR", 0) + h.get("other", 0)
    okrate = (done + review) / tot if tot else 0  # 출력 산출률(품질 플래그와 무관)
    times = h["times_ms"]
    print(f"\n=== 측정 결과 tag={res['tag']} ===")
    print(f"파이프라인: 출력 {done + review}/{tot} (ok_rate {okrate:.2%}, "
          f"COMPLETED {done} · NEEDS_REVIEW {review}) "
          f"timeout {h.get('TIMEOUT',0)} error {h.get('ERROR',0)} | tier {h['tier']} "
          f"| time median {int(statistics.median(times)) if times else 0}ms")
    o = agg["overall"]
    st = " · ".join(f"{k} {v}" for k, v in sorted(agg.get("scored_by_status", {}).items()))
    print(f"\n전체(n={agg['n']} — {st}): cell_sim={o['cell_sim']} cell_sim_ns={o['cell_sim_ns']} "
          f"token_f1={o['token_f1']}(R{o['token_recall']}/P{o['token_prec']}) order_tau={o['order_tau']}")
    if o.get("edit_cost_norm") is not None:
        print(f"수정비용(페이지 평균): 삽입 {o['edit_insert_cell']}셀 · 삭제 {o['edit_delete_cell']}셀 "
              f"· 이동 {o['edit_moved_tok']}어절({o['edit_move_ops']}블록) "
              f"· diff영역 {o['edit_regions']}곳 · cost_norm {o['edit_cost_norm']}")
    print(f"\n{'과목':<8}{'n':>4}{'cell_ns':>9}{'tok_f1':>8}{'tau':>7}")
    print("-" * 36)
    for s, v in agg["by_subject"].items():
        print(f"{s:<8}{v['n']:>4}{str(v['cell_sim_ns']):>9}{str(v['token_f1']):>8}{str(v['order_tau']):>7}")
    # 합격 기준 대조
    print("\n합격 기준 대조(절대 하한):")
    for k, th in THRESHOLDS.items():
        if k == "pipeline_ok_rate":
            v = okrate; ok = v >= th
        else:
            v = o.get(k); ok = (v is not None and v >= th)
        print(f"  {k:<16} {str(round(v,4) if isinstance(v,float) else v):>8} (≥{th})  {'PASS' if ok else 'FAIL'}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tag", required=True)
    ap.add_argument("--baseline", action="store_true", help="결과를 baseline.json으로 동결")
    args = ap.parse_args()

    res = score_tag(args.tag)
    if not res or not res.get("per_page"):
        print("채점할 완료 페이지 없음(스모크 진행 중일 수 있음)."); return
    agg = aggregate(res["per_page"])
    print_report(res, agg)

    REPORT.mkdir(parents=True, exist_ok=True)
    ts = time.strftime("%m%d_%H%M%S")
    out = REPORT / f"metrics_{args.tag}_{ts}.json"
    out.write_text(json.dumps({"agg": agg, "health": res["health"],
                               "per_page": res["per_page"]}, ensure_ascii=False, indent=2),
                   encoding="utf-8")
    print(f"\n저장: {out}")
    if args.baseline:
        bl = REPORT / "baseline.json"
        bl.write_text(json.dumps({"tag": args.tag, "frozen": ts, "agg": agg,
                                  "thresholds": THRESHOLDS}, ensure_ascii=False, indent=2),
                      encoding="utf-8")
        print(f"베이스라인 동결: {bl}")


if __name__ == "__main__":
    main()
