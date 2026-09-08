"""
외부 VLM으로 크롭 이미지를 image / cartoon / chart 중 하나로 분류(모델은 설정으로 고른다).
"""
import base64
import math
import os
from pathlib import Path

from openai import OpenAI
from app.core.config import config
from app.ai.llm.diagram_structure import SUBTYPES
from app.utils.logger import get_logger

logger = get_logger(__name__)

_client: OpenAI | None = None

# 라벨 4종. 'diagram'은 2026-08-07 QA(Step15)에서 추가 — 종전 3종에는 도식 라벨이 없어
# 모식도·구조도·조직도가 전부 'chart'로 무너졌다(Opus 판정 34크롭 중 9건 = 최다 오분류 패턴).
# 그 원인은 구 프롬프트 규칙 2가 "or is an organizational/flow/concept diagram → chart"라고
# **명시적으로 합쳐 놓은 것**이다. 규칙을 쪼개면서 chart를 '데이터 값이 찍힌 것'으로 좁히고,
# cartoon은 말풍선 유무가 아니라 '칸으로 나뉜 그림 이야기'로 넓힌다(만화 4건이 chart로 샜다).
LABELS = ("image", "cartoon", "chart", "diagram")

# ★ 도표 세분류는 **분류와 별개의 콜**로 받는다(2026-09-08, #784).
#   종전에는 사람이 읽는 캡션 문장을 정규식으로 되읽어 정했다
#   (`diagram_structure.subtype_from_caption`). 그래서 캡션 문안을 손볼 때마다 조용히
#   끊겼다 — #646 이 "종류 이름을 쓰지 마세요" 를 넣고 #734 가 남은 낱말을 떼자 이틀 만에
#   `visual_subtype` 이 20/20 빈칸이 됐고 §6.6 골격 8종이 **한 번도 돌지 않았다**
#   (실측 `temp/label46/흔들림_0908.md` §5).
#
# ⚠ **왜 같은 콜에 안 싣나.** 처음에는 분류 응답에 낱말 하나를 더 받게 했다(호출 0 증가).
#   그런데 `SYSTEM_PROMPT` 에 세분류 어휘를 더하면 **라벨 판정이 움직인다** — 문안 세 판
#   (뜻풀이 포함·열쇠만·사용자 턴)을 4-6 표본 36크롭 × 3회로 재 보니 전부 4~6건이 갈렸고,
#   칸으로 나뉜 인생 5시기 **만화**가 세 판 모두 `diagram timeline` 으로 끌려갔다
#   (develop 은 3회 내내 `cartoon`). 사람 정답 대비 11/11 → 10/11.
#   ★ 그 움직임을 실측으로 걷어낼 수도 없다 — 이 모델은 `temperature` 를 **거절한다**
#     (400 `temperature is deprecated for this model`, 2026-09-08 실호출 확인). 그래서
#     같은 프롬프트로도 세션이 바뀌면 3/36 이 갈린다(develop 재측정으로 확인).
#   콜을 가르면 `SYSTEM_PROMPT` 가 develop 과 **바이트로 같아** 라벨이 안 움직이는 것이
#   실측이 아니라 **구조적 보장**이다. 값은 도표에만 한 콜 더 든다(실측 크롭의 약 30%,
#   콜당 $0.0041 → 전 코퍼스 1회 추출당 약 +$4.5. 캡셔닝 몫 $32 대비 14%).
#
#   값 집합은 「점자 자료 제작 지침」 §6.6 의 여덟 중 일곱이다(`diagram_structure.SUBTYPES`).
#   §6.6.7 화면 이미지는 실물 0건이라 2026-09-09(#793)에 뺐다 — 그 상수 주석 참조.
#   조항을 못 대는 낱말은 안 만든다.
#
# 아래 표가 그 일곱과 조항이다.
_SUBTYPE_CLAUSE = {
    "concept_map": "6.6.1",    # 개념도  L3526 "중심 개념에서 하위 개념으로 가지가 뻗어나간"
    "flowchart": "6.6.2",      # 흐름도  L3542 "작업과 처리 순서를 표시"
    "form": "6.6.3",           # 양식    L3640 "채워야 할 빈칸이나 선택 사항이 있는 양식"
    "family_tree": "6.6.4",    # 가계도  L3668 "선조와 후손 간의 연결 관계"
    "org_chart": "6.6.5",      # 조직도  L3722 "조직의 구조나 인적 구성"
    "timeline": "6.6.6",       # 연대표  L3781 "사건을 시간 순서에 따라"
    "slide": "6.6.8",          # 발표용 슬라이드 L3854 "파워포인트나 키노트 등에서 작성된 것"
}

