# -*- coding: utf-8 -*-
"""시각 초안 피커의 **이름과 차례**를 유형별로 못 박는다 (#863, 대표 결재 2026-09-11).

이 축은 CER 로 못 잰다 — 라벨은 피커 표시명이라 점자 셀에 한 글자도 안 들어간다.
그래서 회귀 판정을 **제품 진입점이 실제로 낸 label 수열**로 한다.

    이름   유형 있음(도표·만화)   `흐름도(단순)` `흐름도(기본)` `흐름도(자세히)` `흐름도(줄글)`
           유형 없음(그림·사진·그래프)      `단순`       `기본`       `자세히`       `줄글`
           생략·참조·대안 유형    그대로 (`흐름도 생략` · `그림 참조` · `가계도(상향식)`)
    차례   처리 방식 축   설명 → 생략 → 참조   (gold 전수 12,677건: 75.9% · 14.0% · 10.0%)
           설명 계열 안   기본 → 대안 유형 → 단순 → 자세히 → 줄글

★ 종전에는 `[생략, 설명, 참조]` 였다 — option 번호(1·2·6)를 그대로 화면 차례로 쓴 결과다.
  그래서 **가장 많이 쓰는 안이 둘째, 가장 안 쓰는 안이 첫째**에 서 있었다.
★ 라벨을 또 바꾸려면 여기와 `visual_drafts.AMOUNT_*` 를 같이 고쳐야 한다. 이 시험이
  깨지면 그건 "시험이 낡은 것"이 아니라 **대표 결재를 되돌리고 있다**는 뜻이다.
⚠ `quick-test.sh` 는 `test/unit_test/braille/` 만 본다(이슈 #850) — 이 파일은 그 밖이다.
  시각 초안을 고쳤으면 `pytest test/unit_test` 전체를 돌려야 걸린다.
"""
from __future__ import annotations

import asyncio
from uuid import uuid4

import pytest

from app.ai.llm import visual_drafts as vd
from app.ai.llm.cartoon_opt import CartoonOpt
from app.ai.llm.chart_graph_opt import ChartGraphOpt
from app.ai.llm.diagram_opt import DiagramOpt
from app.ai.llm.image_opt import ImageOpt
from app.schemas.content import ExtractedContent

# 운영 캡션 캐시에서 뽑은 실물이다(재생 결과의 최빈 패턴 대표). 무-LLM(ZERO)으로 돈다.
_CAP_DIAGRAM = (
    "도표: 구조도: 근육 원섬유 마디의 구간 구분\n\n"
    "1. 양쪽 끝에 Z선, 중앙에 M선\n"
    "2. X: Z선에서 Z선까지 전체 길이\n"
    "3. 가는 필라멘트: 양쪽 Z선에서 안쪽으로 뻗음\n"
)
_CAP_IMAGE = "그림: 활동성 정도 막대\n\n위쪽: 활동성 최대\n아래쪽: 활동성 최소"
_CAP_CARTOON = (
    "만화: 학생1과 학생2가 앱 화면을 두고 대화창에서 의견을 나눈다\n"
    "학생1: 독서 여권 앱의 첫 화면을 구성해 봤는데 의견 말해 줘\n"
    "학생2: 독서 축제 기간에 대한 정보가 빠져 있는데 추가해야 할 것 같아\n"
)
_CAP_GRAPH = ("그래프: 꺾은선그래프, 세로축 막전위, 가로축 시간\n\n"
              "ㄱ 자극 지점 표시\n\nㄱ 자극 전: 뾰족한 파형 5회 반복\n\n"
              "ㄱ 자극 후: 뾰족한 파형 6회 반복")


def _labels(cls, caption: str) -> list[str]:
    ext = ExtractedContent(element_id=uuid4(), ocr_confidence=1.0, corrected_text=caption)
    out = asyncio.run(cls()._optimize_one(ext, "ZERO"))
    return [d.label for d in out.drafts]


