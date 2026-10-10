"""추출에서 빠진 본문 줄을 그 자리 글 요소에 원본 글자층으로 되살린다(#1303).

R1 '원본에 있는 글이 추출에서 빠짐'(#1285 · #1295 · #1299)은 표시만 했다. 점역사가 그 줄을 원본을 보고 다시 쳤다.
여기서는 같은 손실(`quality_checker.lost_text_hosts` 가 고른 것 그대로)을 그 자리 글 요소에 넣는다. R1 은 지우지 않고 문구만
'되살림'으로 바뀐다(층이 틀리면 되살린 글도 틀린다, #1302 와 같은 원칙).

★ 경계를 읽은 뒤(Phase 2), 분해 전에 한다. 경계 파일은 안 바뀐다. 넣을 손실을 고르는 `lost_text_hosts` 가 경계 밖(품질
  검사)에 있고 R1 과 같은 손실을 봐야 해서다. 그래서 경계 지문(`pipeline._EXTRACT_SOURCES`)에 넣지 않는다.

넣는 자리: 빠진 줄 조각마다 그 가운데를 품은 글 요소(겹친 넓이가 가장 큰 것, 같으면 경계 순서가 앞선 것).
  · 채우기: 요소 글에 한글이 하나도 없다(번호 · 문장부호만 남음, 언매 p0096 '②，'). 앞뒤 태그를 남기고 그 자리 줄로 채운다.
  · 끼우기: 요소 사각형 안 층 줄을 층 차례로 늘어놓고, 빠진 줄 앞뒤 줄이 요소 글에 그 차례로 있을 때만 그 사이에 넣는다.
    쪽 전체 차례는 안 쓴다(다단 · 회전 지면에서 틀린다). 앞이나 뒤에 줄이 있는데 요소 글에서 못 찾으면 안 넣는다 — MinerU 가
    그 줄을 엉뚱한 글자로 읽어 둔 자리일 수 있다(언매 p0085 옛한글 줄이 두 벌이 됐다). 앞뒤 줄과 같은 단이어야 한다.
  · 손실 하나는 다 넣거나 하나도 안 넣는다. 못 넣는 손실이 나오면 그 손실을 빼고 처음부터 다시 맞춘다.
안 넣는 손실은 R1 만 그대로다: 그 자리가 글 요소가 아님(표 · 수식) · 앞뒤 줄을 못 찾음 · 층 차례와 요소 글 차례가 어긋남 ·
  층을 못 믿음 · 넣을 글이 손실 글과 다름 · 쪽 다른 자리에 이미 있음 · 채우기로 지워질 글자(번호 · 글자)가 넣을 글에 없음 ·
  첫 줄이 다른 요소의 문장을 잇는 줄임(2단 사진 설명 '하는 토기로, …', 동아시아사 p0020).
넣는 글은 층 덮기(#1078)와 같은 `_native_text_pair` 로 뽑는다. 이 길이 윤디자인 기호(#1087)와 한양 옛한글(#1092) PUA 를
  푼다. 손실 목록 글(`extraction_losses._layer_lines`)은 PUA 를 지운 글이라 그대로 넣으면 '오○○입니다' 가 '오입니다' 가 된다.
  그래도 남는 PUA 는 지우고 센다(R15 와 같은 원칙). 그 수가 R1 문구에 실린다.
줄 사이 이음매는 줄 잇기가 요소 안 개행을 푸는 판정(`line_join._resolve_inner_newlines`)과 같다. 다만 MinerU 가 한 문단으로
  이어 둔 요소(개행 없음)에 끼울 때는 단 끝 판정 없이 원본 줄 끝 공백대로 잇는다(언매 해설 p0024 '…있으므' + '로 적절한').
끄기 `LOST_TEXT_RESTORE=0`.
"""
from __future__ import annotations

import os
import re
import unicodedata
from difflib import SequenceMatcher

import fitz

from app.ai.parser import extraction_losses as EL
from app.ai.parser.mineru_runner import _layer_untrustworthy, _native_text_pair, _table_layer
from app.ai.preprocessor import line_join as LJ
from app.ai.quality.quality_checker import _overlap, lost_text_hosts

