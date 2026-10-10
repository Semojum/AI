"""추출 손실 목록(T35) — 이 쪽에서 추출이 못 본 글과, MinerU 는 봤는데 경계까지 못 온 글.

경계 파일의 `extraction_losses` 로 나간다. 채점기가 미커버 gold 를 갈래로 나눌 때 읽는다
(T33 에서 손으로 가른 층 대조를 파이프라인이 스스로 단다). 면제받으려고 다는 것이 아니라
**어디를 고칠지** 정하려고 다는 것이다.

  class   "unseen"  텍스트 레이어엔 있는데 MinerU 글에도 경계 요소 글에도 없다(T33 D).
          "dropped" MinerU 항목 글인데 경계 요소 글에 없다(T33 C).
  source  "textlayer" | "mineru:<content_list type>" | "mineru:<펼친 필드>"(table_footnote·code_body …)
  reason  dropped 만. "figure_text"(그림·그래프 안 글, 캡셔닝 몫으로 둔다) | "not_carried"(그 밖)
          · "sibling"(두 갈래 다): 같은 틀 이웃 줄에 가려 쪽 전체 대조로는 '있음'이던 층 줄(#1298, 아래 절)
  region  unseen 만. 그 글 자리에 걸친 MinerU 항목 type(없으면 None). 영역을 잘못 본 것인지
          영역조차 없는 것인지 가른다(T33 "D 의 MinerU 자리").
  text    그 글(묵자). 채점기가 gold 해독문과 음절 n-gram 으로 맞춘다.
  bbox    0~1000 정규화 [x0, y0, x1, y1] (회전 뒤 지면 좌표).

대조는 T33 층 대조와 같다. 공백·기호를 뺀 글자열에서 음절 6-gram 이 덮는 몫이 50% 이상이면
"있다" 로 본다. 6자보다 짧은 글은 부분 문자열로 본다.

★ 목록이 비었다고 손실이 없는 것이 아니다. 무엇을 대조했는지는 함께 돌려주는 `checks` 에 있다
  ("mineru" = MinerU 원출력과 대조함, "text_layer" = 텍스트 레이어와 대조함). 스캔본은 레이어가 남의
  OCR 이라 "text_layer" 가 빠지고 unseen 을 아예 안 잰다. 그 밖의 쪽은 줄마다 가려 PUA·깨진 글리프 줄과
  한컴 수식 글꼴 스팬만 뺀다. 빠진 줄은 목록에 안 오른다.
"""
from __future__ import annotations

import json
import re
from difflib import SequenceMatcher
from pathlib import Path

import fitz

from app.ai.preprocessor.pdf_analyzer import _MANGLED_LAYER_RE
from app.ai.parser.mineru_runner import (
    _MATH_FONT_RE,
    _MATH_PAGE_MIN_SHARE,
    _MATH_STRUCT_FONT_RE,
    _find_content_list,
    _is_scanned_page,
    _squash_text,
    _unfold_nested,
)

_TAG_RE = re.compile(r"<[^<>]{0,80}>")    # 경계 태그(<!상자>…)·표 HTML(<td>…) — 이름 글자가 대조를 흐린다
_N = 6                                    # 음절 n-gram 길이(T33 층 대조와 같다)
_COVER = 0.5                              # 이 몫 이상 덮이면 "있다"
_MIN_CHARS = 6                            # 이보다 짧은 손실 글은 적지 않는다(①·㉠ 같은 조각은 대조가 안 된다)
_FIGURE_TYPES = frozenset({"image", "chart"})
_BOX_TOL = 3                              # region 판정 여유(0~1000)
# 레이어 줄에서 빼는 글자: 글꼴 매핑이 어긋나 나온 자리(`pdf_analyzer._MANGLED_LAYER_RE`) · 사설 영역(PUA)
_BAD_CHAR_RE = re.compile(f"{_MANGLED_LAYER_RE.pattern}|[\ue000-\uf8ff\U000f0000-\U0010fffd]")


def _plain(s: str | None) -> str:
    return _squash_text(_TAG_RE.sub(" ", s or ""))


