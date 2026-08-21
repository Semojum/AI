"""참조 안에는 **어디를 볼지**가 들어 있어야 한다 (2026-08-21).

「점자 자료 제작 지침」 §1.3.4(3)이 참조를 다루는 유일한 조항이다.

    (3) 교과서 이외의 학습서는 시각 자료만을 별책으로 분권하여 제작할 수 있다. 이 경우
        점역자 주 페이지에서 이런 분권 형식을 안내하고, **시각 자료가 제시된 본문의 해당
        위치마다 별책의 시각 자료 위치를 점역자 주로 알려** 참조하도록 한다.

즉 참조는 위치를 알릴 때 성립한다. "위 그림 참조"처럼 내용도 위치도 없이 끝나면 학생에게
아무것도 남지 않는다.

gold 실측(전 코퍼스 점역자 주 1,265구간·635쪽): `참조` 120건이 **전부 `그림 N-N 참조` 꼴**이고
`앞의 그림`·`위 그림`·`별책` 따위는 0건이다.

이 가드는 지금 품질을 가르지 않는다 — 우리 산출은 이미 전부 식별자를 채운다. 값어치는
**`_number_volume_refs`가 안 돌게 되면 바로 잡는 것**이다. 그 자리는 `_build_response`에서
한 번만 불리므로 조용히 빠지기 쉽다.
"""
from __future__ import annotations

import asyncio
import re
from uuid import uuid4

import pytest

from app.ai.llm.visual_drafts import LABELS, VOLREF_IDX
from app.core.pipeline import _number_volume_refs
from app.schemas.content import ExtractedContent

_HAS_ID = re.compile(r"\d+\s*-\s*\d+")


def _visual_outputs(caps: list[str]):
    from app.ai.llm.chart_graph_opt import ChartGraphOpt
    outs = []
    for c in caps:
        ext = ExtractedContent(element_id=uuid4(), corrected_text=c, ocr_confidence=1.0)
        outs.append(asyncio.run(ChartGraphOpt().optimize([ext], "ZERO"))[0])
    return outs


def _refs(outs):
    return [d.text for o in outs for d in (o.drafts or []) if d.label == LABELS[VOLREF_IDX]]


def test_참조안은_번호를_받는다() -> None:
    outs = _visual_outputs(["그래프: 연도별 인구 추이.", "그림: 세포 구조."])
    before = _refs(outs)
    assert before and not any(_HAS_ID.search(t) for t in before), before   # 채우기 전엔 없다
    _number_volume_refs(outs, 20)
    after = _refs(outs)
    assert len(after) == 2, after
    for t in after:
        assert _HAS_ID.search(t), f"참조에 식별자가 없다(지침 §1.3.4(3)): {t!r}"
    assert "20-1" in after[0] and "20-2" in after[1], after     # 묵자쪽-순번, gold 관행


def test_번호는_쪽마다_1부터_센다() -> None:
    """gold 관행: p0004 → 그림 4-1·4-2 / p0020 → 그림 20-1~20-4."""
    outs = _visual_outputs(["그림: 가.", "그림: 나.", "그림: 다."])
    _number_volume_refs(outs, 4)
    assert [t for t in _refs(outs)] == [
        f"<!주>그림 4-{i} 참조<!/주>" for i in (1, 2, 3)], _refs(outs)


@pytest.mark.parametrize("bad", ["위 그림 참조", "앞의 그림 참조", "그림 참조"])
def test_해소되지_않는_참조는_gold에_없다(bad: str) -> None:
    """이 문구들은 gold 1,265구간에서 0건이다 — 우리도 내면 안 된다."""
    assert not _HAS_ID.search(bad)      # 이 꼴이 통과하면 가드가 무의미하다