_TEXTY = frozenset({"text", "list_item", "title"})
_ANCHOR = 6               # 앞 줄 꼬리 · 뒤 줄 머리를 요소 글에서 그대로 찾는 글자 수
_SAME_MIN = 0.9           # 넣을 글과 손실 글(한글만)이 이만큼 같아야 넣는다(사각형이 이웃 줄을 덮어 딸려 온 글 막기)
_PUA_RE = re.compile("[\ue000-\uf8ff\U000f0000-\U0010fffd]")
_HANGUL_RE = re.compile("[가-힣]")
_LEAD_RE = re.compile(r"^(?:\s*<![^<>]*>)*\s*")
_TRAIL_RE = re.compile(r"\s*(?:<![^<>]*>\s*)*$")


def restore_lost_lines(elements: list[dict], losses: list[dict] | None, page: fitz.Page,
                       math_page: bool) -> dict[str, tuple[str, int]]:
    """R1 로 띄울 손실을 그 자리 글 요소에 넣는다(요소 content 를 고친다). → {손실 글: (넣은 글, 못 살린 PUA 수)}.

    `elements` 는 0~1000 경계 요소다. 넣을지는 고치기 전 요소 글로 정한다(먼저 넣은 글이 뒤 손실 판정을 바꾸지 않게).
    """
    if math_page or not losses or os.environ.get("LOST_TEXT_RESTORE", "1") == "0":
        return {}
    layer = EL._layer_lines(page)
    pool = EL._Pool(e.get("content") for e in elements)
    elig: list[tuple[dict, list[tuple]]] = []
    for x in losses:
        if not lost_text_hosts([x], elements, math_page):
            continue
        if not any(_overlap(e.get("bbox"), x.get("bbox")) for e in elements):
            continue                                              # 가까운 요소에만 붙는 손실(#1301)은 새 요소 몫이다
        rows = _rows_of(x, layer, page)
        if rows and (x.get("reason") == "sibling" or not pool.has(EL._plain(x["text"]))):
            elig.append((x, rows))                                # 이웃 줄 손실은 그 대조로 잡힌 것이라 쪽 전체 대조를 안 한다
    lost_all = {id(rt) for _x, rows in elig for rt in rows}
    cand: list[tuple[dict, list[tuple[tuple, int]]]] = []         # (손실, [(층 줄 조각, 넣을 요소 차례)])
    for x, rows in elig:
        placed = [(rt, _host_of(rt[0], elements, page)) for rt in rows]
        if any(k is None for _rt, k in placed) or _continues(rows[0], placed[0][1], layer, elements, page, lost_all):
            continue
        cand.append((x, placed))
    cols = [r for r, _t in LJ._page_lines(page)]
    while cand:
        work, fails = _apply(cand, elements, page, layer, cols)
        if not fails:
            for k, content in work.items():
                elements[k]["content"] = content
            out = {}
            for x, placed in cand:
                got = _block(page, cols, [rt for rt, _k in placed])
                out[x["text"]] = (got[0], got[1]) if got else (x["text"], 0)
            return out
        cand = [c for c in cand if id(c[0]) not in fails]
    return {}


def _apply(cand, elements, page, layer, cols) -> tuple[dict[int, str], set[int]]:
    """손실들을 넣어 본다 → ({요소 차례: 고친 글}, 못 넣은 손실 id 들)."""
    work: dict[int, str] = {}
    fails: set[int] = set()
    fill: dict[int, list[tuple[tuple, dict]]] = {}               # 채우기 요소 → [(줄 조각, 손실)]
    for x, placed in cand:
        for rt, k in placed:
            if not _HANGUL_RE.search(_squash(elements[k].get("content") or "")[0]):
                fill.setdefault(k, []).append((rt, x))
    for k, items in fill.items():
        rows = sorted({id(rt): rt for rt, _x in items}.values(), key=layer.index)
        got = _block(page, cols, rows)
        text = "\n".join(t for _r, t in rows)
        filled = _fill(elements[k].get("content") or "", got[0]) if got and _same(got[0], text) else None
        if filled is None:
            fails |= {id(x) for _rt, x in items}
        else:
            work[k] = filled
    lost = {id(rt) for _x, placed in cand for rt, _k in placed}
    for x, placed in cand:
        if id(x) in fails:
            continue
        groups: dict[int, list[tuple]] = {}
        for rt, k in placed:
            if k not in fill:
                groups.setdefault(k, []).append(rt)
        for k, rows in groups.items():
            got = _block(page, cols, rows)
            mine = [rt for rt in layer if _center_in(EL._norm(rt[0], page), elements[k]["bbox"])]
            put = _insert(page, cols, work.get(k, elements[k].get("content") or ""), rows, mine, lost, got) if got else None
            if put is None:
                fails.add(id(x))
                break
            work[k] = put
    return work, fails


