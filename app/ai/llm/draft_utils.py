"""점역사주 복수 초안(3안) 공통 유틸.

분류·차이 축은 `code/prompts/stage4_complex.md` 'T4-2 공통 규약'이 단일 출처.
시각 opt(이미지·만화·차트의 텍스트형 초안)는 LLM이 [방식1]/[방식2]/[방식3]으로
서로 다른 3안을 출력하고, 여기서 파싱해 Draft 목록을 만든다.
"""

from __future__ import annotations

import re

from app.schemas.content import Draft

# [방식N] / 방식N / 방식 N + 구분기호(] : . )) 변형 허용. 대괄호·콜론 없어도 인식.
_METHOD_RE = re.compile(r"\[?\s*방식\s*([1-3])\s*[\]:.)]*\s*(.*)")


# 점역사주/점역자주 라벨(대괄호·콜론 변형 포함) 접두 제거용.
_TN_LEGACY_RE = re.compile(r"^\s*\[?\s*점역[사자]주\s*\]?\s*[:：.]?\s*")


def ensure_tn_prefix(text: str) -> str:
    """점역자 주 텍스트를 인라인 태그 `<!점역자주>…<!/점역자주>`로 감싼다 (plan §3-5).

    구 `[점역사주]`·`점역사주:` 리터럴 접두나 이미 붙은 태그가 있으면 제거 후 재포장(중복 방지).
    점역 직전 텍스트의 이 태그를 translator가 점자 마커 `⠠⠄`(양끝)로 치환한다.
    """
    t = (text or "").strip()
    if not t:
        return ""
    t = t.replace("<!점역자주>", "").replace("<!/점역자주>", "").strip()  # 기존 태그 제거
    t = _TN_LEGACY_RE.sub("", t).strip()               # [점역사주]·점역사주: 등 라벨 제거
    if not t:
        return ""
    return f"<!점역자주>{t}<!/점역자주>"


def parse_labeled_drafts(response: str, methods: list[tuple[str, str]]) -> list[Draft]:
    """LLM 응답의 [방식N] 라인 → Draft 목록.

    methods: 옵션 순서대로 [(render_mode, label), ...] (보통 3개).
    파싱된 방식만 Draft로 만든다(부족하면 가능한 만큼). text는 `<!점역자주>…<!/점역자주>` 포장.
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
