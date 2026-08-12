"""점역사주 복수 초안(3안) 공통 유틸.

분류·차이 축은 `code/prompts/stage4_complex.md` 'T4-2 공통 규약'이 단일 출처.
시각 opt(이미지·만화·차트의 텍스트형 초안)는 LLM이 [방식1]/[방식2]/[방식3]으로
서로 다른 3안을 출력하고, 여기서 파싱해 Draft 목록을 만든다.
"""

from __future__ import annotations

import os
import re

from app.schemas.content import Draft

# [방식N] / 방식N / 방식 N + 구분기호(] : . )) 변형 허용. 대괄호·콜론 없어도 인식.
_METHOD_RE = re.compile(r"\[?\s*방식\s*([1-3])\s*[\]:.)]*\s*(.*)")


# 점역사주/점역자주 라벨(대괄호·콜론 변형 포함) 접두 제거용.
_TN_LEGACY_RE = re.compile(r"^\s*\[?\s*점역[사자]주\s*\]?\s*[:：.]?\s*")

# 모델이 방식 이름을 본문 앞에 붙이는 경우 제거(예: "상황 중심: …", "대사 중심: …").
# 점자에 메타 라벨이 찍히지 않게 함. 콜론으로 끝나는 짧은 방식-라벨만 매칭.
_PERSPECTIVE_LABEL_RE = re.compile(r"^(상황|위치|요약|장면|대사|개조|구성)[^:：\n]{0,10}[:：]\s*")

# 시각 초안 포장 방식 — visual_drafts와 **같은 스위치**를 읽는다(tn 기본 / box A/B).
# tn(기본·종전) · box(전면 전환, A/B용) · auto(조건 분기 — 아래 _is_transcription)
_WRAP_STYLE = os.environ.get("VISUAL_WRAP_STYLE", "tn")

# 전사(원문 글 나열)로 보는 신호 — 줄머리에 항목 표지가 붙은 줄이 둘 이상.
# 카드 1: · ① · 1. · - · • 처럼 **평행하게 늘어선 항목**은 그림을 푼 서술이 아니라
# 원문에 이미 글로 있는 것이다. 서술은 이런 표지 없이 줄글로 이어진다.
_ITEM_HEAD_RE = re.compile(
    r"^\s*(?:[①-⑳㉠-㉻]|[0-9]{1,2}\s*[.):]|[가-힣]\s*[.)]|[-•·]\s|카드\s*\d|"
    r"[^\s:：]{1,12}\s*\d+\s*[:：])")
_MIN_ITEMS = 2


def _is_transcription(text: str) -> bool:
    """초안이 **원문 글 나열**인가(= 글상자 본문) 아니면 **그림 서술**인가(= 주표).

    줄 단위로 못 가르는 경우가 있어(LLM이 한 줄에 ' / '로 이어 붙인다) 그 구분자도 본다.
    """
    parts = [x for x in re.split(r"\n|\s/\s", text) if x.strip()]
    return sum(1 for x in parts if _ITEM_HEAD_RE.match(x)) >= _MIN_ITEMS


def ensure_tn_prefix(text: str) -> str:
    """점역자 주 텍스트를 인라인 태그 `<!주>…<!/주>`로 감싼다 (plan §3-5).

    구 `[점역사주]`·`점역사주:` 리터럴 접두나 이미 붙은 태그가 있으면 제거 후 재포장(중복 방지).
    점역 직전 텍스트의 이 태그를 translator가 점자 마커 `⠠⠄`(양끝)로 치환한다.
    """
    t = (text or "").strip()
    if not t:
        return ""
    t = t.replace("<!주>", "").replace("<!/주>", "").strip()  # 기존 태그 제거
    t = _TN_LEGACY_RE.sub("", t).strip()               # [점역사주]·점역사주: 등 라벨 제거
    t = _PERSPECTIVE_LABEL_RE.sub("", t).strip()       # 상황/위치/요약 등 방식 라벨 제거
    if not t:
        return ""
    if _WRAP_STYLE == "box" or (_WRAP_STYLE == "auto" and _is_transcription(t)):
        # 원장 C-02 축. gold는 **둘 다 쓴다** — 전면 전환은 답이 아니다(평가 실측 12쪽:
        # box 전면 전환 시 CER 62.8% → 62.2%, 우리 주표 0셀인데 gold 주표는 888셀 실재).
        # 갈리는 자리는 이렇다:
        #   · 원문에 **글로 이미 있는 것**(카드·보기·자료 나열) → gold는 글상자 본문
        #     (사회문화 p147: 우리가 주표로 감싼 300셀을 gold는 글상자에 넣었다)
        #   · **그림을 말로 푼 것**(그래프 추세·장치 묘사) → gold는 주표 (gold 888셀이 이쪽)
        # auto는 그 둘을 초안 **모양**으로 가른다 — 나열이면 전사, 줄글이면 서술.
        return f"<!상자><!/상자>\n{t}\n<!상자끝><!/상자끝>"
    return f"<!주>{t}<!/주>"


def parse_labeled_drafts(response: str, methods: list[tuple[str, str]]) -> list[Draft]:
    """LLM 응답의 [방식N] 라인 → Draft 목록.

    methods: 옵션 순서대로 [(render_mode, label), ...] (보통 3개).
    파싱된 방식만 Draft로 만든다(부족하면 가능한 만큼). text는 `<!주>…<!/주>` 포장.
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
