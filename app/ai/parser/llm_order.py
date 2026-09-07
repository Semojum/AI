"""읽기순서 LLM 보정 — 규칙이 낸 순서를 claude-opus-5 에게 한 번 더 물어본다.

원장 C-106. 판정 라운드 2026-09-07(표본 97쪽, 커밋 327682c 고정) 근거.

★ 무엇을 사는가 (실측 · 정방향 CER)
    층        쪽    ① 규칙   ② LLM    ②−①
    어긋남    40   58.19%  46.85%  **-11.33%p**
    정상      57   33.00%  34.45%  **+1.45%p**
    전체      97   43.39%  39.57%  **-3.82%p** (마이크로 -4.10%p)
  권당 3,593원(코퍼스 평균 권 245쪽 · 실측 쪽당 2,557토큰 = 21.5원). 대표 결재 2026-09-07.

★ 왜 회전 지면은 빼는가
  회전 쪽(page_rotation 90/270)은 좌표가 누워 있어 규칙이 이미 잘 푼다. 표본 16쪽에서
  LLM 이 τ 0.881 → 0.886 으로 사실상 무차인데 돈만 든다. 라우팅을 비회전으로 좁히면
  걸리는 쪽이 68.3% 로 줄고 이득은 오히려 조금 낫다(-2.64 → -2.66%p, 권당 5,261 → 3,593원).

★ 안전판(_GUARD_RATIO)은 **CER 이득 장치가 아니라 분산 축소 장치다.**
  전체 CER 은 -3.82 → -3.86%p 로 사실상 무차다. 정상 층 손해를 +1.45 → +0.17%p 로
  지우는 대신 어긋남 층 이득도 -11.33 → -9.60%p 로 버린다. 값을 사는 게 아니라
  **한 쪽이 통째로 터지는 일**을 막으려고 둔다(표본에서 CER 57%→131% 로 터진 쪽이 있었다).
  ⚠ 임계 0.7 은 **같은 표본에서 고른 값이고 독립 표본 검증을 안 했다.**

★ LLM 이 죽으면 규칙 순서 그대로 간다. 순열이 아니어도, 예외가 나도, 키가 없어도 마찬가지다.
"""
from __future__ import annotations

import asyncio
import json
import os
import time

from app.core.config import config
from app.utils.logger import get_logger

logger = get_logger(__name__)

MODEL = "claude-opus-5"
SNIPPET = 120                 # 요소당 넣는 본문 길이. 실측: 이걸 0 으로 줄이면 값이 28% 싸지는
                              # 대신 순이득의 70% 가 사라진다(정상 층 손해 +2.04 → +5.98%p).
_GUARD_RATIO = 0.7            # 본문류 요소의 2칸 이상 이동 비율이 이 이상이면 규칙으로 되돌린다
_BODY_TYPES = {"text", "title", "list_item", "caption", "footnote"}
_MAX_TOKENS = 16000           # 사고가 상한을 먹어 빈 응답이 오는 것을 막는다

_SYS = (
    "당신은 교과서·문제집 지면의 읽기 순서를 판정하는 도우미다.\n"
    "입력은 한 쪽에서 추출된 요소 목록이다. 각 요소는 번호, 좌표 bbox=(x0,y0,x1,y1), 종류, "
    "본문 앞부분(최대 120자)을 가진다.\n"
    "좌표는 추출기 원좌표이며 페이지가 회전돼 있을 수 있다(그 경우 읽기 방향이 x축일 수 있다). "
    "제시된 순서는 추출기가 내놓은 순서일 뿐 정답이 아니다.\n"
    "사람이 이 쪽을 소리 내어 읽는다면 어떤 순서가 되는지 판단해, 모든 요소 번호를 한 번씩만 "
    "쓴 순열을 order로 돌려준다. 설명은 쓰지 않는다."
)
_SCHEMA = {
    "type": "object",
    "properties": {"order": {"type": "array", "items": {"type": "integer"}}},
    "required": ["order"],
    "additionalProperties": False,
}


def enabled() -> bool:
    """켜는 스위치는 `READING_ORDER_LLM=1`. **기본은 꺼짐이다.** 키가 없어도 꺼진다.

    ★ 2026-09-08 대표 결정으로 기본값을 켬에서 **끔**으로 바꿨다.
      "이득에 비해 시간 낭비가 너무 크다."
      실측: 쪽당 3.0~3.4초가 더 든다. 실제 문서에서 30초짜리가 45초가 됐다.
      이득은 97쪽 표본에서 정방향 CER -3.82%p(어긋난 층 -11.33 · 정상 층 +1.45)였다.
      점역사가 순서를 고치는 수고보다 매 문서 1.5배 기다리는 수고가 크다는 판단이다.
    ⚠ 되살릴 때는 속도부터 재라. 켜고 끈 두 팔의 **벽시계**를 문서 단위로 대야 한다.
      원장 C-106 에 배선 근거가 있다.
    """
    return (os.environ.get("READING_ORDER_LLM", "0") == "1"
            and bool(config.anthropic_api_key))


def _prompt(items, texts: dict) -> str:
    lines = [f"요소 {len(items)}개", ""]
    for i, b in enumerate(items):
        t = " ".join((texts.get(b.element_id) or "").split())[:SNIPPET]
        x0, y0, x1, y1 = b.bbox
        lines.append(f"[{i}] bbox=({x0},{y0},{x1},{y1}) {b.type} :: {t}")
    return "\n".join(lines)


