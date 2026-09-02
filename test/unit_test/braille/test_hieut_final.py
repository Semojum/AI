"""닫는 큰따옴표 ⠴ 가 앞 음절의 받침으로 먹히던 것(역점역).

`⠴` 는 닫는 큰따옴표이자 **받침의 ㅎ**이라(좋=⠨⠥⠴) 탐욕 매칭이 앞 음절에 붙여 먹었다.
정답 도서 가계도가 통째로 깨졌다 — `남자”` 가 `남잫` 이 된다.
받침 ㅍ(_PIEUP_FINAL)과 같이 **실제로 쓰이는 음절 목록**으로 가른다.
"""
import pytest

from app.utils.braille_back import decode


@pytest.mark.parametrize("cells,expect", [
    ("⠉⠢⠨⠴", "남자”"),      # 가계도 — 실측 135회
    ("⠱⠨⠴", "여자”"),        # 실측 121회
])
def test_닫는_따옴표를_받침으로_먹지_않는다(cells, expect):
    assert decode(cells) == expect


@pytest.mark.parametrize("cells,expect", [
    ("⠨⠥⠴", "좋"),
    ("⠉⠥⠴", "놓"),
])
def test_진짜_받침_ㅎ_음절은_그대로_둔다(cells, expect):
    assert decode(cells) == expect


def test_받침_ㅀ_도_지킨다():
    # 끓 = 받침 ㅀ. ㅎ 이 들어가므로 같은 자리에 걸린다.
    assert "끓는다" in decode("⠠⠈⠮⠴⠉⠵⠊⠲")


def test_ⵁ로_끝나는_기호를_가로채지_않는다():
    # ℃ = ⠴⠙… — 기호표가 먼저다.
    assert "℃" in decode("⠴⠙⠠⠉")
