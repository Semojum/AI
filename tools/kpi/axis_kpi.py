"""축별 정확도 자 — 뭉쳐 재던 CER 을 **축마다** 갈라 무수정 비율을 낸다.

════════════════════════════════════════════════════════════════════════════
왜 만드나 (대표 지시 2026-09-08)
════════════════════════════════════════════════════════════════════════════
정방향 CER 한 수치로 본문·수식·표·시각자료·조판을 **다 뭉쳐** 재고 있었다. 그래서
"쉬운 것(한글 산문)은 지금 몇 %인가" 에 답을 못 했다. 목표(쉬운 것 99% · 어려운 것 90%)
를 세우려면 축마다 지금 값이 있어야 한다.

════════════════════════════════════════════════════════════════════════════
축을 어떻게 가르나 — **귀속 규칙을 코드로 남긴다**
════════════════════════════════════════════════════════════════════════════
1단계 · 요소 유형으로 (재추출 JSON `elements[].type`)
    text · list_item              → 2단계로 내려간다
    formula                       → 수식(M)
    table                         → 표(B)
    image · caption               → 시각자료(V)   ※ 이 축은 셀 대조가 자가 아니다. 아래 참조
    header_footer · page_number   → 쪽 furniture(H) — 축이 아니다. 따로 센다

2단계 · text/list_item 안에서 **문자 종류 런**으로
    `$…$` 구간                    → 수식(M)
    한글 음절·자모                → 본문(T)
    숫자                          → 숫자(N)
    로마자                        → 로마자(R)
    문장부호                      → 문장부호(P)
    그 밖                         → 기호·단위(Y)

  런 귀속은 **런을 따로 점역해 요소 통짜 점역에 정렬**해서 붙인다. 정렬 안 된 셀은
  `?`(미귀속)로 센다. 실측 귀속률 98.7%(표본 26쪽 · `temp/axis/probe2.py`).
  요소별 점역을 이어 붙인 것이 쪽 통짜 점역과 같은지도 확인했다 — 차이 0.008%
  (표본 14쪽 · `temp/axis/probe1.py`).

3단계 · gold 셀에 축 붙이기 (정렬 뒤)
    equal   → 정렬된 우리 셀의 축
    replace → 우리 쪽 블록의 축 구성비대로 gold 셀을 나눠 준다
    delete  → gold 에 없다. 우리 축의 **초과 출력**으로만 센다(분모에 안 들어간다)
    insert  → gold 만 있다(우리가 빠뜨렸다). gold 조각을 **역점역해 문자 종류로** 가른다.
              역점역 수율이 낮으면 앞 셀의 축을 물려받고, 그것도 없으면 `?`.

════════════════════════════════════════════════════════════════════════════
지표
════════════════════════════════════════════════════════════════════════════
  **무수정율(축) = 그 축의 gold 셀 중 우리가 그대로 낸 셀 ÷ 그 축의 gold 셀**
  초과출력(축)   = 그 축에서 gold 에 없는데 우리가 낸 셀 ÷ 그 축의 gold 셀

★ 무수정율은 **둘로 갈라 찍는다.** 안 가르면 "점역을 틀렸다" 와 "그 대목을 통째로
  못 냈다" 가 한 수치에 섞여 축 진단이 안 된다.
    · 무수정율(전체)   = 일치 ÷ gold                       ← 대표 목표와 견줄 값
    · 국소 정확도      = 일치 ÷ (일치 + 자리다툼 + **짧은** 누락/초과)  ← 점역 자체
    · 덩이 누락몫      = 10셀 이상 연속 누락 ÷ gold   (추출 누락·읽기순서·관행 차이)
  10셀을 가르는 근거: 낱말 하나를 잘못 점역하면 diff 조각이 1~9셀로 잘게 나온다.
  10셀 넘게 **연속** 어긋나려면 글 한 덩이가 통째로 한쪽에만 있어야 한다
  (`temp/bucket50/분류표.md` §1 — 50셀+ 구간은 98.8%가 점역 결함이 아니었다).

CER 과 달리 축마다 분모가 다르다. 합쳐도 전체 CER 이 되지 않는다(정의가 다르다).

════════════════════════════════════════════════════════════════════════════
따로 세는 것 — 축에 물리면 축이 실제보다 나빠 보인다
════════════════════════════════════════════════════════════════════════════
· **읽기순서** — 요소를 gold 자리 순으로 다시 놓고 잰다(`temp/fwd_baseline.py` FWD_ORDER
  팔과 같은 방법 · gold 를 보고 하는 오라클이라 **상한**이다). 정규화 전후 CER 차이를
  읽기순서 몫으로 찍고, 축 점수는 **정규화 뒤** 값으로 낸다.
· **코퍼스 짝 어긋남** — gold 쪽에만 해설이 실린 쪽(화법과 작문 등). 쪽을 빼지 않고
  플래그만 달아 그 쪽들의 몫을 따로 찍는다.
· **쪽 furniture** — 머리말·꼬리말·쪽번호. 제품 결함이 아니라 조판 층이다.

════════════════════════════════════════════════════════════════════════════
이 자가 **못 재는 것** (반드시 같이 읽어야 한다)
════════════════════════════════════════════════════════════════════════════
1. **빈칸·줄바꿈**. CER 과 같이 U+2800 과 줄바꿈을 지우고 본다
   (`code/AI/test/corpus_metrics.py:88-90`). 조판 축(칸수)은 `tools/kpi/spacing_kpi.py`
   가 잰다 — 여기서 안 잰다.
2. **시각자료 설명**. 정답이 하나가 아니라 셀 대조가 자가 안 된다(대표 2026-09-08).
   그 축은 `temp/axis/visual_axis.py` 가 구조·양식·문체 셋으로 잰다. 여기서는 V 축의
   셀 수치를 **참고로만** 찍고 목표를 걸지 않는다.
3. **추출 품질**. 묵자는 재추출 JSON 을 그대로 쓴다. 추출이 놓친 글은 gold-only 로
   잡혀 그 축의 무수정율을 깎는다. 그것이 점역 결함인지 추출 결함인지 이 자는 못 가른다.
4. **셀 빈도 ≠ 현상 빈도.** 축 귀속은 **묵자 원문 문자**로 한다(셀 점형으로 세지 않는다).
   gold-only 조각만 예외로 역점역을 쓰는데, 그 몫과 수율을 따로 찍는다.

════════════════════════════════════════════════════════════════════════════
어디서 재나 — CER·칸수 계기와 **같은 코퍼스·같은 쪽 집합**
════════════════════════════════════════════════════════════════════════════
  묵자 = `temp/poc/reextract/*.json` (Opus 5 재추출 1,361쪽)
  점자 = `corpus/pages/braille/EBS-E26-<bid>/<vol>/<page>.brf`
★ 분모는 **정답본이 있는 1,180쪽**이다. 수학 II·독서·영어듣기·세계지리·한국사는
  점자본이 없다(`temp/poc/rt_kpi.py` 상단 · `corpus/books.jsonl`).
  백틱 규약은 코퍼스 BRF 이므로 `backtick="cell"`.
자는 **제품 경로** `translate_body`(S1 #673)다. `translate_plain` 은 꼬리말 경로라 쓰지 않는다.

사용:
    code/AI/venv/bin/python tools/kpi/axis_kpi.py --dump temp/axis/pages.jsonl [코드경로]
    code/AI/venv/bin/python tools/kpi/axis_kpi.py --score temp/axis/pages.jsonl [--out r.json]
    code/AI/venv/bin/python tools/kpi/axis_kpi.py --selftest

변경 이력
  2026-09-08  신설(대표 지시 "축별로 갈라 지금 값을 대라").
"""
from __future__ import annotations

