"""읽기순서 LLM 보정 — 규칙이 낸 순서를 claude-opus-5 에게 한 번 더 물어본다.

원장 C-106. 판정 라운드 2026-09-07(표본 97쪽, 커밋 327682c 고정) 근거.

★ 무엇을 사는가 (실측 · 정방향 CER · 마이크로=gold 셀 가중)
  r39 2026-09-12, **새 경계(temp/par/d3, 현행 develop 추출)** 위 비회전·비수학 2단+사이드바
  부류 318쪽(유효 317), 두 팔 같은 커밋 d3e6d49. 아래 관행 문안을 넣기 전(옛)/후(현행):
    팔  안전판   어긋남 182    정상 135     전체 317   dev 60   val 257   정상층 악화쪽
    옛   raw     -8.01       **+4.77**    -2.03     -3.18    -1.75        32
    옛   0.7     -7.06         +1.29      -3.15     -3.37    -3.10        27
    현행 **raw** **-5.84**   **-0.34**  **-3.27**  **-2.30** **-3.49**    **18**
    현행 0.7     -4.32         -0.31      -2.44     -2.08    -2.53        18
  정상 층 악화 18쪽 중 15쪽이 +0.1%p 이하(중앙 +0.08%p), 1%p 넘는 악화는 3쪽·최대 +2.8%p.
  옛 문안은 최악 +123%p 로 터진 쪽이 3쪽 있다. 실측 쪽당 2,636/197토큰 = 24.9원,
  부류만 걸면 권당 1,715원(245쪽 권 · d3 실측 호출 비율 28.1%), 호출당 중앙 4.4초.
  ※ r38 이 07-19 경계(d2)에서 잰 값(전체 -1.97 · 정상 -0.16 · 악화 13쪽)은 같은 방향이되
    부류 구성이 달랐다(289쪽 · title 요소 0개). d3 에는 title 이 1,241개 있고 회전 지면이
    page_rotation 으로 걸러진다(478쪽).

★ 왜 회전 지면은 빼는가
  회전 쪽(page_rotation 90/270)은 좌표가 누워 있어 규칙이 이미 잘 푼다. 표본 16쪽에서
  LLM 이 τ 0.881 → 0.886 으로 사실상 무차인데 돈만 든다. 라우팅을 비회전으로 좁히면
  걸리는 쪽이 68.3% 로 줄고 이득은 오히려 조금 낫다(-2.64 → -2.66%p, 권당 5,261 → 3,593원).

★ 안전판(_GUARD_RATIO) — **현행 문안에서는 순손해다.** 값은 0.7 로 두되 근거를 알고 써라.
  옛 문안에서는 분산 축소 장치였다(터진 쪽을 막아 전체 -1.12%p 이득). 현행 문안에서는
  되돌리는 24쪽 중 **21쪽이 개선이고 악화는 2쪽**이라 전체 이득을 -3.27 → -2.44%p 로 깎는다.
  이유: displaced_ratio 는 "얼마나 옮겼나"지 "옳게 옮겼나"가 아니다. 사이드바 한 덩어리를
  통째로 옳게 뒤로 보내면 본문이 전부 2칸 이상 밀려 ratio 가 1.00 이 된다
  (세계사/val/026: 규칙 76.4% → 28.1%, τ 0.33 → 1.0 인 개선인데 모든 임계가 되돌린다).
  r39 책 단위 LOO — 한 권을 빼고 나머지 두 권에서 임계를 고르면 **세 번 모두 raw 가 뽑히고**
  뺀 권에서도 net-positive 다(사회문화 -2.55 · 생물 -6.26 · 세계사 -1.49). 같은 표본에서
  고른 값이 아니다. **켤 때 0 으로 내리는 것을 권고했다**(결과_r39-orderremeasure.md §8).
  ⚠ 내리는 결정은 대표 몫이라 이 파일은 안 건드렸다.

⚠ 라우팅 배선이 아직 없다. 지금 apply 는 "비회전 ∧ 요소≥4" 만 거르고 **부류(2단+사이드바)도
  수학 제외도 안 한다.** 그대로 켜면 비회전 653/1,131쪽을 다 불러 권당 3,522원이 되고
  수학·3단·4단+ 에서 손해를 본다. 켜기 전에 temp/order/layout.py 의 부류 판정을 옮겨야 한다.

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

# ★ 묻는 것은 **점자책에 적는 순서**이지 '사람이 눈으로 읽는 순서'가 아니다(r38, 2026-09-11).
#   종전 문안은 "사람이 이 쪽을 소리 내어 읽는다면" 을 물었다. 모델은 그 질문에는 맞게 답했는데,
#   점자책은 그렇게 적지 않는다 — 좌측 용어 사이드바를 본문과 같은 높이에 끼워 넣어, 규칙이
#   이미 맞던 쪽(τ=1.0) 34쪽을 깼다(세계사 val p152: CER 42.6% → 152.6%).
#   조판 관행을 넣은 뒤 그 34쪽이 13쪽으로 줄었고 정상 층 손해가 +5.81%p → −0.16%p 가 됐다.
# 규정 근거 —「점자 도서 제작 지침」2장 5. 다단 점역 (2) 주종 관계의 다단 ①(재추출 1150·1171행)
#   "다단이 본문과 참고 자료로 구성되어 있는 경우에는 본문에 해당하는 단을 우선 적고,
#    참고 자료는 본문 아래 한 줄 띄어 적는다."
#  「점자 자료 제작 지침」2.4.8 (2) 위계가 있는 다단(재추출 1186~1187행)도 같은 말이다.
#   규칙 쪽(`pipeline._reorder_columns` 3번 좁은 참고열 후치, #841)이 이미 지키는 조항인데
#   프롬프트만 이걸 몰랐다.
# ⚠ 조문을 **행 번호와 함께 프롬프트에 인용하는 판**도 재 봤다(r38 `cite` 팔). 이득이 없어
#   안 넣는다 — 관행을 우리 말로 적는 것으로 충분하고, 조문 인용은 토큰만 늘린다.
# ⚠ 회전 문장은 뺐다. `apply` 가 `rotation≠0` 이면 아예 안 부르므로 죽은 문장인데,
#   "읽기 방향이 x축일 수 있다"가 세로 배치를 가로로 읽을 여지를 열어 둔다.
_SYS = (
    "당신은 교과서·문제집 지면을 점자책으로 옮길 때 적는 순서를 판정하는 도우미다.\n"
    "입력은 한 쪽에서 추출된 요소 목록이다. 각 요소는 번호, 좌표 bbox=(x0,y0,x1,y1), 종류, "
    "본문 앞부분(최대 120자)을 가진다. 제시된 순서는 추출기가 내놓은 순서일 뿐 정답이 아니다.\n"
    "점자책은 지면을 눈으로 훑는 매체가 아니라 한 줄로 이어 읽는 글이라, 적는 순서가 "
    "'사람이 눈으로 보는 순서'와 다르다. 다음을 지킨다.\n"
    "1) 지면이 본문 단과 참고 자료 단으로 나뉘면(좁은 폭의 용어 설명·보충 해설·자료 열), "
    "본문 단을 끝까지 다 적은 뒤 참고 자료 단을 통째로 적는다. 같은 높이에 있다고 해서 "
    "참고 자료를 본문 사이에 끼워 넣지 않는다.\n"
    "2) 곁주석·각주 성격의 요소도 본문 흐름을 끊지 않는다. 본문 단이 끝난 자리에 모아 적는다.\n"
    "3) 열을 이루지 않는 낱개 상자·그림·그 설명은 후치 대상이 아니다. 딸린 본문 바로 뒤에 둔다.\n"
    "4) 본문끼리 나란한 동등한 단이면 왼쪽 단을 다 적은 뒤 오른쪽 단으로, 위 단을 다 적은 뒤 "
    "아래 단으로 간다.\n"
    "주어진 목록에 있는 번호만 쓴다. 목록에 없는 것을 지어내지 않는다.\n"
    "모든 요소 번호를 한 번씩만 쓴 순열을 order로 돌려준다. 설명은 쓰지 않는다."
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