def _rows_of(x: dict, layer: list[tuple], page: fitz.Page) -> list[tuple]:
    """손실 글의 층 줄 조각(손실 사각형 안, 층 차례). 같은 글이 쪽 다른 자리에 또 있어도 그 줄은 안 집는다."""
    keys = {"".join(t.split()) for t in x["text"].split("\n")}
    return [rt for rt in layer if "".join(rt[1].split()) in keys and _center_in(EL._norm(rt[0], page), x["bbox"])]


def _center_in(b, box) -> bool:
    cx, cy = (b[0] + b[2]) / 2, (b[1] + b[3]) / 2
    return bool(box) and box[0] - 3 <= cx <= box[2] + 3 and box[1] - 3 <= cy <= box[3] + 3


def _area(a, b) -> float:
    return max(0, min(a[2], b[2]) - max(a[0], b[0])) * max(0, min(a[3], b[3]) - max(a[1], b[1]))


def _host_of(r: fitz.Rect, elements: list[dict], page: fitz.Page) -> int | None:
    """줄 조각의 가운데를 품은 글 요소 차례. 여럿이면 겹친 넓이가 가장 큰 것, 같으면 경계 순서가 앞선 것. 글 요소가 아니면 None."""
    nb = EL._norm(r, page)
    hits = [k for k, e in enumerate(elements) if _center_in(nb, e.get("bbox"))]
    if not hits:
        return None
    k = max(hits, key=lambda i: (_area(elements[i]["bbox"], nb), -i))
    return k if elements[k].get("type") in _TEXTY else None


def _continues(first: tuple, k: int, layer: list[tuple], elements: list[dict], page: fitz.Page,
               lost_all: set[int]) -> bool:
    """첫 줄이 바로 윗줄의 문장을 잇는데, 그 윗줄이 이 요소 글에도 없고 같이 넣을 빠진 줄도 아닌가.
    그러면 문장 앞머리가 다른 요소에 있다 — 이 요소에 넣으면 문장이 두 요소로 찢긴다(동아시아사 p0020 사진 설명
    '달한 양사오 문화를 대표' / '하는 토기로, 물고기 무늬 …' 의 뒷줄이 코드 번호 상자에 들어갔다)."""
    i = layer.index(first)
    if i == 0 or id(layer[i - 1]) in lost_all:
        return False
    (pr, pt), (r, t) = layer[i - 1], first
    if _find("".join(pt.split()), _squash(elements[k].get("content") or "")[0], True) >= 0:
        return False
    line = r.y1 - r.y0
    return (line > 0 and LJ._x_overlap(pr, r) >= LJ._JOIN_COL_OVERLAP
            and -0.5 * line <= r.y0 - pr.y1 <= LJ._JOIN_LINE_GAP * line
            and not LJ._SENT_END_RE.search(pt.rstrip()) and LJ._is_continuation_head(t.lstrip())
            and not LJ._ITEM_HEAD_RE.match(t.lstrip()))


def _squash(s: str) -> tuple[str, list[int]]:
    """태그 · 공백을 뺀 글과 그 글자마다 원문 자리."""
    out, idx, i = [], [], 0
    while i < len(s):
        m = EL._TAG_RE.match(s, i) if s[i] == "<" else None
        if m:
            i = m.end()
            continue
        if not s[i].isspace():
            out.append(s[i])
            idx.append(i)
        i += 1
    return "".join(out), idx


def _find(row: str, flat: str, head: bool) -> int:
    """층 줄(공백 뺀 글)이 요소 글(flat)에서 시작하는(head) · 끝나는 자리. 못 찾으면 -1.
    가장 긴 공통 토막으로 대략 자리를 잡고, 머리 · 꼬리 _ANCHOR 자가 그대로 있는 곳 중 가장 가까운 데(같으면 앞)를 고른다."""
    if len(row) < 4 or not flat:
        return -1
    m = SequenceMatcher(None, row, flat, autojunk=False).find_longest_match(0, len(row), 0, len(flat))
    if m.size < min(8, len(row)):
        return -1
    est = m.b - m.a + (0 if head else len(row))
    key = row[:_ANCHOR] if head else row[-_ANCHOR:]
    hits, k = [], flat.find(key)
    while k >= 0:
        hits.append(k if head else k + len(key))
        k = flat.find(key, k + 1)
    return min(hits, key=lambda h: (abs(h - est), h)) if hits else -1