@pytest.mark.parametrize("cls,caption,expected", [
    # 유형이 있는 자료 — 설명 계열 세 칸이 다 유형을 달고 나온다.
    (DiagramOpt, _CAP_DIAGRAM,
     ["구조도(기본)", "구조도(단순)", "구조도(줄글)", "구조도 생략", "그림 참조"]),
    # 유형이 없는 자료 — 분량 낱말만.
    (ImageOpt, _CAP_IMAGE, ["기본", "단순", "줄글", "그림 생략", "그림 참조"]),
    (ChartGraphOpt, _CAP_GRAPH, ["기본", "단순", "줄글", "그래프 생략", "그림 참조"]),
    # 만화는 줄글 안을 안 낸다 — §5.3.3(1)(2)가 장면 5칸·대사 3칸으로 줄 배치를 못 박아
    # 한 줄 줄글이 조항 위반이 된다.
    (CartoonOpt, _CAP_CARTOON,
     ["만화(기본)", "만화(단순)", "만화 생략", "그림 참조"]),
])
def test_유형별_이름과_차례(cls, caption, expected):
    assert _labels(cls, caption) == expected


def test_기본_안이_언제나_첫째이고_기본_선택이다():
    """gold 최빈(설명 75.9%)이 첫 칸에 서고 처음부터 골라져 있어야 한다."""
    for cls, cap in ((DiagramOpt, _CAP_DIAGRAM), (ImageOpt, _CAP_IMAGE),
                     (ChartGraphOpt, _CAP_GRAPH), (CartoonOpt, _CAP_CARTOON)):
        ext = ExtractedContent(element_id=uuid4(), ocr_confidence=1.0, corrected_text=cap)
        out = asyncio.run(cls()._optimize_one(ext, "ZERO"))
        assert out.selected_idx == 0, (cls.__name__, [d.label for d in out.drafts])
        assert out.drafts[0].option == vd.DESC_OPTION, cls.__name__


def test_생략과_참조는_맨_뒤_두_칸이다():
    """처리 방식 축의 차례는 설명 → 생략 → 참조다(gold 최빈순)."""
    for cls, cap in ((DiagramOpt, _CAP_DIAGRAM), (ImageOpt, _CAP_IMAGE),
                     (ChartGraphOpt, _CAP_GRAPH), (CartoonOpt, _CAP_CARTOON)):
        ext = ExtractedContent(element_id=uuid4(), ocr_confidence=1.0, corrected_text=cap)
        opts = [d.option for d in asyncio.run(cls()._optimize_one(ext, "ZERO")).drafts]
        assert opts[-2:] == [vd.OMIT_OPTION, vd.VOLREF_OPTION], (cls.__name__, opts)


def test_대안_유형_안은_분량_낱말을_안_단다():
    """대안 유형은 '같은 자료를 다른 구조로 읽은 안'이라 분량 축이 아니다.

    기본 바로 뒤에 서고(§3-2 차례), 이름은 유형 그대로다.
    """
    from app.ai.llm.diagram_opt import _family_alt, _skeleton_label
    st = {"mode": "top_down",
          "nodes": [{"text": "할아버지", "children": [{"text": "아버지"}]}],
          "items": [{"text": "나"}, {"text": "아버지"}]}
    assert _skeleton_label("family_tree", st) == "가계도(하향식)"     # 유형 이름 그대로
    assert _family_alt("family_tree", st).label == "가계도(상향식)"   # 대안도 그대로
    assert vd.FLOW_CHAIN_LABEL == "흐름도(화살표)"                    # 관행형도 그대로
    # 기본 안만 분량을 단다.
    assert vd.with_amount("가계도(하향식)", vd.AMOUNT_BASIC) == "가계도(하향식, 기본)"


def test_라벨은_점자_셀로_새지_않는다():
    """이름은 피커 표시명이다 — 본문·점자에 한 글자도 들어가면 안 된다.

    전례가 있다(프롬프트 문구 유출). `기본`·`단순`·`자세히` 는 흔한 낱말이라 새면
    본문에 섞여도 눈에 잘 안 띈다 — 그래서 기계로 잡는다.
    """
    from app.ai.braille.visual_braille import DiagramBraille
    ext = ExtractedContent(element_id=uuid4(), ocr_confidence=1.0,
                           corrected_text=_CAP_DIAGRAM)
    opts = asyncio.run(DiagramOpt().optimize([ext], "ZERO"))
    bo = DiagramBraille().translate(opts)[0]
    cells = "\n".join(bo.braille_lines) + "\n".join(
        ln for d in bo.drafts for ln in (d.braille_lines or []))
    from app.utils.braille_back import decode
    back = decode(cells)
    for word in (vd.AMOUNT_BASIC, vd.AMOUNT_SIMPLE, vd.AMOUNT_DETAIL, vd.AMOUNT_PROSE):
        assert word not in back, f"라벨 '{word}' 가 점자 셀로 샜다: {back[:200]}"
    assert "(" not in opts[0].corrected_text, opts[0].corrected_text
