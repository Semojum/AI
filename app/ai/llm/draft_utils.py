"""점역사주 복수 초안(3안) 공통 유틸.

분류·차이 축은 `code/prompts/stage4_complex.md` 'T4-2 공통 규약'이 단일 출처.
시각 opt(이미지·만화·차트의 텍스트형 초안)는 LLM이 [방식1]/[방식2]/[방식3]으로
서로 다른 3안을 출력하고, 여기서 파싱해 Draft 목록을 만든다.
"""

from __future__ import annotations

import re

from app.schemas.content import Draft

_METHOD_RE = re.compile(r"\[\s*방식\s*([1-3])\s*\]\s*(.*)")


def ensure_tn_prefix(text: str) -> str:
    t = (text or "").strip()
    if not t:
        return ""
    return t if t.startswith("[점역사주]") else f"[점역사주] {t}"


def parse_labeled_drafts(response: str, methods: list[tuple[str, str]]) -> list[Draft]:
    """LLM 응답의 [방식N] 라인 → Draft 목록.

    methods: 옵션 순서대로 [(render_mode, label), ...] (보통 3개).
    파싱된 방식만 Draft로 만든다(부족하면 가능한 만큼). text엔 [점역사주] 접두 보장.
    """
    found: dict[int, str] = {}
    for raw in response.splitlines():
        m = _METHOD_RE.search(raw.strip())
        if not m:
            continue
        n, text = int(m.group(1)), m.group(2).strip()
        if text and n not in found:
            found[n] = text

    drafts: list[Draft] = []
    for i, (render_mode, label) in enumerate(methods, start=1):
        if i in found:
            drafts.append(Draft(
                option=i, text=ensure_tn_prefix(found[i]),
                render_mode=render_mode, label=label,
            ))
    return drafts


def single_draft(text: str, render_mode: str = "narrative", label: str = "단일") -> list[Draft]:
    """단일 초안(파싱 실패·ZERO·FALLBACK 등)."""
    return [Draft(option=1, text=ensure_tn_prefix(text), render_mode=render_mode, label=label)]
