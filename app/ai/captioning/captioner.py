"""
GPT-4o로 크롭 이미지를 한국어 텍스트로 묘사.
image/cartoon/chart 각각 다른 프롬프트 사용.
"""
import re
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
# ★ 규정 정답과 대조해 보니(kpi_regulation.py, 2026-07-17) 우리 캡션은 R 22% / P 11% —
#   내용은 담는데 2~4배 길다. 원인 두 가지가 규정 원문에 그대로 있다:
#     (1) "간결한 **어구**나 문장" — 완전한 문장을 강요할 필요가 없다.
#     (6) "과정 흐름에 대한 설명은 위계가 있는 **개조식 항목**으로" — 산문으로 풀면 안 된다.
#   그리고 (2) "핵심 내용"은 **무엇을 뜻하는지**다. 규정 정답은 "현재: 학교에 다니고 있다"인데
#   우리는 "교복을 입고 책가방을 멘 학생이 서 있음"이라 적었다 — 외형은 핵심이 아니다.
_COMMON = (
    "당신은 시각장애 학생용 점자 교과서를 만드는 점역사입니다.\n"
    "「점자 자료 제작 지침」 6.1.4에 따라 설명하세요.\n"
    "- 이 자료가 **무엇을 뜻하는지**를 쓰세요. 무엇이 보이는지가 아닙니다 (규정 2).\n"
    "  옷차림·자세·표정·위치·색은 그 뜻에 필요할 때만 씁니다. 대개는 필요 없습니다.\n"
    "  예: '학교에 다니고 있다'(O) / '교복을 입고 책가방을 멘 학생이 서 있다'(X)\n"
    "- 가능한 적은 수의 단어로. 완전한 문장이 아니라 어구여도 됩니다 (규정 1).\n"
    "- 과정·흐름은 산문으로 풀지 말고 개조식으로. 화살표 →를 쓰세요 (규정 6).\n"
    "- 한 번 읽고 이해되도록 명료하게 (규정 3).\n"
    "- 전체 윤곽을 한 줄로 먼저, 그 다음 부분을 나누어 (규정 4).\n"
    "- 자료에 있는 제목·글자·수치는 그대로 옮기세요. 지어내지 마세요.\n"
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
        "수치는 하나도 빠뜨리거나 바꾸지 마세요. 추세는 사실만 진술하세요.\n"
        # 도서지침 예3-32(비율)·3-34(막대) 실측 형식: 데이터는 '항목: 값' 한 줄씩.
        "데이터는 지침 형식대로 '항목: 값' 을 한 줄에 하나씩 적으세요. "
        "예)\n양반: 26.29%\n상민: 59.78%\n"
        "쉼표로 이어 붙이지 마세요. 그룹(연도 등)이 나뉘면 그룹명을 한 줄로 먼저 적으세요."
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


# 유형 제시어(§6.3.4(1)): 캡션 첫머리를 자료 유형으로 시작한다. LLM 프롬프트가 아니라
# rule-based로 붙인다 — 분류기가 유형을 이미 알고, 규정 틀 검증(kpi_regulation.py)에서
# LLM이 제시어를 자주 빼먹는 게 최대 실패 항목이었다(2026-07-17, 틀 통과 8/18의 주원인).
_TYPE_WORD = {"image": "그림", "cartoon": "만화", "chart": "그래프", "chart_graph": "그래프"}
_TYPE_WORDS_ALL = ("그림", "사진", "그래프", "삽화", "만화", "지도", "표", "도표")


_TYPE_COLON_RES = None  # lazy — 유형 제시어+쌍점 패턴


def _has_type_colon(s: str) -> bool:
    """유형 제시어(그림·그래프 등)+쌍점으로 시작하는가 — 지침 §6.3.4 '유형, 쌍점, 내용'."""
    global _TYPE_COLON_RES
    if _TYPE_COLON_RES is None:
        _TYPE_COLON_RES = re.compile(
            r"^(?:" + "|".join(map(re.escape, _TYPE_WORDS_ALL)) + r")\s*[:：]")
    return bool(_TYPE_COLON_RES.match(s))


# 제목줄 패턴: 유형+번호("그림 2-1." "표 1.") — 제시어가 아니라 자료 제목이다(지침 예3-20).
_TITLE_LINE_RE = re.compile(
    r"^(?:" + "|".join(map(re.escape, _TYPE_WORDS_ALL)) + r")\s*\d+(?:[.\-]\d+)*\.?\s")


def _ensure_type_word(text: str, image_type: str) -> str:
    """지침 §6.3.4: 설명 본문은 '유형 제시어 + 쌍점'으로 시작해야 한다.

    ⚠ 단순 startswith(유형) 판정은 제목줄("그림 2-1. …")을 제시어로 오판해 본문
    제시어를 생략시켰다(지침 예3-20 프레임 검사 실측, 2026-07-19). 쌍점까지 요구하고,
    제목줄이면 제목은 유지한 채 다음 본문 앞에 제시어를 삽입한다.
    """
    t = (text or "").strip()
    if not t:
        return t
    if _has_type_colon(t):
        return t
    tw = _TYPE_WORD.get(image_type, "그림")
    if _TITLE_LINE_RE.match(t):
        nl = t.find("\n")
        if nl > 0:
            title, body = t[:nl].rstrip(), t[nl + 1:].strip()
            if body and not _has_type_colon(body):
                return f"{title}\n{tw}: {body}"
            return t
        return t  # 제목 한 줄뿐 — 본문 없음, 그대로
    return f"{tw}: {t}"


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

    if os.getenv("CAPTION_BACKEND", "anthropic") == "anthropic":
        return _ensure_type_word(_caption_anthropic(b64, mime, prompt), image_type)

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
    return _ensure_type_word(resp.choices[0].message.content.strip(), image_type)
