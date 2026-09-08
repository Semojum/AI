"""고급 점역 — **MinerU 가 기준**이고 LLM 은 글자만 고친다.

고급 점역의 몫은 MinerU 가 한자로 깨뜨리는 글자를 제대로 읽는 것이지 지면 구조를 다시
잡는 것이 아니다. 레이아웃·좌표·읽기순서·유형·캡션 연결은 MinerU 것을 그대로 쓴다 —
그래야 bbox 가 보통 경로와 똑같이 맞는다.

⚠ 종전에는 반대로 했다(LLM 목록 기준 + 좌표만 얹기). 그러면 LLM 이 쪼갠 단위와 MinerU
  레이아웃이 어긋나 FE 하이라이트가 글자와 안 맞았다.
"""
from app.core.pipeline import _graft_text


def test_좌표와_유형은_MinerU_것이_남는다():
    # 실물 꼴 — MinerU 가 '또'를 한자 '且'로, '구'를 '求'로 깨뜨린다(p1#75 실측).
    mnr = [{"type": "text", "content": "且, E(X^2)=a+5에서 값을 求하면", "bbox": [10, 10, 200, 20],
            "id": "m1", "order": 0}]
    llm = [{"type": "title", "content": "또, E(X^2)=a+5에서 값을 구하면"}]
    assert _graft_text(mnr, llm) == 1
    assert mnr[0]["content"] == "또, E(X^2)=a+5에서 값을 구하면"   # 글자만 바뀐다
    assert mnr[0]["bbox"] == [10, 10, 200, 20]          # 좌표는 그대로
    assert mnr[0]["type"] == "text" and mnr[0]["id"] == "m1"


def test_안_닮은_짝은_문턱이_막는다(monkeypatch):
    """개악은 유사도 0.75 아래에 몰려 있다 — 본문 삭제·바꿔치기·중복(이식률_0908 §4).

    0.45 로는 이 짝이 붙어 뒤 문장이 통째로 사라졌다. 되돌리는 길은 `GRAFT_SIM_MIN`.
    """
    def run():
        mnr = [{"type": "text", "content": "이 문단은 앞 문장이 있고 뒤에 긴 설명이 더 붙는다",
                "bbox": [0, 0, 9, 9]}]
        return _graft_text(mnr, [{"type": "text", "content": "이 문단은 앞 문장이 있고"}]), mnr

    hit, mnr = run()
    assert hit == 0 and mnr[0]["content"].endswith("더 붙는다"), mnr

    monkeypatch.setenv("GRAFT_SIM_MIN", "0.45")
    hit, mnr = run()
    assert hit == 1, "스위치를 내려도 안 붙으면 되돌리는 길이 없다"


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
