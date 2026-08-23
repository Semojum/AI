"""없는 그림의 설명을 내보내지 않는 가드 (노션 Review, 2026-08-23).

그림이 없는 자리가 시각 요소로 잡히면 캡셔너가 지면의 글자를 읽어 설명으로 낸다.
실측(1_a4.pdf 문제 본문 영역을 그대로 크롭)한 문자열을 케이스로 쓴다.
"""
import tempfile
from pathlib import Path

import pytest

from app.ai.captioning.captioner import _is_blank_crop, _reject_read_text

# 실측으로 나온 '글자를 읽은' 캡션 둘
READ_TEXT_1 = ("그림: 본문: 28번 문제\n\n$\\overline{AB}=\\overline{CD}=4$, "
               "$\\overline{BC}=\\overline{BD}=2\\sqrt{5}$ 인 사면체 ABCD가 있다.")
READ_TEXT_2 = ("그림: 25. 수열 $\\{a_n\\}$이 모든 자연수 $n$에 대하여\n\n"
               "$\\sqrt{9n^{2}-5}+2n<a_n<5n+1$")

# 정상 캡션 — 수식이 들어 있어도 걸리면 안 된다(전수 측정: LaTeX 필터는 정상의 21.9%를 죽였다)
NORMAL = [
    "개념도: 1 ATP 구조 2 아데닌 3 리보스 4 고에너지 인산 결합 5 P~P~P 6 $+H_2O$ "
    "7 ATP → ADP: 에너지 방출",
    "그림: 뇌 단면 구조도. 대뇌: 단면 상단 대부분을 차지 소뇌: 뇌 뒤쪽 아래에 위치",
    "그래프: 선그래프, 세로축 막전위($mV$), 가로축 시간(초)",
    "만화: 한 사람의 일생을 시간 흐름에 따라 보여줌. 현재: 학생임 8년 후: 대학에서 그림을 그림",
    "도표: 사면체 ABCD와 점 H, G, 구 S를 나타낸 입체도형 그림",
]


@pytest.mark.parametrize("text", [READ_TEXT_1, READ_TEXT_2])
def test_글자를_읽은_캡션은_버린다(text):
    assert _reject_read_text(text) == ""


@pytest.mark.parametrize("text", NORMAL)
def test_정상_캡션은_안_걸린다(text):
    """제일 중요한 케이스다. 수식이 든 정상 캡션을 죽이면 가드가 손해가 된다."""
    assert _reject_read_text(text) == text


def test_빈_입력은_빈_문자열():
    assert _reject_read_text("") == ""
    assert _reject_read_text(None) == ""


def _png(fill):
    from PIL import Image
    f = Path(tempfile.mkdtemp()) / "c.png"
    Image.new("RGB", (80, 60), fill).save(f)
    return str(f)


def test_단색_크롭은_캡션을_안_단다():
    assert _is_blank_crop(_png("white")) is True


def test_내용_있는_크롭은_통과한다():
    from PIL import Image, ImageDraw
    f = Path(tempfile.mkdtemp()) / "c.png"
    im = Image.new("RGB", (80, 60), "white")
    ImageDraw.Draw(im).rectangle([10, 10, 70, 50], fill="black")
    im.save(f)
    assert _is_blank_crop(str(f)) is False


def test_못_읽으면_막지_않는다():
    """판단이 안 서면 캡션을 다는 쪽으로 기운다."""
    assert _is_blank_crop("/does/not/exist.png") is False
