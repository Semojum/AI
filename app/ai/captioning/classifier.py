"""
외부 VLM으로 크롭 이미지를 image / cartoon / chart 중 하나로 분류(모델은 설정으로 고른다).
"""
import base64
import math
import os
from pathlib import Path

from dotenv import load_dotenv
from openai import OpenAI
from app.core.config import config

load_dotenv()

_client: OpenAI | None = None

# 라벨 4종. 'diagram'은 2026-08-07 QA(Step15)에서 추가 — 종전 3종에는 도식 라벨이 없어
# 모식도·구조도·조직도가 전부 'chart'로 무너졌다(Opus 판정 34크롭 중 9건 = 최다 오분류 패턴).
# 그 원인은 구 프롬프트 규칙 2가 "or is an organizational/flow/concept diagram → chart"라고
# **명시적으로 합쳐 놓은 것**이다. 규칙을 쪼개면서 chart를 '데이터 값이 찍힌 것'으로 좁히고,
# cartoon은 말풍선 유무가 아니라 '칸으로 나뉜 그림 이야기'로 넓힌다(만화 4건이 chart로 샜다).
LABELS = ("image", "cartoon", "chart", "diagram")

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


def _get_client() -> OpenAI:
    global _client
    if _client is None:
        _client = OpenAI(api_key=config.openai_api_key or None)
    return _client


def classify(image_path: str) -> str:
    """
    Returns 'image' | 'cartoon' | 'chart' | 'diagram'
    """
    return classify_with_confidence(image_path)[0]


def classify_with_confidence(image_path: str) -> tuple[str, float | None]:
    """
    Returns (label, confidence).
    label = 'image' | 'cartoon' | 'chart' | 'diagram'
    confidence = 라벨 토큰들의 logprob 합을 exp한 확률(0~1).
      - 응답이 세 라벨 밖이면 0.0 (형식 이탈 자체가 불확실 신호 → R2 대상)
      - API가 logprobs를 안 주면 None (신뢰도 판단 불가 — 플래그 안 띄움)
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
        return "image", 0.0

    confidence: float | None = None
    try:
        tokens = choice.logprobs.content or []
        # 공백·개행뿐인 스캐폴드 토큰은 제외하고 라벨 토큰의 확률만 본다.
        lps = [t.logprob for t in tokens if t.token.strip()]
        if lps:
            confidence = math.exp(sum(lps))
    except (AttributeError, TypeError):
        pass  # logprobs 미제공 → None
    return label, confidence


def _classify_anthropic(b64: str, mime: str):
    """Anthropic 백엔드 분류. logprobs API가 없어 confidence=None을 준다.
    quality_checker는 confidence None이면 R2를 띄우지 않는다(설계된 경로).

    ★ 캡션과 **같은 이미지 해시 캐시**를 쓴다(2026-08-23 대표 결재 ㉯). 시각 요소 하나에
      API가 두 번 나가는데(분류 + 캡션) 종전에는 캡션만 캐시가 막았다. 분류 응답은 라벨
      한 단어라 캐시가 특히 싸다 — 전 코퍼스 1회 추출 기준 도입가 1.67달러가 빠진다.
      키에 `image_type="__classify__"`를 줘 캡션 항목과 섞이지 않게 한다.
    ⚠ 프롬프트 캐싱은 여기 못 건다 — `SYSTEM_PROMPT`가 **319토큰**이라 최소 캐시 길이
      1,024에 못 미친다. 표시를 달아도 조용히 캐시되지 않는다.
    """
    import anthropic
    from app.core.limits import estimate_tokens, llm_limiter
    from app.utils.req_log import record_anthropic
    from app.ai.captioning.captioner import _cache_file
    raw = base64.b64decode(b64)
    cache = _cache_file(raw, "__classify__", SYSTEM_PROMPT)
    if cache is not None and cache.exists():
        label = cache.read_text(encoding="utf-8").strip()
        return (label, None) if label in LABELS else ("image", 0.0)
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
        return "image", 0.0        # 형식 이탈 = 불확실 신호(R2 대상)
    # 형식 이탈은 캐시하지 않는다 — 한 번 어긋난 응답이 영구히 굳으면 그 그림은
    # 다시는 제 라벨을 못 받는다(빈 캡션을 안 굽는 것과 같은 이유).
    if cache is not None:
        cache.write_text(label, encoding="utf-8")
    return label, None