def _seam(page: fitz.Page, cols: list[fitz.Rect], r: fitz.Rect, cur: str, nxt: str, flow: bool = False) -> str:
    """cur 줄(자리 r) 뒤에 nxt 를 붙일 이음매. `line_join._resolve_inner_newlines` 안쪽 판정과 같다.
    flow(MinerU 가 한 문단으로 이어 둔 요소)면 단 끝 판정을 건너뛴다.
    붙임 · 띄움은 `_line_seam` 이 원본 줄 끝 공백으로 정한다. 그 함수는 넘긴 글이 층 줄과 글자째 같아야 하는데, 층 줄에는
    PUA(옛한글 · 가림 ○○)가 있고 우리 글에는 없다. 그래서 그 자리 층 줄 글을 그대로 넘긴다(자리가 줄 하나라 안 섞인다)."""
    line = r.y1 - r.y0
    if line <= 0 or not cur.strip() or not nxt.strip():
        return "\n"
    right, flush = LJ._col_edge(cols, r)
    if ((flow or (flush >= LJ._JOIN_FLUSH_MIN and abs(right - r.x1) <= LJ._JOIN_RIGHT_SLACK * line))
            and not LJ._ITEM_HEAD_RE.match(nxt.lstrip()) and LJ._is_continuation_head(nxt.lstrip())
            and not LJ._SENT_END_RE.search(cur.rstrip())):
        raw = page.get_textbox(r).rstrip("\n").split("\n")[-1]
        return LJ._line_seam(page, r, raw, nxt)
    return "\n"


def _visual_rows(rows: list[tuple]) -> list[list[tuple]]:
    """층 줄 조각 [(자리, 글)]을 인쇄 한 줄씩 묶는다(세로로 절반 넘게 겹치면 한 줄, 정답표 · 선택지 조각)."""
    out: list[list[tuple]] = []
    for r, t in rows:
        if out:
            p = out[-1][-1][0]
            if min(p.y1, r.y1) - max(p.y0, r.y0) > 0.5 * min(p.height, r.height):
                out[-1].append((r, t))
                continue
        out.append([(r, t)])
    return out


def _block(page: fitz.Page, cols: list[fitz.Rect], rows: list[tuple]) -> tuple[str, int, list[tuple]] | None:
    """빠진 층 줄 조각 → (넣을 글, 못 살린 PUA 수, 인쇄 줄 [(자리, 층 글)]). 층을 못 믿으면 None."""
    texts, lines, miss = [], [], 0
    for vr in _visual_rows(rows):
        r = fitz.Rect(vr[0][0])
        for rr, _t in vr[1:]:
            r |= rr
        # 제어 문자(InDesign 표지 \x07 · U+200C · 빈 글리프 \x01)는 띄우고 나서 믿을지 본다. 표 경로와 같다(#1148).
        plain, t = map(_table_layer, _native_text_pair(page, EL._norm(r, page)))
        if not plain.strip() or _layer_untrustworthy(plain, page):
            return None
        miss += len(_PUA_RE.findall(t))
        texts.append(" ".join(_PUA_RE.sub("", t).split()))
        lines.append((r, " ".join(t_ for _r, t_ in vr)))
    out = texts[0]
    for k in range(1, len(texts)):
        seam = _seam(page, cols, lines[k - 1][0], lines[k - 1][1], lines[k][1])
        out = (out.rstrip() + seam + texts[k].lstrip()) if seam != "\n" else out + "\n" + texts[k]
    return out, miss, lines


def _same(block: str, text: str) -> bool:
    """넣을 글과 손실 글이 같은 글인가(한글만 맞댄다, 손실 글은 PUA 를 지운 글이라 기호 · 옛한글은 안 본다)."""
    a, b = "".join(_HANGUL_RE.findall(block)), "".join(_HANGUL_RE.findall(text))
    return bool(b) and SequenceMatcher(None, a, b, autojunk=False).ratio() >= _SAME_MIN