def _ask(prompt: str):
    """(order, 입력토큰, 출력토큰). 캐시에 있으면 부르지 않는다(토큰 0).

    ★ 캐시 키는 **프롬프트 문자열 해시**다(재구조화 3-b). 요소 목록을 직렬화하면
      `element_id`(uuid4)가 섞여 다른 job 은 항상 미스가 된다. `_prompt` 가 넣는 것은
      index·bbox·type·본문 120자뿐이라 같은 쪽이면 같은 문자열이 나온다.
    ★ 원응답 raw 만 담는다 — 순열 검사·안전판은 `apply` 가 적중분에도 그대로 건다.
    """
    import anthropic

    from app.utils import llm_cache
    from app.utils.req_log import record_anthropic

    k = llm_cache.key("order", MODEL, _SYS, prompt)
    cached = llm_cache.get("order", k)
    if cached is not None:
        return json.loads(cached)["order"], 0, 0

    client = anthropic.Anthropic(api_key=config.anthropic_api_key or None)
    resp = client.messages.create(
        model=MODEL, max_tokens=_MAX_TOKENS,
        thinking={"type": "adaptive"},
        output_config={"effort": "medium",
                       "format": {"type": "json_schema", "schema": _SCHEMA}},
        system=_SYS, messages=[{"role": "user", "content": prompt}],
    )
    # 쪽당 토큰·원가는 여기서만 남는다. 나중에 단가를 다시 재려면 이 줄이 있어야 한다.
    record_anthropic("reading_order", MODEL, getattr(resp, "usage", None))
    txt = next((b.text for b in resp.content if b.type == "text"), "")
    u = getattr(resp, "usage", None)
    order = json.loads(txt)["order"]        # 파싱된 뒤에만 담는다 — 깨진 응답을 굳히지 않는다
    llm_cache.put("order", k, txt)
    return order, getattr(u, "input_tokens", 0), getattr(u, "output_tokens", 0)


def displaced_ratio(items, order: list[int]) -> float:
    """본문류 요소 중 규칙 자리에서 2칸 이상 옮겨진 비율. 안전판 판정값."""
    body = [i for i, b in enumerate(items) if b.type in _BODY_TYPES]
    if not body:
        return 0.0
    pos = {e: r for r, e in enumerate(order)}
    return sum(1 for i in body if abs(pos[i] - i) >= 2) / len(body)


async def apply(layout, ext_map, rotation: int) -> dict:
    """layout.elements 의 reading_order 를 LLM 판정으로 바꾼다(제자리). 실패하면 그대로 둔다.

    반환은 관측값이다 — 걸렸는지·되돌렸는지·얼마 썼는지.
    """
    out = {"called": False, "applied": False, "reverted": False, "ratio": 0.0,
           "in": 0, "out": 0, "reason": ""}
    items = sorted(layout.elements, key=lambda b: b.reading_order)
    if not enabled():
        out["reason"] = "꺼짐"
    elif rotation:
        # 회전 지면은 규칙이 이미 잘 푼다(위 도크스트링). 돈만 드는 자리라 아예 안 부른다.
        out["reason"] = f"회전 {rotation}°"
    elif len(items) < 4:
        out["reason"] = "요소 4개 미만"
    if out["reason"]:
        logger.info("읽기순서 LLM 건너뜀 (%s)", out["reason"])
        return out

    texts = {eid: (c.corrected_text or "") for eid, c in (ext_map or {}).items()}
    t0 = time.time()
    try:
        order, tin, tout = await asyncio.to_thread(_ask, _prompt(items, texts))
    except Exception as exc:                                       # noqa: BLE001
        # 호출이 죽어도 쪽이 어긋나면 안 된다 — 규칙 순서를 그대로 쓴다.
        logger.warning("읽기순서 LLM 실패 → 규칙 순서 유지: %s", exc)
        out["reason"] = f"실패 {type(exc).__name__}"
        return out
    out.update(called=True, **{"in": tin, "out": tout})

    if sorted(order) != list(range(len(items))):
        logger.warning("읽기순서 LLM 응답이 순열이 아니다 → 규칙 순서 유지 (요소 %d)", len(items))
        out["reason"] = "순열 아님"
        return out

    ratio = displaced_ratio(items, order)
    out["ratio"] = round(ratio, 3)
    if ratio >= _GUARD_RATIO:
        # 안전판. 이득 장치가 아니라 분산 축소 장치다(도크스트링 참조).
        logger.info("읽기순서 LLM 되돌림 (본문 이동비율 %.2f ≥ %.2f)", ratio, _GUARD_RATIO)
        out["reverted"] = True
        out["reason"] = "안전판"
        return out

    for rank, i in enumerate(order, start=1):
        items[i].reading_order = rank
    out["applied"] = True
    logger.info("읽기순서 LLM 적용 (요소 %d · 이동비율 %.2f · %d/%d토큰 · %.1fs)",
                len(items), ratio, tin, tout, time.time() - t0)
    return out


def _demo() -> None:
    """안전판 계산만 자체 점검한다(API 호출 없음)."""
    class B:
        def __init__(self, t):
            self.type = t
    items = [B("text")] * 5
    assert displaced_ratio(items, [0, 1, 2, 3, 4]) == 0.0
    assert displaced_ratio(items, [4, 3, 2, 1, 0]) == 0.8      # 가운데 하나만 제자리
    assert displaced_ratio([B("image")] * 3, [2, 1, 0]) == 0.0  # 본문류가 없으면 0
    print("ok")


if __name__ == "__main__":
    _demo()