class _Pool:
    """대조 대상 글 묶음. 조각 사이에 구분자를 넣어 경계를 넘는 n-gram 이 안 생기게 한다."""

    def __init__(self, texts):
        self.s = "\x00".join(q for q in map(_plain, texts) if q)
        self.grams = {self.s[i:i + _N] for i in range(len(self.s) - _N + 1)}

    def hits(self, q: str) -> bytearray:
        """q 의 글자마다 이 묶음의 n-gram 에 덮이면 1. n 보다 짧은 q 는 통째로 부분 문자열인지 본다."""
        hit = bytearray(len(q))
        if len(q) < _N:
            if q and q in self.s:
                hit[:] = b"\x01" * len(q)
            return hit
        for i in range(len(q) - _N + 1):
            if q[i:i + _N] in self.grams:
                hit[i:i + _N] = b"\x01" * _N
        return hit

    def has(self, q: str) -> bool:
        return bool(q) and sum(self.hits(q)) >= _COVER * len(q)


def _far(a: fitz.Rect | None, b: fitz.Rect | None) -> bool:
    if a is None or b is None:
        return False
    return b.y1 < a.y0 or b.y0 - a.y1 > 2 * max(a.height, 1.0)


def _lost_runs(parts: list[tuple], pools: list[_Pool]) -> list[list[tuple]]:
    """한 덩이(레이어 블록 · MinerU 항목)의 줄들 [(자리, 글)] 중 **어느 묶음에도 없는 줄이 이어진 토막**.

    덩이 글을 이어 붙인 채로 덮는다. 줄 하나씩 재면 `정답` · `1. 가설` 같은 짧은 줄이 흔한 조각이라
    어딘가의 부분 문자열로 걸려 "있음" 이 된다(dev 생명과학 p10 정답 칸이 통째로 안 잡혔다).
    이어 붙이면 짧은 줄도 이웃과 같이 n-gram 으로 잰다. 기호뿐인 줄(글자 0)은 토막을 끊지 않는다.
    자리(Rect)가 있으면 줄이 멀리 떨어질 때(위로 올라감 = 다른 단 · 세로로 두 줄 높이 넘게 벌어짐) 토막을 끊는다.
    """
    qs = [_plain(t) for _, t in parts]
    s = "".join(qs)
    hit = bytearray(len(s))
    for pool in pools:
        for i, h in enumerate(pool.hits(s)):
            hit[i] |= h
    runs: list[list[tuple]] = []
    run: list[tuple] = []
    pos = 0
    for part, q in zip(parts, qs):
        n = len(q)
        if n and sum(hit[pos:pos + n]) < _COVER * n:
            if run and _far(run[-1][0], part[0]):
                runs.append(run)
                run = []
            run.append(part)
        elif n and run:
            runs.append(run)
            run = []
        pos += n
    if run:
        runs.append(run)
    return [r for r in runs if len(_plain("".join(t for _, t in r))) >= _MIN_CHARS]


def _item_text(it: dict, fig_text: dict[int, str]) -> str:
    kind = it.get("type")
    if kind in _FIGURE_TYPES:
        # 그림 안 글은 MinerU 가 안 적는 일이 많다(카드 뉴스·지도). 레이어 줄이 있으면 그 줄들을 쓴다.
        return fig_text.get(id(it)) or it.get("content") or ""
    if kind == "table":
        return it.get("table_body") or ""
    if kind == "list":
        return "\n".join(it.get("list_items") or [])
    return it.get("text") or ""


