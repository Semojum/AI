"""흐름도 관행형(option 10) 접기 길이 상한 (2026-09-09 대표 결재 3번안, #808).

"접는 것 자체가 option 10 의 존재 이유다(2026-08-26 결재). **길면 나누고 짧으면 접는다.**"

상한 값의 근거는 「점자 자료 제작 지침」 §1.3.3 L323 "점자 페이지는 **가로 32칸**, 세로
26줄을 기본 규격으로 설정한다" 다. 32칸을 넘으면 그 체인은 접힌 것이 아니라 하드랩으로
잘린 덩어리라 관행형의 존재 이유가 사라진다. 같은 지침 §3.1.1(1)① L1730 이 표에서
**같은 판단 절차**를 쓴다 — "표의 한 행을 점역 형식에 맞춰 32칸 안에 배열할 수 있다면
표의 정렬 형태대로 점역한다(아니면 풀어 적는다)".

그 자리에서는 규정형(§6.6.2(4)③④ 상자 한 줄에 하나)이 이미 "나눈 안"으로 나란히 선다.
되돌리는 길은 `FLOW_CHAIN_MAX_CELLS`(0 = 상한 없음). 스위치 대장 등재.
"""
from __future__ import annotations

from app.ai.llm.diagram_opt import _cells, _flow_chain_alt, assemble_flowchart_chain

_SHORT = {"boxes": [{"no": 1, "text": "씨앗"}, {"no": 2, "text": "싹"}, {"no": 3, "text": "꽃"}]}
# 대표가 보신 실물의 원인 — 상자 하나가 47자였다.
_LONG = {"boxes": [
    {"no": 1, "text": "담배모자이크병에 걸린 식물로부터 추출액을 얻었다"},
    {"no": 2, "text": "추출액을 세균여과기에 통과시켰다"},
    {"no": 3, "text": "여과액을 건강한 식물에 발랐다"}]}


def _chain_cells(structure: dict) -> int:
    text, indents = assemble_flowchart_chain(structure)
    return max((_cells(l) for l, i in zip(text.split("\n"), indents)
                if i == 0 and "→" in l), default=0)


def test_한_줄에_접히면_관행형을_낸다():
    assert _chain_cells(_SHORT) <= 32
    assert _flow_chain_alt("flowchart", _SHORT) is not None


def test_한_줄을_넘으면_관행형을_안_낸다():
    assert _chain_cells(_LONG) > 32
    assert _flow_chain_alt("flowchart", _LONG) is None


def test_스위치로_상한을_끌_수_있다(monkeypatch):
    monkeypatch.setenv("FLOW_CHAIN_MAX_CELLS", "0")
    assert _flow_chain_alt("flowchart", _LONG) is not None