import collections
import difflib
import glob
import json
import os
import re
import sys
from multiprocessing import Pool

_HERE = os.path.dirname(os.path.realpath(__file__))          # <AI>/tools/kpi
AI_ROOT = os.path.dirname(os.path.dirname(_HERE))
V2 = os.path.dirname(os.path.dirname(AI_ROOT))               # /home/pj14/v2
REEXTRACT = os.path.join(V2, "temp/poc/reextract/*.json")
BRF = os.path.join(V2, "corpus/pages/braille/EBS-E26-{bid}/{vol}/{page}.brf")

# ── 축 ────────────────────────────────────────────────────────────────────
T, P, N, R, Y, M, B, V, H, F, U = "TPNRYMBVHF?"
AXIS_NAME = {
    T: "본문 텍스트(한글 산문)", P: "문장부호", N: "숫자", R: "로마자",
    Y: "기호·단위", M: "수식", B: "표", V: "시각자료(참고)",
    H: "쪽 furniture(축 아님)", F: "조판 장식(축 아님·아래 ★)", U: "미귀속",
}
# ★ F(조판 장식)는 **축이 아니라 gold-only 잔재의 이름표**다. 무수정율은 **구조상 늘 0.0%**다 —
#   hit 은 `equal` 조각에서만 오르는데 그 자리에는 우리 쪽 축 배열(`axis`)이 붙고, 그 배열에
#   F 는 절대 안 들어간다(F 는 `replace`/`insert` 의 gold 조각에서만 붙는다). 0.0% 를
#   "기능이 없다"로 읽으면 안 된다.
#   게다가 이 자의 `ours` 는 `temp/poc/reextract`(LLM 재추출, **bbox 없음**)를 요소마다
#   `translate_body` 한 것이라 `pdf_analyzer.tag_boxed_elements`·`LayoutBraille` 를 아예 안 탄다.
#   테두리는 그 두 단계에서만 나오므로 이 자에서는 원리적으로 한 셀도 안 나온다.
#   실측 2026-09-08(같은 1,180쪽, 제품 코드 ZERO 경로로 상자 태깅까지 돌림):
#     gold 1단계 상자 2,195 : 우리 1,644 · 2단계 439 : 119 · 3단계 3 : 8 → 합 67.2%.
#   즉 제품은 이미 낸다. F 의 gold셀 수는 "제품이 못 내는 양"이 아니라 "이 자가 안 재는 양"이다.
ELEM_AXIS = {"formula": M, "table": B, "image": V, "caption": V,
             "header_footer": H, "page_number": H}
