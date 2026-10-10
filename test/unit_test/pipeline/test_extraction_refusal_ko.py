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
    "이 지면은 흐려서 추출할 수 없습니다.",          # 머리 '죄송합니다' 없이도(#1288 좁힌 패턴)
]

본문 = [
    "읽을 수 있는 글자를 크게 키운 예시이다.",
    "그림: 세포막 안은 양전하를 띤다.",
    "표에 없는 값은 0으로 본다.",
    "이 페이지에는 그림 3개와 표 1개가 있다.",
    "죄송하다는 말을 반복하는 인물의 심리를 서술하시오.",
    # #1288 전권 묵자 글자층에서 걸렸던 본문(한다체). 문단이 통째로 비었다.
    "살아 있는 동안 육체와 영혼은 서로 얽혀 순수하게 인식할 수 없으므로",                  # 생활과 윤리 p0037
    # 보기 줄 문장 끝 꼴. 지어낸 문장이다. 이 꼴이 실제로 걸린 쪽은 동결 홀드아웃 책이라 쓰지 않는다(#1292).
    "ㄹ. 빛이 없는 곳에서는 물체의 색을 인식할 수 없다.",
]


@pytest.mark.parametrize("t", 해설문)
def test_해설문은_막는다(t):
    assert _is_extraction_refusal(t)


@pytest.mark.parametrize("t", 본문)
def test_본문은_살린다(t):
    assert not _is_extraction_refusal(t)


def test_글자층_글에는_해설문_검사를_걸지_않는다():
    """#1288 글자층(TEXT_NATIVE)에는 모델 해설문이 생길 수 없다. 걸리면 본문만 지운다."""
    from app.core.pipeline import _parse_txt_result
    el = {"id": "00000000-0000-0000-0000-000000001288", "order": 1, "type": "text",
          "content": "이 지면은 흐려서 추출할 수 없습니다.", "bbox": [10, 10, 200, 40]}
    for method, kept in (("TEXT_NATIVE", True), ("OCR", False)):
        lay, em, _ = _parse_txt_result({"meta": {"extraction_method": method}, "elements": [el]}, "p")
        b = lay.elements[0]
        assert (em[b.element_id].corrected_text == el["content"]) is kept
        assert ("R11" in b.flags) is not kept
