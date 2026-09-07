"""재료 블록(#636)이 **어느 시각 opt 로도** 새지 않는다.

#640 이 `visual_drafts` 와 `cartoon_opt` 두 곳에서 재료를 떼었는데, `build_visual_drafts`
를 안 타는 형제 경로(`diagram_opt` 의 §6.6 골격, `chart_graph_opt`)가 남아 있었다.
실측(재료 켠 캡션 62건): 20건(32.3%) 유출 — 도표 18/20 · 그래프 2/12.

그래서 이 시험은 유형 하나가 아니라 **넷 전부**를 돈다. 경로가 늘면 여기에 줄을 더한다.
"""
from __future__ import annotations

import asyncio
import re
from uuid import uuid4

import pytest

from app.ai.llm.cartoon_opt import CartoonOpt
from app.ai.llm.chart_graph_opt import ChartGraphOpt
from app.ai.llm.diagram_opt import DiagramOpt
from app.ai.llm.image_opt import ImageOpt
from app.schemas.content import ExtractedContent

_MATERIAL = """⟦재료⟧
글자: 갑상샘
글자: 세포 ㉠
요소: 원 모양 입자 5개
관계: 갑상샘 → 입자 → 세포 ㉠
축: 가로축 시간, 세로축 농도
수치: 2020년: 12
순서: 1단계 → 2단계
상황: 안내자가 설명하고 있음.
대사: 왕: 이것이 무엇인가?
없음: 말풍선 꼬리
못읽음: 뒤쪽 안내판 글씨"""

_CAPS = {
    ImageOpt: "그림: 갑상샘에서 분비된 물질이 세포에 작용하는 과정\n갑상샘 → 물질 → 세포 ㉠",
    DiagramOpt: "도표: 흐름도\n갑상샘 → 물질 분비 → 세포 ㉠\n세포 ㉠: 수용체에 결합 없음",
    ChartGraphOpt: "그래프: 막대그래프, 연도별 값\n2020년: 12\n2021년: 34",
    CartoonOpt: "만화: 안내자가 전시물 앞에서 설명하고 있음.\n왕: 이것이 무엇인가?",
}

# 재료 열쇠말이 줄머리에 오면 그건 점역사가 볼 글이 아니라 관측 메모다.
_KEY_HEAD = re.compile(r"^\s*(?:<!\d+칸>|<!/?[^>]*>)*\s*"
                       r"(글자|요소|관계|축|수치|순서|상황|대사|없음|못읽음)\s*[:：]", re.M)


def _drafts(cls, caption: str):
    ext = ExtractedContent(element_id=uuid4(), ocr_confidence=1.0,
                           corrected_text=caption, structure={})
    return asyncio.run(cls().optimize([ext], "ZERO"))[0]


@pytest.mark.parametrize("cls", [ImageOpt, DiagramOpt, ChartGraphOpt, CartoonOpt])
def test_재료가_어느_안에도_안_샌다(cls):
    out = _drafts(cls, _CAPS[cls] + "\n" + _MATERIAL)
    for d in out.drafts:
        assert "⟦재료⟧" not in d.text, (cls.__name__, d.label, d.text)
        assert not _KEY_HEAD.search(d.text), (cls.__name__, d.label, d.text)


@pytest.mark.parametrize("cls", [ImageOpt, DiagramOpt, ChartGraphOpt, CartoonOpt])
def test_재료가_없을_때와_글이_같다(cls):
    """재료를 떼고 나면 스위치가 꺼진 경로와 **글자까지 같아야** 한다."""
    off = _drafts(cls, _CAPS[cls])
    on = _drafts(cls, _CAPS[cls] + "\n" + _MATERIAL)
    if cls is CartoonOpt:
        return          # 만화는 재료를 **쓴다**(상황=주 안·대사=주 밖) — 같을 수 없다
    assert [d.text for d in on.drafts] == [d.text for d in off.drafts], cls.__name__


def test_만화는_재료를_실제로_쓴다():
    out = _drafts(CartoonOpt, "만화: 아무 말\n" + _MATERIAL)
    sel = out.drafts[out.selected_idx].text
    assert "안내자가 설명하고 있음." in sel        # 상황 → 주 안(머리줄)
    assert "왕: 이것이 무엇인가?" in sel           # 대사 → 주 밖
    assert "못읽음" not in sel and "없음" not in sel