SUBSPLIT = ("text", "list_item")

_PAGE_ROW = re.compile(r"^[a-z]?\d+\s.*\s\d+\s*$")
_TAG = re.compile(r"<!/?[^>]{1,40}>")
_CELL = re.compile(r"[^⠁-⣿]")
_MATH = re.compile(r"\$[^$]{1,400}\$")
_ANS_HEAD = re.compile(r"정답\s*[:：]|정답과\s*해설|해설\s*[:：]")
_PUNCT = set(".,!?;:'\"()[]{}·…‘’“”「」『』〈〉《》―—–-~/\\")
_K = 12                        # 자리 찾기 K-그램. difflib 은 셀 종류가 256뿐이라 못 쓴다
# gold 쪽 조판 장식(글상자 테두리 ⠿⠛⠛…·점선 ⠒⠒…·표 구분선 ⠐⠐…)을 가르는 최소 연속 길이.
# ★ 셀 하나로 가르면 안 된다 — ⠿ 는 약자 '옹' 이기도 하다(메모리: gold ⠿ 두 얼굴).
#   **연속 런** 으로만 가른다. 6셀은 실물 테두리 최소 길이(코퍼스 실측 9,023셀/143조각).
_DECOR_RUN = 6
# 알려진 조판 장식 셀은 4연속부터 장식으로 본다. 근거는 `temp/bucket50/분류표.md` §1
# A1 글상자 위 테두리 ⠛ · A2 아래 ⠶ · A3 점선 ⠒ · A4 표 구분선 ⠐ · A5 ⠉, 모서리 ⠿.
# ⚠ 이 셀들은 한글·수식 셀과 겹친다(⠿=약자 '옹'). **연속 런일 때만** 장식으로 센다.
_DECOR_CELLS = set("⠛⠶⠒⠐⠉⠿")
_DECOR_RUN_KNOWN = 4

# ── 역점역 신뢰 관문 ──────────────────────────────────────────────────────
# ★ 2026-09-08 반례로 붙였다. gold-only 조각을 역점역해 문자 종류로 축을 붙였더니
#   **로마자 축 덩이누락 65.7%** 가 나왔다. 표본을 보니 실물이 아니라 역점역 실패다 —
#   화법과 작문 body p0056 의 766셀이 `정ib:2(정ibo정ibqo유)(jaR{1)'z(η(nS지f여^…`
#   로 풀렸다. 조각이 수표·로마자표·대문자표 **구간 중간에서 시작**하면 디코더가
#   상태를 모른 채 풀어 라틴 문자·그리스 문자를 쏟는다. 그 쓰레기를 세면 '로마자' 가 된다.
#   → 풀린 글이 **읽을 수 있는 꼴**일 때만 축을 붙이고, 아니면 미귀속으로 센다.
_CLEAN = re.compile("[가-힣ㄱ-ㅎㅏ-ㅣ0-9A-Za-z\\s.,?!'\"()\\[\\]〈〉《》「」…·:;%~/-]")
_SUS = re.compile("[\u0370-\u03ff{}^_\\\\∞√∬∑∫∀∃⌒∠≡∽⊂⊃∪∩]")


