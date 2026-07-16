"""시각자료 대체텍스트 4안 생성 (이미지·만화·차트·도표 공통).

점역사가 고를 4가지 대체텍스트(QA 2026-07-05 요건). 각 안은 그 자체로 완결된 대체텍스트다:
  0) 생략     : 점자 규정(§6.3.4(2)②)에 맞춘 생략 표기 — 결정적, LLM 미사용.
  1) 짧은 제목: 인쇄 캡션이 있으면 그대로, 없으면 LLM이 짧은 제목 생성.
  2) 개조식   : 위계 있는 개조식 + 짧은 설명 — 구조가 있으면 rule-based 전사, 없으면 LLM.
  3) 줄글     : 자세한 줄글 설명 — 구조가 있으면 rule-based, 없으면 LLM.

성능·안정성: 0·1안은 무-LLM(또는 캡션 전사)이라 **항상** 나온다. 2·3안 중 LLM이 필요한
부분만 **1회 호출**로 함께 생성한다(방식별 N회 호출 → 1회로 축소, 페이지 타임아웃 완화).
LLM 파싱이 실패해도 캡션 폴백으로 4안이 보장된다(구 3안 포맷 미준수 문제 해소).

기본 선택(selected_idx): 장식용이면 0(생략), 그 외엔 2(개조식)를 기본 초안으로 둔다.
"""

from __future__ import annotations

import os
import re
import time

from app.ai.llm.base_opt import decide_tier_timeout, generate_with_retry
from app.core.config import config
from app.schemas.content import Draft
from app.utils.logger import get_logger

logger = get_logger(__name__)

# 시각자료 감싸기 스타일 A/B (2026-07-13 설계 재검토용 스위치, 기본=현행):
#   tn  = 점역자주 ⠠⠄ 감싸기(현행 설계, 지침 §6.3.4(1))
#   box = 글상자 테두리 ⠿⠛…/⠿⠶… 감싸기(실험용).
# ⚠ box 근거였던 "정답 BRL ⠿ 95%"는 오독 — 정답의 ⠿(17,981회)는 전부 한글 약자 '옹'(동·통·종 등)이고
#   테두리형 줄(⠿+단일 채움 반복)은 정답 1131p 전체에서 0줄. A/B에서도 box는 악화(cell_ns 0.709→0.682).
#   → 기본 tn 유지. 스위치는 후속 실험 대비용으로만 남김.
_WRAP_STYLE = os.environ.get("VISUAL_WRAP_STYLE", "tn")

# 4안 라벨(FE 피커 표시) — 순서 = option 1..4
LABELS = ("생략", "짧은 제목", "개조식 설명", "줄글 설명")
OMIT_IDX, TITLE_IDX, OUTLINE_IDX, PROSE_IDX = 0, 1, 2, 3

# 개조식 들여쓰기(칸): 제목 5칸(§6.3.3(1)), 유형/설명 점역자주 0칸, 전사 항목 level0=3칸(+2/단계).
_TITLE_INDENT = 5
_OUTLINE_BASE = 3
_OUTLINE_STEP = 2

# 최적화 프롬프트 — GPT-4o가 만든 캡션(묘사)을 HCXT가 점자 초안용으로 '다듬는다'(재생성 금지).
# 짧은 제목은 캡션 첫 문장(rule-based)이라 LLM은 개조식·줄글 두 형식만 담당 → 토큰↓·속도↑.
_PROMPT = """당신은 시각장애 학생용 점자 교과서 점역 전문가입니다.
아래 '설명'은 한 시각자료({label})에 대한 묘사입니다. 이 설명을 점자 초안용으로 **다듬어**
두 형식으로만 출력하세요. 설명에 없는 정보·수치·추측을 새로 만들지 말고, 주어진 내용만 간결히
재구성합니다. "그림은/이미지는"으로 시작하지 마세요. 아래 태그를 각각 한 번씩만 출력합니다.

[개조식] 핵심을 위계 있는 개조식으로. 큰 항목은 줄 맨 앞, 하위 항목은 앞에 "- ". 3~5줄.
[줄글] 1~3문장으로 간결히.

설명: {caption}"""

_PREFILL = "[개조식]\n"

_SECTION_RE = re.compile(r"\[(제목|개조식|줄글)\]\s*(.*)")


def _tn(text: str) -> str:
    """시각자료 감싸기 — tn(현행): 점역자주 / box(A/B): 글상자 테두리."""
    if _WRAP_STYLE == "box":
        return (f"<!테두리_위><!/테두리_위>\n{text}\n<!테두리_아래><!/테두리_아래>")
    return f"<!점역자주>{text}<!/점역자주>"


