"""추출 손실 목록(T35) — 이 쪽에서 추출이 못 본 글과, MinerU 는 봤는데 경계까지 못 온 글.

경계 파일의 `extraction_losses` 로 나간다. 채점기가 미커버 gold 를 갈래로 나눌 때 읽는다
(T33 에서 손으로 가른 층 대조를 파이프라인이 스스로 단다). 면제받으려고 다는 것이 아니라
**어디를 고칠지** 정하려고 다는 것이다.

  class   "unseen"  텍스트 레이어엔 있는데 MinerU 글에도 경계 요소 글에도 없다(T33 D).
          "dropped" MinerU 항목 글인데 경계 요소 글에 없다(T33 C).
  source  "textlayer" | "mineru:<content_list type>" | "mineru:<펼친 필드>"(table_footnote·code_body …)
  reason  dropped 만. "figure_text"(그림·그래프 안 글, 캡셔닝 몫으로 둔다) | "not_carried"(그 밖)
  region  unseen 만. 그 글 자리에 걸친 MinerU 항목 type(없으면 None). 영역을 잘못 본 것인지
          영역조차 없는 것인지 가른다(T33 "D 의 MinerU 자리").
  text    그 글(묵자). 채점기가 gold 해독문과 음절 n-gram 으로 맞춘다.
  bbox    0~1000 정규화 [x0, y0, x1, y1] (회전 뒤 지면 좌표).

대조는 T33 층 대조와 같다. 공백·기호를 뺀 글자열에서 음절 6-gram 이 덮는 몫이 50% 이상이면
"있다" 로 본다. 6자보다 짧은 글은 부분 문자열로 본다.

★ 목록이 비었다고 손실이 없는 것이 아니다. 무엇을 대조했는지는 함께 돌려주는 `checks` 에 있다
  ("mineru" = MinerU 원출력과 대조함, "text_layer" = 텍스트 레이어와 대조함). 스캔본·수식 PUA 쪽처럼
  레이어를 못 믿으면 "text_layer" 가 빠지고 unseen 은 아예 안 잰다.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import fitz

from app.ai.parser.mineru_runner import (
    _MATH_FONT_RE,
    _find_content_list,
    _layer_untrustworthy,
    _native_text_spaced,
    _squash_text,
    _unfold_nested,
)

_TAG_RE = re.compile(r"<[^<>]{0,80}>")    # 경계 태그(<!상자>…)·표 HTML(<td>…) — 이름 글자가 대조를 흐린다
_N = 6                                    # 음절 n-gram 길이(T33 층 대조와 같다)
_COVER = 0.5                              # 이 몫 이상 덮이면 "있다"
_MIN_CHARS = 6                            # 이보다 짧은 손실 글은 적지 않는다(①·㉠ 같은 조각은 대조가 안 된다)
_FIGURE_TYPES = frozenset({"image", "chart"})
_BOX_TOL = 3                              # region 판정 여유(0~1000)


def _plain(s: str | None) -> str:
    return _squash_text(_TAG_RE.sub(" ", s or ""))


class _Pool:
    """대조 대상 글 묶음. 조각 사이에 구분자를 넣어 경계를 넘는 n-gram 이 안 생기게 한다."""

    def __init__(self, texts):
        self.s = "\x00".join(q for q in map(_plain, texts) if q)
        self.grams = {self.s[i:i + _N] for i in range(len(self.s) - _N + 1)}

    def has(self, q: str) -> bool:
        if len(q) < _N:
            return q in self.s
        hit = bytearray(len(q))
        for i in range(len(q) - _N + 1):
            if q[i:i + _N] in self.grams:
                hit[i:i + _N] = b"\x01" * _N
        return sum(hit) >= _COVER * len(q)


def _item_text(it: dict, page: fitz.Page, layer_ok: bool) -> str:
    kind = it.get("type")
    if kind in _FIGURE_TYPES:
        # 그림 안 글은 MinerU 가 안 적는 일이 많다(카드 뉴스·지도). 레이어를 믿으면 레이어 글을 쓴다.
        if layer_ok and it.get("bbox"):
            return _native_text_spaced(page, it["bbox"]) or it.get("content") or ""
        return it.get("content") or ""
    if kind == "table":
        return it.get("table_body") or ""
    if kind == "list":
        return "\n".join(it.get("list_items") or [])
    return it.get("text") or ""


def _norm(r: fitz.Rect, page: fitz.Page) -> list[int]:
    w, h = page.rect.width or 1, page.rect.height or 1
    return [round(r.x0 / w * 1000), round(r.y0 / h * 1000), round(r.x1 / w * 1000), round(r.y1 / h * 1000)]


def _region(bb: list[int], items: list[dict]) -> str | None:
    cx, cy = (bb[0] + bb[2]) / 2, (bb[1] + bb[3]) / 2
    for it in items:
        b = it.get("bbox")
        if b and len(b) == 4 and b[0] - _BOX_TOL <= cx <= b[2] + _BOX_TOL and b[1] - _BOX_TOL <= cy <= b[3] + _BOX_TOL:
            return it.get("type")
    return None


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
    layer_ok = not _layer_untrustworthy(page.get_text("text"), page)
    if layer_ok:
        checks.append("text_layer")

    losses: list[dict] = []
    seen_texts = []
    for it in items:
        text = _item_text(it, page, layer_ok)
        seen_texts.append(text)
        q = _plain(text)
        if len(q) < _MIN_CHARS or kept.has(q):
            continue
        kind = it.get("type")
        losses.append({
            "class": "dropped",
            "source": f"mineru:{it.get('_nested') or kind}",
            "reason": "figure_text" if kind in _FIGURE_TYPES else "not_carried",
            "text": text.strip(),
            "bbox": [round(v) for v in it["bbox"]] if it.get("bbox") else None,
        })

    if layer_ok:
        seen = _Pool(seen_texts)
        rot = page.rotation_matrix
        for blk in page.get_text("dict").get("blocks", []):
            if blk.get("type") != 0:
                continue
            run: list[tuple[fitz.Rect, str]] = []
            for ln in [*blk.get("lines", []), None]:          # None = 블록 끝에서 모은 줄을 털어 낸다
                lost = None
                if ln is not None:
                    # 한컴 수식 글꼴은 레이어가 평범한 ASCII 로 거짓말을 한다(`_has_math_font` 주석) — 뺀다
                    text = "".join(sp.get("text") or "" for sp in ln.get("spans", [])
                                   if not _MATH_FONT_RE.match(sp.get("font") or ""))
                    q = _plain(text)
                    if q and not _layer_untrustworthy(text) and not seen.has(q) and not kept.has(q):
                        lost = (fitz.Rect(ln["bbox"]) * rot, text.strip())
                if lost:
                    run.append(lost)
                    continue
                if run and len(_plain("".join(t for _, t in run))) >= _MIN_CHARS:
                    r = fitz.Rect(run[0][0])
                    for rr, _ in run[1:]:
                        r |= rr
                    bb = _norm(r, page)
                    losses.append({"class": "unseen", "source": "textlayer", "region": _region(bb, items),
                                   "text": "\n".join(t for _, t in run), "bbox": bb})
                run = []
    return losses, checks
