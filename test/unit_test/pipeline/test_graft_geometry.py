"""고급 점역(LLM 추출)에 MinerU 좌표를 이식하는 자리.

종전에는 `advanced_ai=true` 로 돌리면 bbox 가 통째로 (0,0,0,0) 이라 FE 하이라이트가
아예 안 떴다. LLM 은 내용, MinerU 는 기하 — 둘을 합치는 게 `_graft_geometry` 다.
"""
from app.core.pipeline import _graft_geometry


def test_글자는_유사도로_짝짓는다():
    llm = [{"type": "text", "content": "함수 f(x)가 0 이하에서 연속이다."},
           {"type": "text", "content": "따라서 최솟값은 3이다."}]
    mnr = [{"type": "text", "content": "따라서 최솟값은 3이다", "bbox": [10, 90, 200, 100]},
           {"type": "text", "content": "함수 f(x)가 0 이하에서 연속이다", "bbox": [10, 10, 200, 20]}]
    assert _graft_geometry(llm, mnr) == 2
    assert llm[0]["bbox"] == [10, 10, 200, 20]      # 순서가 뒤바뀌어도 내용으로 찾는다
    assert llm[1]["bbox"] == [10, 90, 200, 100]


def test_그림은_유형별_차례로_짝짓는다():
    # 그림은 MinerU 쪽 content 가 비어 유사도가 안 먹는다 — 나온 차례로 잇는다.
    llm = [{"type": "image", "content": "그래프: 가로축은 시간"},
           {"type": "image", "content": "그림: 세포 구조"}]
    mnr = [{"type": "image", "content": "", "bbox": [0, 0, 50, 50]},
           {"type": "image", "content": "", "bbox": [0, 60, 50, 110]}]
    assert _graft_geometry(llm, mnr) == 2
    assert llm[0]["bbox"] == [0, 0, 50, 50]
    assert llm[1]["bbox"] == [0, 60, 50, 110]


def test_짝이_없으면_좌표를_안_붙인다():
    llm = [{"type": "text", "content": "지면에 없는 문장이다."}]
    mnr = [{"type": "text", "content": "전혀 다른 글", "bbox": [1, 2, 3, 4]}]
    assert _graft_geometry(llm, mnr) == 0
    assert "bbox" not in llm[0]


def test_한_짝을_둘이_나눠_갖지_않는다():
    llm = [{"type": "text", "content": "같은 문장이다."},
           {"type": "text", "content": "같은 문장이다."}]
    mnr = [{"type": "text", "content": "같은 문장이다.", "bbox": [1, 2, 3, 4]}]
    assert _graft_geometry(llm, mnr) == 1
    assert llm[0]["bbox"] == [1, 2, 3, 4] and "bbox" not in llm[1]


def test_문단이_합쳐져도_유사도가_대표_조각을_잡는다():
    # LLM 은 "문단 단위로, 중간에 자르지 말 것" 지시라 MinerU 가 줄로 쪼갠 것을 합쳐 읽는다.
    # 조각을 모아 합집합을 만드는 갈래도 재 봤으나 실측이 더 나빴다(docstring 참조) —
    # 유사도가 가장 많이 겹치는 조각을 잡아 주는 것으로 충분하다.
    llm = [{"type": "text", "content": "앞 줄이다 아주 긴 뒷부분이 이어진다"}]
    mnr = [{"type": "text", "content": "앞 줄이다 아주 긴 뒷부분이 이어진다", "bbox": [10, 10, 200, 32]},
           {"type": "text", "content": "상관없는 다른 줄", "bbox": [10, 90, 180, 100]}]
    assert _graft_geometry(llm, mnr) == 1
    assert llm[0]["bbox"] == [10, 10, 200, 32]