def decode_ok(txt: str) -> bool:
    """역점역 결과를 축 귀속에 써도 되나. 반례는 위 주석 참조."""
    if len(txt) < 6:
        return False
    clean = len(_CLEAN.findall(txt)) / len(txt)
    sus = len(_SUS.findall(txt)) / len(txt)
    return clean >= 0.90 and sus <= 0.03


def cells(t: str) -> str:
    return _CELL.sub("", t)


def strip_print(t: str) -> str:
    """우리 태그와 쪽 머리행을 벗긴다 — fwd_baseline·spacing_kpi 와 같은 전처리."""
    t = _TAG.sub("", t)
    return "\n".join(l for l in t.split("\n")
                     if l.strip() and not _PAGE_ROW.match(l.strip()))


def char_axis(ch: str) -> str:
    o = ord(ch)
    if 0xAC00 <= o <= 0xD7A3 or 0x3130 <= o <= 0x318F:
        return T
    if "0" <= ch <= "9":            # ★ `ch.isdigit()` 은 ①⑴Ⅲ 까지 참이다 — 쓰면 안 된다
        return N
    if ("a" <= ch <= "z") or ("A" <= ch <= "Z"):
        return R
    if ch in _PUNCT:
        return P
    return Y


def runs(text: str) -> list[tuple[str, str]]:
    """[(축, 조각)]. `$…$` 는 통째로 수식."""
    out: list[tuple[str, str]] = []
    i = 0
    for m in _MATH.finditer(text):
        if m.start() > i:
            out += _plain_runs(text[i:m.start()])
        out.append((M, m.group()))
        i = m.end()
    out += _plain_runs(text[i:])
    return out


def _plain_runs(t: str) -> list[tuple[str, str]]:
    out: list[list[str]] = []
    for ch in t:
        if ch.isspace():                       # 공백은 앞 런에 붙인다(단독 런을 안 만든다)
            if out:
                out[-1][1] += ch
            else:
                out.append([T, ch])
            continue
        a = char_axis(ch)
        if out and out[-1][0] == a:
            out[-1][1] += ch
        else:
            out.append([a, ch])
    return [(a, s) for a, s in out]


# ── 점역·역점역 (자식 프로세스에서 늦게 연다) ──────────────────────────────
_tb = _decode = _a2u = _BOOKS = None


def _init(code_path: str) -> None:
    global _tb, _decode, _a2u, _BOOKS
    sys.path.insert(0, code_path)
    sys.path.insert(0, os.path.join(V2, "temp/poc"))
    from app.ai.braille.translator import translate_body
    from app.utils.braille_back import decode
    from app.utils.braille_ascii import ascii_to_unicode
    from rt_kpi import M as books                                   # 책ID ↔ 책이름
    _tb = lambda s: cells("\n".join(translate_body(s)[0]))          # noqa: E731
    _decode, _a2u, _BOOKS = decode, ascii_to_unicode, books


def elem_cells(kind: str, content: str) -> tuple[str, str]:
    """요소 하나 → (점자 셀, 셀마다의 축). 길이가 같다."""
    s = strip_print(content)
    if not s.strip():
        return "", ""
    out = _tb(s)
    fixed = ELEM_AXIS.get(kind)
    if fixed or kind not in SUBSPLIT:
        return out, (fixed or U) * len(out)
    rr = runs(s)
    parts = [(a, _tb(p) if p.strip() else "") for a, p in rr]
    joined = "".join(p for _, p in parts)
    lab = "".join(a * len(p) for a, p in parts)
    axis = [U] * len(out)
    for op, i1, i2, j1, j2 in difflib.SequenceMatcher(
            None, joined, out, autojunk=False).get_opcodes():
        if op == "equal":
            axis[j1:j2] = lab[i1:i2]
    return out, "".join(axis)


# ── 읽기순서 정규화 (fwd_baseline 과 같은 오라클) ──────────────────────────
def _index(g: str) -> dict:
    idx = collections.defaultdict(list)
    for i in range(len(g) - _K + 1):
        idx[g[i:i + _K]].append(i)
    return idx