SYSTEM_PROMPT = (
    "You are an image classifier for a Korean braille textbook pipeline. "
    "Given an image, respond with exactly one word, applying these rules in order:\n"
    "1. 'cartoon' — a drawn story: speech/thought bubbles, OR panels/frames read in sequence, "
    "OR drawn characters shown speaking. Comics count even without bubbles.\n"
    "2. 'chart' — it plots DATA: numeric axes with a scale, plotted bars/lines/points/pie slices, "
    "or a legend mapping series to values. It must show quantities.\n"
    "3. 'diagram' — a labelled schematic with NO plotted quantities: 모식도, 구조도, 개념도, "
    "흐름도, 조직도, 계통도, cycle or process arrows, boxes-and-arrows, cross-sections, maps.\n"
    "4. 'image' — everything else: photographs, illustrations, decorative art, logos, icons.\n"
    "Decorative shapes with a word inside are 'image', not 'chart'."
)


# 세분류 프롬프트. 이 글은 이미 `diagram` 으로 판정된 그림에만 쓰인다 —
# 분류 규칙(`SYSTEM_PROMPT`)과 절대 한 자리에 두지 않는다(위 ⚠).
# ★ 뜻풀이는 **규정 조문 그대로**다(§6.6 각 절 첫 문장, 아래 `_SUBTYPE_CLAUSE` 의 행 번호).
#   여기서는 뜻풀이를 실어도 라벨이 안 움직인다 — 콜이 갈려 있어 분류가 이 글을 안 본다.
#   ⚠ 뜻풀이를 지어내지 마라. 첫 판에 "a cycle of natural stages 는 none" 이라고 **내가
#     지어 쓴** 예외 목록을 넣었더니 세분류 수확이 도표 11건 중 7 → 10건 중 1 로 떨어졌다.
#     §6.6.2 는 흐름도를 "작업과 처리 순서를 표시한 시각 자료" 로 정의한다 — 물질 순환도는
#     그 조문에 들어간다. 조문에 없는 배제 규칙은 규정을 좁히는 것이다.
_SUBTYPE_PROMPT = (
    "This image is a diagram from a Korean school textbook. Answer with exactly one word "
    "naming what kind of diagram it is. The seven kinds and their definitions come from "
    "the Korean braille production guideline §6.6 (§6.6.7 화면 이미지 is out of "
    "the list on purpose — see diagram_structure.SUBTYPES):\n"
    "- concept_map — a centre concept with branches running out to sub-concepts (§6.6.1)\n"
    "- flowchart — work and processing steps shown in order (§6.6.2)\n"
    "- form — a form carrying blanks to fill in or options to tick (§6.6.3)\n"
    "- family_tree — the connections between ancestors and descendants (§6.6.4)\n"
    "- org_chart — the structure or staffing of an organisation, its ranks and units (§6.6.5)\n"
    "- timeline — events written out in time order (§6.6.6)\n"
    "- slide — a presentation slide made in PowerPoint or Keynote (§6.6.8)\n"
    "Answer 'none' only when the picture matches none of those seven definitions. "
    "Answer with the single word and nothing else."
)


def _get_client() -> OpenAI:
    global _client
    if _client is None:
        _client = OpenAI(api_key=config.openai_api_key or None)
    return _client


def _parse_subtype(raw: str) -> str:
    """세분류 콜 응답 → §6.6 하위유형. 일곱 밖이면 ""(골격 미적용 = 캡션·설명 폴백).

    **억지로 배정하지 않는다** — §6.6 밖 자료(지도·벤다이어그램·해부도)에 골격을 씌우면
    위계 없는 자료에 위계 개조식이 붙는다. 그래서 프롬프트가 'none' 을 허용한다.
    캐시에 담긴 `diagram flowchart` 꼴도 같은 함수로 읽는다(마지막 낱말을 본다).
    """
    parts = raw.strip().lower().replace(",", " ").split()
    sub = parts[-1].strip("()'\".") if parts else ""
    return sub if sub in SUBTYPES else ""


