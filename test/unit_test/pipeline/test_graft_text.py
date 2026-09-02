"""고급 점역 — **MinerU 가 기준**이고 LLM 은 글자만 고친다.

고급 점역의 몫은 MinerU 가 한자로 깨뜨리는 글자를 제대로 읽는 것이지 지면 구조를 다시
잡는 것이 아니다. 레이아웃·좌표·읽기순서·유형·캡션 연결은 MinerU 것을 그대로 쓴다 —
그래야 bbox 가 보통 경로와 똑같이 맞는다.

⚠ 종전에는 반대로 했다(LLM 목록 기준 + 좌표만 얹기). 그러면 LLM 이 쪼갠 단위와 MinerU
  레이아웃이 어긋나 FE 하이라이트가 글자와 안 맞았다.
"""
from app.core.pipeline import _graft_text


def test_좌표와_유형은_MinerU_것이_남는다():
    mnr = [{"type": "text", "content": "以⑦） 軸 구-七기가를", "bbox": [10, 10, 200, 20],
            "id": "m1", "order": 0}]
    llm = [{"type": "title", "content": "이것은 축 구조 기가를"}]
    assert _graft_text(mnr, llm) == 1
    assert mnr[0]["content"] == "이것은 축 구조 기가를"   # 글자만 바뀐다
    assert mnr[0]["bbox"] == [10, 10, 200, 20]          # 좌표는 그대로
    assert mnr[0]["type"] == "text" and mnr[0]["id"] == "m1"


def test_요소_개수는_MinerU_를_따른다():
    # LLM 이 둘로 쪼개도 MinerU 가 하나면 하나다 — 레이아웃이 흔들리면 안 된다.
    mnr = [{"type": "text", "content": "가나다라마바사", "bbox": [0, 0, 9, 9]}]
    llm = [{"type": "text", "content": "가나다라마바사"}, {"type": "text", "content": "딴 것"}]
    _graft_text(mnr, llm)
    assert len(mnr) == 1


def test_짝이_없으면_원래_글자를_지킨다():
    mnr = [{"type": "text", "content": "원래 글자다", "bbox": [0, 0, 9, 9]}]
    llm = [{"type": "text", "content": "전혀 다른 내용"}]
    assert _graft_text(mnr, llm) == 0
    assert mnr[0]["content"] == "원래 글자다"


def test_빈_LLM_글자로_덮지_않는다():
    mnr = [{"type": "text", "content": "지켜야 할 본문", "bbox": [0, 0, 9, 9]}]
    llm = [{"type": "text", "content": "   "}]
    _graft_text(mnr, llm)
    assert mnr[0]["content"] == "지켜야 할 본문"


def test_한_LLM_요소를_둘이_나눠_쓰지_않는다():
    mnr = [{"type": "text", "content": "같은 문장이다", "bbox": [0, 0, 9, 9]},
           {"type": "text", "content": "같은 문장이다", "bbox": [0, 20, 9, 29]}]
    llm = [{"type": "text", "content": "같은 문장이다"}]
    assert _graft_text(mnr, llm) == 1