def _locate(seg: str, idx: dict):
    n = len(seg) - _K + 1
    if n < 1:
        return 0.0, None
    votes, posmap = collections.Counter(), []
    for i in range(n):
        ps = idx.get(seg[i:i + _K])
        if ps:
            posmap.append((i, ps))
            for p in ps:
                votes[(p - i) // 64] += 1
    if not votes:
        return 0.0, None
    best = votes.most_common(1)[0][0] * 64
    got = [min(ps, key=lambda p: abs(p - i - best)) for i, ps in posmap
           if min(abs(p - i - best) for p in ps) <= 256]
    if not got:
        return 0.0, None
    got.sort()
    return len(got) / n, got[len(got) // 2]


def decor_spans(seg: str) -> list[tuple[int, int]]:
    """seg 안에서 같은 셀이 _DECOR_RUN 이상 이어지는 구간 [(시작, 끝)]."""
    out, i, n = [], 0, len(seg)
    while i < n:
        j = i + 1
        while j < n and seg[j] == seg[i]:
            j += 1
        if j - i >= (_DECOR_RUN_KNOWN if seg[i] in _DECOR_CELLS else _DECOR_RUN):
            out.append((i, j))
        i = j
    return out


def edits(a: str, b: str) -> int:
    sm = difflib.SequenceMatcher(None, a, b, autojunk=False)
    return sum(max(i2 - i1, j2 - j1) for op, i1, i2, j1, j2 in sm.get_opcodes()
               if op != "equal")


# ── 쪽 한 장 ──────────────────────────────────────────────────────────────
def dump_page(rf: str):
    d = json.load(open(rf, encoding="utf-8"))
    m = d.get("meta") or {}
    bid = next((k for k, v in _BOOKS.items() if v == m.get("book")), None)
    if not bid:
        return None
    path = BRF.format(bid=bid, vol=m["vol"], page=m["page"])
    if not os.path.exists(path):
        return None
    els = [e for e in (d.get("elements") or []) if (e.get("content") or "").strip()]
    want = strip_print("\n".join(e.get("content") or "" for e in els))
    if len(want) < 80:
        return None
    raw = open(path, encoding="utf-8", errors="ignore").read()
    gold = cells(raw if "⠁" in raw else _a2u(raw, backtick="cell"))
    if not gold:
        return None

    per: list[tuple[str, str]] = []
    for e in els:
        try:
            per.append(elem_cells(e.get("type") or "", e.get("content") or ""))
        except Exception:                                          # noqa: BLE001
            per.append(("", ""))
    ours_raw = "".join(c for c, _ in per)

    idx = _index(gold)
    keys, last = [], -1.0
    for c, _ in per:
        cv, ctr = _locate(c, idx) if c else (0.0, None)
        keys.append(ctr if (cv >= 0.30 and len(c) >= 24) else None)
    filled = []
    for k in keys:
        if k is None:
            filled.append(last + 1e-6)
        else:
            filled.append(float(k)); last = float(k)
    order = sorted(range(len(per)), key=lambda i: (filled[i], i))
    ours = "".join(per[i][0] for i in order)
    axis = "".join(per[i][1] for i in order)

    try:
        gold_txt = _decode(raw if "⠁" in raw else _a2u(raw, backtick="cell"))
    except Exception:                                              # noqa: BLE001
        gold_txt = ""
    return {
        "bid": bid, "book": _BOOKS[bid], "vol": m["vol"], "page": m["page"],
        "gold": gold, "ours": ours, "axis": axis,
        "cer_raw": edits(ours_raw, gold) / len(gold),
        "cer": edits(ours, gold) / len(gold),
        # 코퍼스 짝 어긋남: 점자 쪽에만 해설이 실렸다
        "ansmix": bool(_ANS_HEAD.search(gold_txt) and not _ANS_HEAD.search(want)),
    }


def cmd_dump(out: str, code_path: str) -> int:
    files = sorted(glob.glob(REEXTRACT))
    with Pool(12, initializer=_init, initargs=(code_path,)) as p:
        rows = [r for r in p.map(dump_page, files, chunksize=4) if r]
    os.makedirs(os.path.dirname(out) or ".", exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"{out}  쪽 {len(rows):,} · 코드 {code_path}")
    return 0


# ── 채점 ──────────────────────────────────────────────────────────────────
def _gaps(spans: list[tuple[int, int]], n: int) -> list[tuple[int, int]]:
    """spans 의 여집합 구간."""
    out, prev = [], 0
    for a, b in spans:
        if a > prev:
            out.append((prev, a))
        prev = b
    if prev < n:
        out.append((prev, n))
    return out


def score_page(row: dict, decode) -> dict:
    """한 쪽 → 축별 카운터. gold 셀 분모·일치·초과출력."""
    ours, gold, axis = row["ours"], row["gold"], row["axis"]
    gold_n = collections.Counter()      # 축별 gold 셀(분모) = hit + rep + ins
    hit = collections.Counter()         # 축별 일치
    rep = collections.Counter()         # 축별 자리다툼(우리도 냈는데 다르다)
    ins = collections.Counter()         # 축별 누락(gold 만 있다) — 짧은 것
    insL = collections.Counter()        # 축별 누락 — 10셀 이상 덩이
    over = collections.Counter()        # 축별 초과 출력 — 짧은 것
    overL = collections.Counter()       # 축별 초과 출력 — 10셀 이상 덩이
    ins_src = collections.Counter()     # 누락 귀속을 무엇으로 붙였나
    for op, i1, i2, j1, j2 in difflib.SequenceMatcher(
            None, ours, gold, autojunk=False).get_opcodes():
        if op == "equal":
            for a in axis[i1:i2]:
                gold_n[a] += 1; hit[a] += 1
        elif op == "delete":
            d = over if (i2 - i1) < 10 else overL
            for a in axis[i1:i2]:
                d[a] += 1
        elif op == "replace":
            comp = collections.Counter(axis[i1:i2])
            tot = sum(comp.values()) or 1
            gseg = gold[j1:j2]
            dec = sum(b - a for a, b in decor_spans(gseg))
            if dec:
                gold_n[F] += dec; rep[F] += dec
            m = (j2 - j1) - dec
            share = {a: v * m / tot for a, v in comp.items()} if m > 0 else {}
            for a, v in share.items():
                gold_n[a] += v; rep[a] += v
            if (i2 - i1) > m:                      # 우리가 더 냈다(장식 몫 제외한 gold 대비)
                d = over if (i2 - i1 - m) < 10 else overL
                for a, v in comp.items():
                    d[a] += v * (i2 - i1 - m) / tot
        else:                                      # insert — 우리가 빠뜨렸다
            seg = gold[j1:j2]
            dec = sum(b - a for a, b in decor_spans(seg))
            if dec:                                # 글상자 테두리·점선은 조판 장식이다
                d = ins if dec < 10 else insL
                gold_n[F] += dec; d[F] += dec
                ins_src["장식런"] += dec
                seg = "".join(seg[a:b] for a, b in _gaps(decor_spans(seg), len(seg)))
            m = len(seg)
            if m == 0:
                continue
            comp = None
            try:
                txt = decode(seg)
            except Exception:                      # noqa: BLE001
                txt = ""
            good = [c for c in txt if not c.isspace()]
            if len(good) >= 6 and decode_ok(txt):
                c = collections.Counter(char_axis(x) for x in good)
                if sum(c.values()):
                    comp = c
                    ins_src["역점역"] += m
            if comp is None and m < 10 and txt.strip() and \
                    len(_CLEAN.findall(txt)) == len(txt):
                # 짧은 조각은 역점역이 **깨끗이 풀릴 때만** 문자 종류로 가른다.
                # 안 그러면 빠뜨린 문장부호(⠴ ”·⠠⠴ ))가 이웃 축(본문)으로 밀려
                # 본문 국소 오류를 부풀린다(실측: 그 셈법에서 본문 국소편집 14,968셀 중
                # 절반 넘게가 실은 문장부호였다).
                c = collections.Counter(char_axis(x) for x in txt if not x.isspace())
                if c:
                    comp = c
                    ins_src["역점역(짧은 것)"] += m
            if comp is None and m < 10:
                # 그래도 못 풀면 정렬된 문맥의 이웃 축을 쓴다
                nb = axis[i1 - 1] if i1 > 0 else (axis[i1] if i1 < len(axis) else U)
                comp = collections.Counter({nb or U: 1})
                ins_src["이웃(짧은 것만)"] += m
            if comp is None:
                comp = collections.Counter({U: 1})
                ins_src["미귀속(역점역 실패한 덩이)"] += m
            tot = sum(comp.values())
            d = ins if m < 10 else insL
            for a, v in comp.items():
                gold_n[a] += v * m / tot; d[a] += v * m / tot
    return {"gold": gold_n, "hit": hit, "rep": rep, "ins": ins, "insL": insL,
            "over": over, "overL": overL, "src": ins_src}


def cmd_score(cache: str, out: str | None) -> int:
    sys.path.insert(0, AI_ROOT)
    from app.utils.braille_back import decode

    KEYS = ("gold", "hit", "rep", "ins", "insL", "over", "overL", "src")
    tot = {k: collections.Counter() for k in KEYS}
    per_book: dict = collections.defaultdict(
        lambda: {k: collections.Counter() for k in KEYS[:-1]})
    cer_raw = cer = 0.0
    npage = nans = 0
    ansmix_gold = 0.0
    rows = [json.loads(l) for l in open(cache, encoding="utf-8")]
    for r in rows:
        s = score_page(r, decode)
        npage += 1
        cer_raw += r["cer_raw"]; cer += r["cer"]
        for k in KEYS:
            tot[k].update(s[k])
        for k in KEYS[:-1]:
            per_book[r["book"]][k].update(s[k])
        if r["ansmix"]:
            nans += 1
            ansmix_gold += sum(s["gold"].values()) - sum(s["hit"].values())

    G = sum(tot["gold"].values())
    print(f"축별 정확도 자 · 쪽 {npage:,} · gold 셀 {G:,.0f}")
    print(f"  CER(정규화 전) {cer_raw/npage*100:6.2f}%   "
          f"CER(읽기순서 정규화 후) {cer/npage*100:6.2f}%   "
          f"→ 읽기순서 몫 {(cer_raw-cer)/npage*100:5.2f}%p (오라클 = 상한)")
    print(f"  코퍼스 짝 어긋남 쪽 {nans}쪽 · 그 쪽들의 미일치 gold 셀 {ansmix_gold:,.0f}"
          f" ({ansmix_gold/G*100:.2f}% of gold)\n")
    hdr = (f"{'축':22s}{'gold셀':>11s}{'몫':>7s}{'무수정율':>9s}"
           f"{'국소정확도':>11s}{'덩이누락':>9s}{'짧은초과':>9s}{'덩이초과':>9s}")
    print(hdr); print("-" * len(hdr))
    for a in (T, P, N, R, Y, M, B, V, H, F, U):
        g = tot["gold"][a]
        if g < 1:
            continue
        loc = tot["hit"][a] + tot["rep"][a] + tot["ins"][a] + tot["over"][a]
        print(f"{AXIS_NAME[a]:22s}{g:>11,.0f}{g/G*100:>6.1f}%"
              f"{tot['hit'][a]/g*100:>8.1f}%"
              f"{(tot['hit'][a]/loc*100 if loc else float('nan')):>10.1f}%"
              f"{tot['insL'][a]/g*100:>8.1f}%{tot['over'][a]/g*100:>8.1f}%"
              f"{tot['overL'][a]/g*100:>8.1f}%")
    print("\n  ★ 조판 장식 행은 축이 아니다 — 이 자는 요소별 translate_body 만 돌려"
          " 글상자 태깅·layout 을 안 탄다. 무수정율은 구조상 늘 0.0% 이고 제품 실측은"
          " 67.2%(2026-09-08)다. AXIS_NAME 위 주석 참조.")
    print(f"\n  누락(gold-only) 셀 귀속 근거: "
          + " · ".join(f"{k} {v:,}" for k, v in tot['src'].most_common()))

    print("\n책별 무수정율(전체 / 국소정확도) — 본문 T · 문장부호 P · 수식 M · 표 B")
    for bk, c in sorted(per_book.items(),
                        key=lambda kv: -(kv[1]["gold"][T] and
                                         1 - kv[1]["hit"][T] / kv[1]["gold"][T])):
        g = sum(c["gold"].values())
        cells_ = []
        for a in (T, P, M, B):
            gg = c["gold"][a]
            lo = c["hit"][a] + c["rep"][a] + c["ins"][a] + c["over"][a]
            cells_.append(
                f"{AXIS_NAME[a][:2]} {c['hit'][a]/gg*100:5.1f}%/{c['hit'][a]/lo*100:5.1f}%"
                if gg >= 200 and lo else f"{AXIS_NAME[a][:2]}      -     ")
        print(f"  {bk[:26]:26s} {g:>9,.0f}셀  " + "  ".join(cells_))
    if out:
        json.dump({"npage": npage, "gold_cells": G,
                   "cer_raw": cer / npage and cer_raw / npage, "cer": cer / npage,
                   "axis": {AXIS_NAME[a]: {k: tot[k][a] for k in
                                           ("gold", "hit", "rep", "ins", "insL",
                                            "over", "overL")}
                            for a in AXIS_NAME if tot["gold"][a]},
                   "per_book": {b: {k: dict(v) for k, v in c.items()}
                                for b, c in per_book.items()},
                   "ansmix_pages": nans},
                  open(out, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        print("\n→", out)
    return 0


# ── 자체 검사 ─────────────────────────────────────────────────────────────
def selftest() -> int:
    # ★ ① 은 `str.isdigit()` 이 참이라 숫자로 새기 쉽다. 기호(Y)로 가야 한다.
    assert [a for a, _ in runs("가나 1871년 $x^2$ ABC, ①")] == [T, N, T, M, T, R, P, Y], \
        runs("가나 1871년 $x^2$ ABC, ①")
    assert char_axis("①") == Y and char_axis("Ⅲ") == Y
    assert char_axis("가") == T and char_axis("7") == N and char_axis(".") == P
    assert char_axis("A") == R
    assert strip_print("<!주>가<!/주>\n\n12 제목 34\n나") == "가\n나"
    # 정렬 채점: 우리 ⠁⠃⠉ vs gold ⠁⠭⠉ → 축 T 2/3 일치
    row = {"ours": "⠁⠃⠉", "gold": "⠁⠭⠉", "axis": "TTT"}
    s = score_page(row, lambda x: "")
    assert s["hit"][T] == 2 and round(s["gold"][T]) == 3 and s["rep"][T] == 1, s
    # 초과 출력: 우리만 두 셀
    s2 = score_page({"ours": "⠁⠃⠉", "gold": "⠁", "axis": "TPP"}, lambda x: "")
    assert s2["over"][P] == 2 and s2["hit"][T] == 1, s2
    # 누락: gold 만 — 역점역이 한글을 내면 T 로 간다
    s3 = score_page({"ours": "⠁", "gold": "⠁⠃⠉⠙⠑⠋⠛⠓", "axis": "T"},
                    lambda x: "가나다라마바사")
    assert round(s3["gold"][T]) == 8 and s3["src"]["역점역"] == 7 \
        and round(s3["ins"][T]) == 7 and not s3["insL"], s3
    # 10셀 이상 누락은 덩이로 간다
    s4 = score_page({"ours": "⠁", "gold": "⠁" + "⠃⠉⠙⠑⠋⠛⠓⠊⠚⠈⠘⠸",
                     "axis": "T"}, lambda x: "가나다라마바사아자차카타")
    assert round(s4["insL"][T]) == 12 and not s4["ins"], s4
    # 조판 장식 런은 gold 쪽에서 F 로 빠진다 — ⠿ 하나는 약자라 안 빠져야 한다
    assert decor_spans("⠁⠛⠛⠛⠛⠛⠛⠁") == [(1, 7)] and decor_spans("⠿⠁⠿") == []
    assert decor_spans("⠁⠿⠛⠛⠛⠛⠁") == [(2, 6)]        # 알려진 장식 셀은 4연속부터
    assert decor_spans("⠁⠑⠑⠑⠑⠑⠁") == []              # 모르는 셀은 6연속 필요
    s5 = score_page({"ours": "⠁", "gold": "⠁" + "⠛" * 8, "axis": "T"}, lambda x: "")
    assert round(s5["gold"][F]) == 8 and not s5["gold"][T] - 1, s5
    assert decode_ok("이에 대한 설명으로 옳은 것만을 고른 것은?")
    assert not decode_ok("정ib:2(정ibo정ibqo유)(jaR{1)'z(η(nS지f여^(i{]자wja'요R{jv")
    print("selftest ok")
    return 0


def main(argv: list[str]) -> int:
    if "--selftest" in argv:
        return selftest()
    out = argv[argv.index("--out") + 1] if "--out" in argv else None
    if "--dump" in argv:
        cache = argv[argv.index("--dump") + 1]
        rest = [a for a in argv[1:] if not a.startswith("--")
                and a != cache and a != out]
        return cmd_dump(cache, rest[0] if rest else AI_ROOT)
    if "--score" in argv:
        return cmd_score(argv[argv.index("--score") + 1], out)
    print(__doc__)
    return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
