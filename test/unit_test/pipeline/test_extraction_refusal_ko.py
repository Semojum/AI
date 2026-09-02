"""추출 모델이 한국어로 쓴 '못 읽었다' 해설문 억제(FE QA S-7).

종전 패턴이 전부 영어라, 한국어로 답하는 모델의 해설문은 한 줄도 안 걸려 초안에
그대로 실렸다. 본문을 잘못 지우면 더 나쁘므로 양방향으로 잰다.
"""
import pytest

from app.core.pipeline import _is_extraction_refusal

해설문 = [
    "이 페이지에는 읽을 수 있는 텍스트가 없습니다.",
    "이미지에서 판독 가능한 글자가 보이지 않습니다.",
    "텍스트가 없습니다",
    "죄송합니다. 이 지면은 흐려서 추출할 수 없습니다.",
    "저는 AI 언어 모델이라 이미지를 직접 볼 수 없습니다.",
    "이 이미지에는 텍스트가 없습니다",
    "No discernible text in this page.",
]

본문 = [
    "읽을 수 있는 글자를 크게 키운 예시이다.",
    "그림: 세포막 안은 양전하를 띤다.",
    "표에 없는 값은 0으로 본다.",
    "이 페이지에는 그림 3개와 표 1개가 있다.",
    "죄송하다는 말을 반복하는 인물의 심리를 서술하시오.",
]


@pytest.mark.parametrize("t", 해설문)
def test_해설문은_막는다(t):
    assert _is_extraction_refusal(t)


@pytest.mark.parametrize("t", 본문)
def test_본문은_살린다(t):
    assert not _is_extraction_refusal(t)
