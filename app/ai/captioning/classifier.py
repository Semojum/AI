"""
GPT-4o로 크롭 이미지를 image / cartoon / chart 중 하나로 분류.
"""
import base64
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
    with open(image_path, "rb") as f:
        b64 = base64.b64encode(f.read()).decode()

    ext = Path(image_path).suffix.lstrip(".").lower()
    mime = "image/jpeg" if ext in ("jpg", "jpeg") else f"image/{ext}"

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
    )
    label = resp.choices[0].message.content.strip().lower()
    if label not in ("image", "cartoon", "chart"):
        label = "image"
    return label