def _layer_lines(page: fitz.Page) -> list[tuple[fitz.Rect, str]]:
    """믿을 수 있는 레이어 줄 [(회전 뒤 자리, 글)].

    레이어 신뢰는 **줄마다** 가른다 — 쪽 글 전체로 가르면 글꼴 매핑이 몇 글자만 어긋난 쪽까지 통째로
    빠진다(dev 121쪽 중 99쪽). 파이프라인도 블록마다 가른다(`_native_override`).
    한컴 수식 글꼴(EH·ST) 스팬은 **수식 쪽에서만** 뺀다. 수학Ⅰ p52 는 `EHsang-Plain` 이 `sin` 을 `TJO` 로
    거짓말하지만, 생명과학Ⅰ은 같은 글꼴로 유전자 기호·숫자(`44` · `XX`)를 멀쩡히 적는다 — 이름으로는
    못 가른다. 수식 쪽 판정은 추출 라우터(I886)와 같은 잣대(구조체 글꼴 스팬 20% 초과)다.
    """
    rot = page.rotation_matrix
    rows = [(ln, [sp for sp in ln.get("spans", [])])
            for blk in page.get_text("dict").get("blocks", []) if blk.get("type") == 0
            for ln in blk.get("lines", [])]
    fonts = [sp.get("font") or "" for _, sps in rows for sp in sps]
    math_page = bool(fonts) and \
        sum(1 for f in fonts if _MATH_STRUCT_FONT_RE.match(f)) / len(fonts) > _MATH_PAGE_MIN_SHARE
    out = []
    for ln, sps in rows:
        text = "".join(sp.get("text") or "" for sp in sps
                       if not (math_page and _MATH_FONT_RE.match(re.sub(r"^[A-Z]{6}\+", "", sp.get("font") or ""))))
        # 깨진 글자만 뺀다(줄째 버리지 않는다). 언매는 ◇ 를 PUA(U+E280)로, 옛한글을 PUA 로, 글머리 구분을
        # 제어 문자(\x07)로 적어 한 줄에 두어 자만 섞여도 `_layer_untrustworthy` 가 줄째 버렸다 — 한글은 멀쩡하다.
        text = _BAD_CHAR_RE.sub("", text).strip()
        if text:
            out.append((fitz.Rect(ln["bbox"]) * rot, text))
    return out


def _inside(bb: list[int], box) -> bool:
    cx, cy = (bb[0] + bb[2]) / 2, (bb[1] + bb[3]) / 2
    return bool(box) and len(box) == 4 and \
        box[0] - _BOX_TOL <= cx <= box[2] + _BOX_TOL and box[1] - _BOX_TOL <= cy <= box[3] + _BOX_TOL


def _norm(r: fitz.Rect, page: fitz.Page) -> list[int]:
    w, h = page.rect.width or 1, page.rect.height or 1
    return [round(r.x0 / w * 1000), round(r.y0 / h * 1000), round(r.x1 / w * 1000), round(r.y1 / h * 1000)]


def _region(bb: list[int], items: list[dict]) -> str | None:
    return next((it.get("type") for it in items if _inside(bb, it.get("bbox"))), None)


def locate(boundary: dict, text: str) -> str | None:
    """채점기용 — 글(gold 해독문 등)이 이 쪽 경계 파일의 어디에 있나. 목록을 만든 잣대와 같다.

    "kept"    경계 요소 글에 있다 → 점역·배치 몫(추출은 했다)
    "unseen"  추출이 못 봤다
    "dropped" MinerU 는 봤는데 경계까지 못 왔다
    None      어디에도 없다 → gold 만의 것(점역자 주·테두리 등)이거나, 대조를 안 한 쪽이다
              (`boundary["meta"]["loss_checks"]` 로 가른다)
    """
    q = _plain(text)
    if not q:
        return None
    if _Pool(e.get("content") for e in boundary.get("elements", [])).has(q):
        return "kept"
    losses = boundary.get("extraction_losses") or []
    for cls in ("unseen", "dropped"):
        if _Pool(x.get("text") for x in losses if x.get("class") == cls).has(q):
            return cls
    return None


