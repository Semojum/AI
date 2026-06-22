"""
GPT-4o로 크롭 이미지를 한국어 텍스트로 묘사.
image/cartoon/chart 각각 다른 프롬프트 사용.
"""
import base64
import os
from pathlib import Path

from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

_client: OpenAI | None = None

_PROMPTS = {
    "image": (
        "이 이미지를 시각장애인을 위해 한국어로 상세히 묘사해 주세요. "
        "이미지에 보이는 주요 요소, 색상, 배치, 분위기를 구체적으로 설명하세요."
    ),
    "cartoon": (
        "이 만화 이미지를 시각장애인을 위해 한국어로 묘사해 주세요. "
        "등장인물과 상황을 설명하고, 말풍선의 대사는 빠짐없이 그대로 인용하여 "
        "장면 묘사와 함께 하나의 문단으로 작성하세요."
    ),
    "chart": (
        "이 차트/그래프를 시각장애인을 위해 한국어로 설명해 주세요. "
        "차트 종류, 제목, 축 레이블, 주요 데이터 값과 추세를 구체적으로 서술하세요."
    ),
}


def _get_client() -> OpenAI:
    global _client
    if _client is None:
        _client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
    return _client


def caption(image_path: str, image_type: str = "image") -> str:
    """
    image_type: 'image' | 'cartoon' | 'chart'
    Returns Korean description string.
    """
    prompt = _PROMPTS.get(image_type, _PROMPTS["image"])

    with open(image_path, "rb") as f:
        b64 = base64.b64encode(f.read()).decode()

    ext = Path(image_path).suffix.lstrip(".").lower()
    mime = "image/jpeg" if ext in ("jpg", "jpeg") else f"image/{ext}"

    from app.utils.req_log import inc_gpt4o
    inc_gpt4o()
    resp = _get_client().chat.completions.create(
        model="gpt-4o",
        messages=[
            {
                "role": "user",
                "content": [
                    {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}},
                    {"type": "text", "text": prompt},
                ],
            }
        ],
        max_tokens=500,
        temperature=0.3,
    )
    return resp.choices[0].message.content.strip()