def _fill(c: str, block: str) -> str | None:
    """요소 글 c 를 넣을 글로 채운 글. 앞뒤 태그는 남긴다. 지워질 글자(번호 · 글자, 문장부호 말고)가 넣을 글에 없으면 None."""
    lead = _LEAD_RE.match(c).group(0)
    trail = _TRAIL_RE.search(c[len(lead):]).group(0)
    gone = c[len(lead):len(c) - len(trail)]
    if any(unicodedata.category(ch)[0] in "LN" and ch not in block for ch in gone):
        return None
    return lead + block + trail


def _insert(page: fitz.Page, cols: list[fitz.Rect], c: str, rows: list[tuple], mine: list[tuple],
            lost: set[int], got: tuple[str, int, list[tuple]]) -> str | None:
    """빠진 줄 조각(rows) 앞뒤 층 줄이 요소 글 c 에 같은 차례로 있으면 그 사이에 넣은 글. 아니면 None."""
    block, _miss, lines = got
    if not _same(block, "\n".join(t for _r, t in rows)):
        return None
    flat, idx = _squash(c)
    mine_ids = {id(rt) for rt in rows}
    seq = [(id(rt) in mine_ids, rt) for rt in mine if id(rt) in mine_ids or id(rt) not in lost]   # 다른 손실 줄은 앞뒤 줄로 안 쓴다
    at = [i for i, (is_lost, _rt) in enumerate(seq) if is_lost]
    if not at:
        return None
    heads = [_find("".join(rt[1].split()), flat, True) for is_lost, rt in seq if not is_lost]
    found = [h for h in heads if h >= 0]
    if found != sorted(found):                                # 층 차례 ≠ 요소 글 차례(다단 · 섞인 순서)
        return None
    prev = next((rt for is_lost, rt in reversed(seq[:at[0]]) if not is_lost), None)
    nxt = next((rt for is_lost, rt in seq[at[-1] + 1:] if not is_lost), None)
    end = _find("".join(prev[1].split()), flat, False) if prev else -1
    start = _find("".join(nxt[1].split()), flat, True) if nxt else -1
    # 앞(뒤)에 줄이 있는데 요소 글에서 못 찾으면 자리를 못 믿는다. 앞뒤 줄과 같은 단이어야 한다.
    if (prev and end < 0) or (nxt and start < 0) or not (prev or nxt):
        return None
    if (prev and LJ._x_overlap(prev[0], lines[0][0]) < LJ._JOIN_COL_OVERLAP) or \
            (nxt and LJ._x_overlap(nxt[0], lines[-1][0]) < LJ._JOIN_COL_OVERLAP):
        return None
    flow = "\n" not in c
    if prev and nxt:
        a, b = idx[end - 1] + 1, idx[start]
        if a > b or c[a:b].strip():                           # 앞뒤 줄 사이에 다른 글 · 태그가 있으면 자리를 못 믿는다
            return None
        return (c[:a] + _seam(page, cols, prev[0], prev[1], lines[0][1], flow) + block
                + _seam(page, cols, lines[-1][0], lines[-1][1], nxt[1], flow) + c[b:])
    if prev:
        a = idx[end - 1] + 1
        return c[:a] + _seam(page, cols, prev[0], prev[1], lines[0][1], flow) + block + c[a:]
    b = idx[start]
    return _drop_head(c[:b], block) + block + _seam(page, cols, lines[-1][0], lines[-1][1], nxt[1], flow) + c[b:]


def _drop_head(pre: str, block: str) -> str:
    """넣을 자리 바로 앞(같은 줄)에 한글 없는 머리만 남아 있으면 뺀다: 넣을 글이 그 머리로 시작하거나(MinerU 가 두 줄
    선택지의 첫 줄을 버리고 번호만 남긴 꼴, 언매 해설 p0024 '②한 분석이다.') 문장부호 · 기호뿐일 때(화작 p0162 '，')."""
    m = re.search(r"([^\n>]*)$", pre)
    tail = m.group(1).strip() if m else ""
    if tail and not _HANGUL_RE.search(tail) and (
            block.startswith(tail) or all(unicodedata.category(ch)[0] in "PSZ" for ch in tail)):
        return pre[:len(pre) - len(m.group(1))]
    return pre