# ── 같은 틀 이웃 줄에 가린 손실(#1298) ──────────────────────────────────────────
# 위 대조는 층 줄마다 쪽 전체 글에서 6-gram 이 반 넘게 덮이면 '있다'로 친다. 같은 틀 이웃 줄이 남아 있으면 통째로 빠진 줄도
# 그 이웃 글로 덮여 목록에 안 올랐다(2027 언매 p0096 선택지 ② · 화작 p0176 '재학생 200명' · 생명과학 p0141 보기 ㄱ).
# 그래서 층 줄 하나가 글 한 자리만 차지하게 짝짓는다. 닮음 높은 줄부터(같으면 긴 줄 · 층 차례) 닮은 자리(_SIB_SIM 이상)를 잡고,
# **길이가 비슷한 줄끼리만** 자리를 다툰다. 짧은 이름표 줄('DNA 상대량')이 긴 문장 속 같은 문구 자리를 빼앗지 않게.
# 닮은 자리가 있는데 모두 이웃 줄이 먼저 차지했고, 아무 줄도 안 차지한 글에서도 반 넘게 안 덮이는 줄이 손실이다
# (분수 분자 · 분모 줄이 한 요소 안에서 차례만 바뀐 꼴은 남은 글에 있어 빠진다).
# 묵자(경계 요소)와 MinerU 원출력을 **따로** 짝짓는다. 합쳐 대면 같은 틀 글이 두 벌이라 빠진 줄이 남은 한 벌을 차지한다.
# 2027 dev · val 시제품 후보 7, 7 모두 진짜(V2 temp/n220/assign2.py).
_SIB_SIM = 0.8
_SIB_LEN = 0.7                  # 길이가 이 배 ~ 1/이 배 사이인 줄끼리만 다툰다
_SIB_MIN_HANGUL = 10
_LATEX_CMD_RE = re.compile(r"\\[a-zA-Z]+")
_HANGUL_SYL_RE = re.compile(r"[가-힣]")


def _sib_plain(s: str | None) -> str:
    return _plain(_LATEX_CMD_RE.sub("", s or ""))