def _shorten(text: str, limit: int = 45) -> str:
    """긴 캡션(MinerU 캡셔너의 장문 설명)을 '짧은 제목'용으로 줄인다.

    짧은 인쇄 캡션은 그대로(요건 "캡션 있으면 그대로"), 장문 AI 설명만 첫 문장/limit자로 축약.
    """
    t = " ".join((text or "").split())
    if len(t) <= limit:
        return t
    m = re.search(r"[.。!?]\s|[.。!?]$", t)          # 첫 문장 경계
    if m and m.start() + 1 <= int(limit * 1.6):
        return t[: m.start() + 1]
    return t[:limit].rsplit(" ", 1)[0] + "…"


def _outline_text_indents(
    label: str, title: str, desc: str, items: list[tuple[int, str]]
) -> tuple[str, list[int]]:
    """개조식 → (텍스트, 줄별 들여쓰기). §6.3 규정 배치:
      제목(5칸, 점역자주 밖·§6.3.3(1)) → 유형+짧은 설명(점역자주·§6.3.4(1)) → 전사 항목(위계 들여).
    """
    lines: list[str] = []
    indents: list[int] = []
    title = (title or "").strip()
    desc = (desc or "").strip()
    head = f"{label}: {desc}" if (desc and desc != title) else label
    if _WRAP_STYLE == "box":
        # box(A/B): 블록 전체를 글상자로 — 제목은 위 테두리 안(BBPG-1.2.5), 유형/설명은 첫 줄.
        lines.append(f"<!테두리_위>{title}<!/테두리_위>"); indents.append(0)
        lines.append(head); indents.append(0)
    else:
        if title:
            lines.append(title); indents.append(_TITLE_INDENT)      # §6.3.3(1) 제목 5칸(plain)
        lines.append(_tn(head)); indents.append(0)                   # §6.3.4(1) 유형/설명 점역자주
    for level, text in items:
        text = (text or "").strip()
        if not text:
            continue
        lines.append(text); indents.append(_OUTLINE_BASE + _OUTLINE_STEP * max(0, level))  # 전사 §6.3.4(2)①
    if _WRAP_STYLE == "box":
        lines.append("<!테두리_아래><!/테두리_아래>"); indents.append(0)
    return "\n".join(lines), indents


def omission_draft(label: str) -> Draft:
    """0안: 생략 표기(§6.3.4(2)②). 장식용·중요도 낮은 자료용."""
    return Draft(option=1, text=_tn(f"{label} 생략"), render_mode="narrative", label=LABELS[OMIT_IDX])


def title_draft(label: str, title: str) -> Draft:
    """1안: 짧은 제목(캡션 그대로 또는 생성)."""
    body = f"{label}: {title}".strip().rstrip(":") if title else f"{label} 생략"
    return Draft(option=2, text=_tn(body), render_mode="narrative", label=LABELS[TITLE_IDX])


def outline_draft(
    label: str, title: str, desc: str, items: list[tuple[int, str]]
) -> tuple[Draft, list[int]]:
    """2안: 위계 개조식(제목 5칸 + 유형/설명 점역자주 + 전사 항목). 반환 (Draft, line_indents)."""
    text, indents = _outline_text_indents(label, title, desc, items)
    return Draft(option=3, text=text, render_mode="narrative", label=LABELS[OUTLINE_IDX]), indents


def prose_draft(label: str, prose: str) -> Draft:
    """3안: 줄글 자세한 설명."""
    body = (prose or "").strip()
    return Draft(option=4, text=_tn(f"{label}: {body}" if body else f"{label} 생략"),
                 render_mode="narrative", label=LABELS[PROSE_IDX])


def _parse_sections(response: str) -> dict[str, object]:
    """LLM 응답 → {제목:str, 개조식:list[(level,text)], 줄글:str}."""
    title = ""
    outline: list[tuple[int, str]] = []
    prose_lines: list[str] = []
    cur = None
    for raw in (response or "").splitlines():
        line = raw.rstrip()
        m = _SECTION_RE.match(line.strip())
        if m:
            cur = m.group(1)
            rest = m.group(2).strip()
            if cur == "제목" and rest:
                title = rest
            elif cur == "개조식" and rest:
                outline.append(_outline_item(rest))
            elif cur == "줄글" and rest:
                prose_lines.append(rest)
            continue
        if not line.strip():
            continue
        if cur == "개조식":
            outline.append(_outline_item(line))
        elif cur == "줄글":
            prose_lines.append(line.strip())
        elif cur == "제목" and not title:
            title = line.strip()
    return {"제목": title, "개조식": outline, "줄글": " ".join(prose_lines).strip()}


