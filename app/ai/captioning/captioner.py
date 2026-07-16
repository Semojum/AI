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

# 프롬프트는 「점자 자료 제작 지침」 6.1.4 시각 자료 설명을 근거로 한다.
#   (1) 간결한 문장 — 가능한 적은 수의 단어로
#   (2) 핵심 내용 전달 — 핵심에 초점
#   (3) 명료한 표현 — 한 번 읽고 이해되도록
#   (4) 단계적 접근 — 전체 윤곽 → 부분
#   (6) 개조식 표현 — 과정·흐름은 위계 있는 개조식
#   (7) 진술적 설명 — 사실을 문장으로 진술(대부분의 시각 자료)
#   (8) 독자 특성 — 주제에 적합한 단어
# 6.3.4(2): 점역자 주표 안에 '시각 자료 유형: 추가 설명문' 형식.
# ★ 색상·분위기 같은 시각적 인상은 규정이 요구하지 않는다(핵심 내용 아님).
#   마크다운·머리말 금지 — 점자로 옮길 평문이어야 한다.
_COMMON = (
    "당신은 시각장애 학생용 점자 교과서를 만드는 점역사입니다.\n"
    "「점자 자료 제작 지침」 6.1.4에 따라 설명하세요.\n"
    "- 가능한 적은 수의 단어로 간결하게 (규정 1)\n"
    "- 핵심 내용에 초점 (규정 2)\n"
    "- 한 번 읽고 이해되도록 명료하게 (규정 3)\n"
    "- 전체 윤곽을 먼저, 그 다음 부분을 단계적으로 (규정 4)\n"
    "- 색상·분위기·시각적 인상은 쓰지 마세요. 정보가 아닙니다.\n"
    "- 마크다운(#, **, 목록 기호)·머리말·인사말 없이 평문만 출력하세요.\n"
)

_PROMPTS = {
    "image": _COMMON + (
        "이 그림의 내용을 사실 위주로 진술하세요 (규정 7). "
        "그림에 글자가 있으면 그대로 옮기세요."
    ),
    "cartoon": _COMMON + (
        "이 만화의 장면과 등장인물을 설명하고, 말풍선 대사는 빠짐없이 그대로 인용하세요. "
        "칸 순서대로 서술하세요."
    ),
    "chart": _COMMON + (
        "이 차트의 종류·제목·축 이름을 먼저 밝히고, 데이터 값을 정확히 옮기세요. "
        "수치는 하나도 빠뜨리거나 바꾸지 마세요. 추세는 사실만 진술하세요."
    ),
}



def _get_client() -> OpenAI:
    global _client
    if _client is None:
        _client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
    return _client


# 백엔드 전환 — 모델 비교 실험용. 기본은 기존 GPT-4o 경로 그대로.
#   CAPTION_BACKEND=anthropic CAPTION_MODEL=claude-sonnet-5
def _caption_anthropic(b64: str, mime: str, prompt: str) -> str:
    import anthropic
    from app.utils.req_log import inc_gpt4o
    inc_gpt4o()                       # 호출 수 집계는 공용
    client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
    resp = client.messages.create(
        model=os.getenv("CAPTION_MODEL", "claude-sonnet-5"),
        max_tokens=500,
        messages=[{
            "role": "user",
            "content": [
                {"type": "image",
                 "source": {"type": "base64", "media_type": mime, "data": b64}},
                {"type": "text", "text": prompt},
            ],
        }],
    )
    _record_usage(resp)
    return "".join(b.text for b in resp.content if b.type == "text").strip()


_USAGE = {"calls": 0, "in": 0, "out": 0}


def _record_usage(resp) -> None:
    u = getattr(resp, "usage", None)
    if not u:
        return
    _USAGE["calls"] += 1
    _USAGE["in"] += getattr(u, "input_tokens", 0) or 0
    _USAGE["out"] += getattr(u, "output_tokens", 0) or 0


def usage_report() -> dict:
    """이번 프로세스의 캡셔닝 API 사용량(호출·토큰). 비용 보고용."""
    return dict(_USAGE)


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

    if os.getenv("CAPTION_BACKEND", "openai") == "anthropic":
        return _caption_anthropic(b64, mime, prompt)

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