def _sib_windows(q: str, k: str) -> list[tuple[float, int]]:
    """k 에서 q 와 같은 길이 자리 중 닮음 _SIB_SIM 이상 [(닮음, 시작)], 높은 차례. 머리 · 가운데 · 꼬리 4자로 자리를 찾는다."""
    n, starts = len(q), set()
    for off in {0, max(0, n // 2 - 2), max(0, n - 4)}:
        probe = q[off:off + 4]
        if len(probe) == 4:
            starts.update(m.start() - off for m in re.finditer(re.escape(probe), k))
    got = [(SequenceMatcher(None, q, k[s:s + n], autojunk=False).ratio(), s) for s in starts if 0 <= s <= len(k) - n]
    return sorted((x for x in got if x[0] >= _SIB_SIM), key=lambda x: (-x[0], x[1]))


def _sibling_match(lines: list[tuple], texts) -> tuple[set[int], set[int]]:
    """lines[(자리, 글)] 를 texts 와 짝짓는다 → (글에 있는 줄 번호, 같은 틀 이웃 줄에 자리를 빼앗긴 줄 번호)."""
    k = "\x00".join(q for q in map(_sib_plain, texts) if q)
    rows = []
    for i, (_r, t) in enumerate(lines):
        q = _sib_plain(t)
        w = _sib_windows(q, k) if len(q) >= _MIN_CHARS else []
        if w:
            rows.append((w[0][0], i, q, w))
    taken: list[tuple[int, int]] = []
    have: set[int] = set()
    pend: list[tuple[int, str]] = []
    for _best, i, q, w in sorted(rows, key=lambda x: (-x[0], -len(x[2]), x[1])):
        n = len(q)
        s = next((s for _r, s in w if not any(
            min(s + n, e) - max(s, b) > min(n, e - b) / 2 and _SIB_LEN <= (e - b) / n <= 1 / _SIB_LEN
            for b, e in taken)), None)
        if s is not None:
            taken.append((s, s + n))
            have.add(i)
        elif len(_HANGUL_SYL_RE.findall(q)) >= _SIB_MIN_HANGUL:
            pend.append((i, q))
    free = list(k)
    for b, e in taken:
        free[b:e] = "\x00" * (e - b)
    rest = _Pool("".join(free).split("\x00"))
    lost = set()
    for i, q in pend:
        (have if rest.has(q) else lost).add(i)
    return have, lost


def extraction_losses(elements: list[dict], page: fitz.Page,
                      raw_dir: Path | None) -> tuple[list[dict], list[str]]:
    """경계 요소(최종) · MinerU 원출력 · 텍스트 레이어를 대조해 (손실 목록, 대조한 것)을 돌려준다."""
    kept = _Pool(el.get("content") for el in elements)
    items: list[dict] = []
    checks: list[str] = []
    if raw_dir is not None and raw_dir.is_dir():
        try:
            items = _unfold_nested(json.loads(_find_content_list(raw_dir).read_text(encoding="utf-8")), raw_dir)
            checks.append("mineru")
        except (FileNotFoundError, OSError, ValueError):
            items = []
    # 쪽째로 빼는 것은 스캔본뿐이다(위의 글이 남의 OCR 이다). 그 밖은 줄마다 가른다(`_layer_lines`).
    layer_ok = not _is_scanned_page(page)
    if layer_ok:
        checks.append("text_layer")
    lines = _layer_lines(page) if layer_ok else []
    # 레이어 줄을 **그림 안 / 밖** 으로 한 번 나눈다. 그림 안 줄은 그 그림의 글(dropped · figure_text 로 잰다),
    # 밖의 줄은 unseen 으로 잰다. 한 줄이 두 갈래 어느 쪽에도 안 들어가는 틈이 없다.
    figs = [it for it in items if it.get("type") in _FIGURE_TYPES]
    fig_lines: dict[int, list[str]] = {}
    outside: list[tuple[fitz.Rect, str]] = []
    for r, t in lines:
        bb = _norm(r, page)
        host = next((f for f in figs if _inside(bb, f.get("bbox"))), None)
        if host is None:
            outside.append((r, t))
        else:
            fig_lines.setdefault(id(host), []).append(t)
    fig_text = {k: "\n".join(v) for k, v in fig_lines.items()}

    losses: list[dict] = []
    seen_texts = []
    for it in items:
        text = _item_text(it, fig_text)
        seen_texts.append(text)
        kind = it.get("type")
        # 항목 안에서도 줄마다 잰다 — 대부분 들어가고 일부만 빠진 항목(그림 안 글 · 표 각주 한 줄)도 잡힌다.
        parts = [(None, x.strip()) for x in re.split(r"\n|<[^<>]{0,80}>", text) if x.strip()]
        for run in _lost_runs(parts, [kept]):
            losses.append({
                "class": "dropped",
                "source": f"mineru:{it.get('_nested') or kind}",
                "reason": "figure_text" if kind in _FIGURE_TYPES else "not_carried",
                "text": "\n".join(t for _, t in run),
                "bbox": [round(v) for v in it["bbox"]] if it.get("bbox") else None,
            })

    # 그림 밖 레이어 줄을 **레이어 순서대로 한 줄로 이어** 잰다. PyMuPDF 는 정답 칸 `1. 가설` 같은 줄을
    # 블록 하나씩으로 쪼개 준다 — 블록마다 재면 짧은 줄이 또 혼자 남는다(생명과학 p10).
    seen = _Pool(seen_texts)
    runs = _lost_runs(outside, [kept, seen])
    for run in runs:
        r = fitz.Rect(run[0][0])
        for rr, _ in run[1:]:
            r |= rr
        bb = _norm(r, page)
        losses.append({"class": "unseen", "source": "textlayer", "region": _region(bb, items),
                       "text": "\n".join(t for _, t in run), "bbox": bb})
    # 같은 틀 이웃 줄에 가린 손실(#1298, 위 절). 위에서 이미 잃은 줄은 뺀다. MinerU 원출력에 있으면 dropped 다.
    gone = {id(p) for run in runs for p in run}
    rest = [p for p in outside if id(p) not in gone]
    _have, lost = _sibling_match(rest, [el.get("content") for el in elements]) if rest else (set(), set())
    if lost:
        mu_have = _sibling_match(rest, seen_texts)[0] if items else set()
        for i in sorted(lost):
            r, t = rest[i]
            bb = _norm(r, page)
            losses.append({"class": "dropped" if i in mu_have else "unseen", "source": "textlayer",
                           "reason": "sibling", "region": _region(bb, items), "text": t, "bbox": bb})
    return losses, checks