def _outline_item(line: str) -> tuple[int, str]:
    """개조식 한 줄 → (level, text). 선행 공백/'- '로 위계 판정."""
    indent = len(line) - len(line.lstrip(" \t"))
    body = line.strip()
    level = 0
    if body.startswith(("- ", "* ", "· ")):
        body = body[2:].strip()
        level = 1
    elif indent >= 2:
        level = 1
    return level, body


async def build_visual_drafts(
    ext,
    routing_tier: str,
    *,
    label: str,
    caption: str,
    title: str = "",
    kind: str,
    struct_outline: list[tuple[int, str]] | None = None,
    struct_prose: str | None = None,
    decorative: bool = False,
) -> tuple[list[Draft], int, list[int] | None, str]:
    """4안(생략·제목·개조식·줄글) 생성. 반환 (drafts, selected_idx, line_indents, tier).

    title = 자료 제목(짧은 제목 초안·개조식 머리줄). caption = 인쇄 캡션/설명(개조식 항목·줄글).
    struct_outline/struct_prose가 오면 그 파트는 rule-based 전사(LLM 미사용). 나머지(제목·개조식·
    줄글 중 빠진 것)만 비ZERO에서 LLM 1회로 채운다.
    """
    caption = (caption or "").strip()
    title = (title or "").strip()
    tier = routing_tier
    _t0 = time.monotonic()   # 시각요소별 4안 생성 소요시간(줄글 LLM 포함) 로깅용

    # LLM이 채워야 할 파트: 제목·캡션 다 없으면 제목, 구조 없으면 개조식/줄글.
    need_title = not (title or caption)
    need_outline = struct_outline is None
    need_prose = struct_prose is None
    has_seed = bool(title or caption)
    use_llm = (routing_tier != "ZERO") and has_seed and (need_title or need_outline or need_prose)

    llm_title, llm_outline, llm_prose = "", [], ""
    if use_llm:
        # 시각 최적화는 캡션 재구성(무거운 생성) → QUALITY 상한을 쓴다(요소당 상한이지만 페이지
        # 누적 예산이 총량을 막으므로 안전). 티어 라벨은 신뢰도 기준(decide_tier_timeout).
        t2, _ = decide_tier_timeout(ext.ocr_confidence)
        timeout = config.hcxt_quality_timeout_seconds
        # 출력은 [개조식]+[줄글] 두 섹션을 한 번에 담는다 → 캡션의 0.9배(구 180 상한)로는
        # 위계 개조식이 예산을 먹고 줄글이 문장 중간에 잘렸다(A/B에서 확인). 두 섹션 합계를
        # 고려해 캡션의 ~1.6배로 잡고 상한을 320으로 올린다(vLLM 46tok/s면 ~7s, QUALITY 상한 내).
        src = caption or title
        mnt = min(320, max(140, int(len(src) * 1.6)))
        response, used_fb = await generate_with_retry(
            _PROMPT.format(label=label, caption=src),
            timeout=timeout, element_id=ext.element_id, kind=kind,
            prefill=_PREFILL, max_new_tokens=mnt, fallback_max_tokens=mnt,
        )
        tier = "FALLBACK" if used_fb else t2
        sec = _parse_sections(response)
        llm_title, llm_outline, llm_prose = sec["제목"], sec["개조식"], sec["줄글"]

    # 짧은 제목: 인쇄 캡션 우선(요건 — "캡션 있으면 그대로"), 단 장문 AI 캡션은 짧게 축약. 없으면 제목/LLM.
    short_title = _shorten(caption) or title or llm_title or ""
    # 개조식: 5칸 제목줄 = 구조적 표제(title), 점역자주 설명 = 캡션/생성 설명.
    outline_desc = caption or llm_title or ""
    outline_items = struct_outline if struct_outline is not None else llm_outline
    prose = struct_prose if struct_prose is not None else (llm_prose or caption or title)

    d_omit = omission_draft(label)
    d_title = title_draft(label, short_title)
    d_outline, indents = outline_draft(label, title, outline_desc, outline_items)
    d_prose = prose_draft(label, prose)
    drafts = [d_omit, d_title, d_outline, d_prose]

    selected_idx = OMIT_IDX if decorative else OUTLINE_IDX
    line_indents = indents if selected_idx == OUTLINE_IDX else None
    logger.info("    4안 %s %s: %.1fs (tier=%s%s)", kind, str(ext.element_id)[:8],
                time.monotonic() - _t0, tier, ", LLM" if use_llm else "")
    return drafts, selected_idx, line_indents, tier