def classify(image_path: str) -> str:
    """
    Returns 'image' | 'cartoon' | 'chart' | 'diagram'
    """
    return classify_with_confidence(image_path)[0]


def classify_with_confidence(image_path: str) -> tuple[str, float | None, str]:
    """
    Returns (label, confidence, visual_subtype).
    label = 'image' | 'cartoon' | 'chart' | 'diagram'
    confidence = 라벨 토큰들의 logprob 합을 exp한 확률(0~1).
      - 응답이 네 라벨 밖이면 0.0 (형식 이탈 자체가 불확실 신호 → R2 대상)
      - API가 logprobs를 안 주면 None (신뢰도 판단 불가 — 플래그 안 띄움)
    visual_subtype = 라벨이 'diagram' 일 때 §6.6 하위유형 일곱 중 하나, 아니면 ""
      (`diagram_structure.SUBTYPES`). 경계 JSON 의 `visual_subtype` 으로 나가
      `diagram_opt._ASSEMBLERS` 가 골격을 세우는 데 쓴다.
    """
    with open(image_path, "rb") as f:
        b64 = base64.b64encode(f.read()).decode()

    ext = Path(image_path).suffix.lstrip(".").lower()
    mime = "image/jpeg" if ext in ("jpg", "jpeg") else f"image/{ext}"

    if os.getenv("CAPTION_BACKEND", "anthropic") == "anthropic":
        return _classify_anthropic(b64, mime)

    from app.utils.req_log import record_openai
    resp = _get_client().chat.completions.create(
        model="gpt-4o",
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {
                "role": "user",
                "content": [
                    {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}},
                    {"type": "text", "text": "Classify this image."},
                ],
            },
        ],
        max_tokens=5,
        temperature=0,
        logprobs=True,
    )
    record_openai("분류", "gpt-4o", getattr(resp, "usage", None))
    choice = resp.choices[0]
    label = choice.message.content.strip().lower()
    if label not in LABELS:
        return "image", 0.0, ""

    confidence: float | None = None
    try:
        tokens = choice.logprobs.content or []
        # 공백·개행뿐인 스캐폴드 토큰은 제외하고 라벨 토큰의 확률만 본다.
        lps = [t.logprob for t in tokens if t.token.strip()]
        if lps:
            confidence = math.exp(sum(lps))
    except (AttributeError, TypeError):
        pass  # logprobs 미제공 → None
    # ★ 세분류는 anthropic 팔에만 배선했다. `CAPTION_BACKEND=openai` 는 제품 경로가 아니라
    #   (기본값이 anthropic) 안 재 보고 코드를 늘리지 않는다. 이 팔에서는 캡션 폴백
    #   (`diagram_structure.subtype_from_caption`)이 그대로 산다.
    return label, confidence, ""


