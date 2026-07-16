"""
GPT-4o로 크롭 이미지를 image / cartoon / chart 중 하나로 분류.
"""
import base64
import math
import os
from pathlib import Path

from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

_client: OpenAI | None = None

SYSTEM_PROMPT = (
    "You are an image classifier. "
    "Given an image, respond with exactly one word using these rules in order: "
    "1. If the image contains speech bubbles, respond 'cartoon'. "
    "2. If the image contains axes, legends, data values, or is an organizational/flow/concept diagram, respond 'chart'. "
    "3. Otherwise, respond 'image'."
)


def _get_client() -> OpenAI:
    global _client
    if _client is None:
        _client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
    return _client


def classify(image_path: str) -> str:
    """
    Returns 'image' | 'cartoon' | 'chart'
    """
    return classify_with_confidence(image_path)[0]


def classify_with_confidence(image_path: str) -> tuple[str, float | None]:
    """
    Returns (label, confidence).
    label = 'image' | 'cartoon' | 'chart'
    confidence = 라벨 토큰들의 logprob 합을 exp한 확률(0~1).
      - 응답이 세 라벨 밖이면 0.0 (형식 이탈 자체가 불확실 신호 → R2 대상)
      - API가 logprobs를 안 주면 None (신뢰도 판단 불가 — 플래그 안 띄움)
    """
    with open(image_path, "rb") as f:
        b64 = base64.b64encode(f.read()).decode()

    ext = Path(image_path).suffix.lstrip(".").lower()
    mime = "image/jpeg" if ext in ("jpg", "jpeg") else f"image/{ext}"

    if os.getenv("CAPTION_BACKEND", "openai") == "anthropic":
        return _classify_anthropic(b64, mime)

    from app.utils.req_log import inc_gpt4o
    inc_gpt4o()
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
    choice = resp.choices[0]
    label = choice.message.content.strip().lower()
    if label not in ("image", "cartoon", "chart"):
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
    quality_checker는 confidence None이면 R2를 띄우지 않는다(설계된 경로)."""
    import anthropic
    from app.utils.req_log import inc_gpt4o
    inc_gpt4o()
    client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
    resp = client.messages.create(
        model=os.getenv("CAPTION_MODEL", "claude-sonnet-5"),
        max_tokens=10,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": [
            {"type": "image", "source": {"type": "base64", "media_type": mime, "data": b64}},
        ]}],
    )
    label = "".join(b.text for b in resp.content if b.type == "text").strip().lower()
    if label not in ("image", "cartoon", "chart"):
        return "image", 0.0        # 형식 이탈 = 불확실 신호(R2 대상)
    return label, None