def _classify_anthropic(b64: str, mime: str):
    """Anthropic 백엔드 분류. logprobs API가 없어 confidence=None을 준다.
    quality_checker는 confidence None이면 R2를 띄우지 않는다(설계된 경로).

    ★ 캡션과 **같은 캐시 디렉터리**를 쓰되 `classify/` 하위로 갈라 담는다(3-c).
      종전에는 라벨 한 단어가 캡션과 **한 자리에 섞여** 있었다 — 3,242건 안에 캡션 1,961 +
      라벨 1,281 이다. 섞인 채로 옮기거나 쓸어 담으면 라벨이 캡션 자리로 들어가
      `그림: chart` 가 나온다(실제로 관찰됐다).
      캐시를 쓰는 이유는 그대로다(2026-08-23 대표 결재 ㉯). 시각 요소 하나에
      API가 두 번 나가는데(분류 + 캡션) 종전에는 캡션만 캐시가 막았다. 분류 응답은 라벨
      한 단어라 캐시가 특히 싸다 — 전 코퍼스 1회 추출 기준 도입가 1.67달러가 빠진다.
    ⚠ 프롬프트 캐싱은 여기 못 건다 — `SYSTEM_PROMPT`가 **319토큰**이라 최소 캐시 길이
      1,024에 못 미친다. 표시를 달아도 조용히 캐시되지 않는다.
    """
    import anthropic
    from app.core.limits import estimate_tokens, llm_limiter
    from app.utils.req_log import record_anthropic
    from app.ai.captioning.captioner import _cache_new_file, _kind_matches
    raw = base64.b64decode(b64)
    # 판 번호 열쇠(3-c) + 격리 열쇠(3-e). 옛 자리(전문 키)는 2026-09-08 에 없앴다 —
    # 열쇠에 고객이 안 들어가 고객 사이에 샌다. 캐시는 여기서부터 새로 쌓는다(대표 결정).
    cache = _cache_new_file("classify", raw, "classify")
    if cache is not None and cache.exists():
        label = cache.read_text(encoding="utf-8").strip()
        if _kind_matches("classify", label):   # 캡션이 라벨 자리에 있으면 없는 셈 친다
            if label not in LABELS:
                return "image", 0.0, ""
            return label, None, (_subtype(b64, mime, raw) if label == "diagram" else "")
    llm_limiter().acquire_sync(estimate_tokens(SYSTEM_PROMPT, len(b64) * 3 // 4), 10)
    model = os.getenv("CAPTION_MODEL", "claude-sonnet-5")
    client = anthropic.Anthropic(api_key=config.anthropic_api_key or None)
    resp = client.messages.create(
        model=model,
        max_tokens=10,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": [
            {"type": "image", "source": {"type": "base64", "media_type": mime, "data": b64}},
        ]}],
    )
    record_anthropic("분류", model, getattr(resp, "usage", None))
    label = "".join(b.text for b in resp.content if b.type == "text").strip().lower()
    if label not in LABELS:
        return "image", 0.0, ""    # 형식 이탈 = 불확실 신호(R2 대상)
    # 형식 이탈은 캐시하지 않는다 — 한 번 어긋난 응답이 영구히 굳으면 그 그림은
    # 다시는 제 라벨을 못 받는다(빈 캡션을 안 굽는 것과 같은 이유).
    if cache is not None:
        cache.write_text(label, encoding="utf-8")
    return label, None, (_subtype(b64, mime, raw) if label == "diagram" else "")


def _subtype(b64: str, mime: str, raw: bytes) -> str:
    """§6.6 세분류 한 낱말. 도표로 판정된 그림에만 부른다(#784).

    분류와 **다른 콜**이라 `SYSTEM_PROMPT` 가 develop 과 바이트로 같다 — 라벨이 안
    움직이는 것이 구조적 보장이다(위 ⚠). 캐시는 `subtype/` 로 따로 담는다.
    실패해도 쪽은 나가야 한다 — 못 받으면 ""(캡션 폴백 + 설명 초안)으로 물러난다.
    """
    import anthropic
    from app.core.limits import estimate_tokens, llm_limiter
    from app.utils.req_log import record_anthropic
    from app.ai.captioning.captioner import _cache_new_file, _kind_matches

    cache = _cache_new_file("subtype", raw, "subtype")
    if cache is not None and cache.exists():
        cached = cache.read_text(encoding="utf-8").strip()
        if _kind_matches("subtype", cached):
            return _parse_subtype(cached)
    model = os.getenv("CAPTION_MODEL", "claude-sonnet-5")
    try:
        llm_limiter().acquire_sync(estimate_tokens(_SUBTYPE_PROMPT, len(b64) * 3 // 4), 10)
        resp = anthropic.Anthropic(api_key=config.anthropic_api_key or None).messages.create(
            model=model,
            max_tokens=10,
            system=_SUBTYPE_PROMPT,
            messages=[{"role": "user", "content": [
                {"type": "image", "source": {"type": "base64", "media_type": mime, "data": b64}},
            ]}],
        )
    except Exception as exc:            # noqa: BLE001 — 세분류를 못 받아도 라벨은 살았다
        logger.warning("세분류 콜 실패(골격 없이 진행): %s: %s", type(exc).__name__, exc)
        return ""
    record_anthropic("세분류", model, getattr(resp, "usage", None))
    answer = "".join(b.text for b in resp.content if b.type == "text").strip().lower()
    sub = _parse_subtype(answer)
    # 일곱 밖('none' 포함)도 담는다 — 같은 그림에 같은 질문을 다시 하지 않는다.
    # `diagram` 을 앞에 붙이는 것은 `_kind_matches` 가 첫 낱말로 자리를 가르기 때문이다.
    if cache is not None and answer:
        cache.write_text(f"diagram {sub or 'none'}", encoding="utf-8")
    return sub
