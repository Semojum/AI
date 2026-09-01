"""같은 입력에 같은 출력 — 파이프라인 결정성 가드 (2026-08-21).

eval이 A/B에서 잡았다: 같은 경계 파일·같은 커밋인데 산출이 갈린 쪽이 있다
(NULL 두 벌에서 1/709, 실험 두 벌에서 34/709). 표 요소의 셀 내용이 한쪽에서
통째로 비었고, 사라진 점자 2줄이 그것이었다.

원인은 아직 미확정이다(재현 실험 예정). 그때까지 **여기서 회귀를 막는다** —
opt 단계를 같은 입력으로 두 번 돌려 산출이 한 글자도 안 달라지는지 본다.

⚠ 잡히는 것과 못 잡는 것을 구분해 둔다.
   잡는다  : 규칙 경로의 순서 의존(set 순회·해시 순서·정렬 동률)
   못 잡는다: 실행 시간·외부 API 응답 차이. 그건 재현 실험이 봐야 한다.
"""
from __future__ import annotations

import asyncio
from uuid import uuid4

import pytest

from app.schemas.content import ExtractedContent

_TABLE_HTML = (
    "<table><tr><td>구분</td><td>(가)</td><td>(나)</td></tr>"
    "<tr><td>내용</td><td>A: 갑만의 입장</td>"
    "<td>B: 갑과 을의 공통 입장C: 을만의 입장</td></tr></table>"
)
_TABLE_PIPE = "구분 | (가) | (나)\n내용 | A: 갑만의 입장 | B: 공통 입장"


def _run(opt, exts, tier="ZERO"):
    return asyncio.run(opt.optimize(exts, tier))


@pytest.mark.parametrize("text", [_TABLE_HTML, _TABLE_PIPE])
def test_표_opt는_두_번_돌려도_같다(text: str) -> None:
    """표 셀 내용이 실행마다 갈리던 자리(EBS-E26-014 p0079 요소 13)."""
    from app.ai.llm.table_opt import TableOpt

    eid = uuid4()
    outs = []
    for _ in range(3):
        ext = ExtractedContent(element_id=eid, corrected_text=text, ocr_confidence=1.0)
        outs.append(_run(TableOpt(), [ext])[0])
    first = outs[0]
    for o in outs[1:]:
        assert o.corrected_text == first.corrected_text, (
            f"표 태그가 실행마다 다르다:\n{first.corrected_text!r}\n{o.corrected_text!r}")
        assert o.render_mode == first.render_mode
        assert [d.text for d in (o.drafts or [])] == [d.text for d in (first.drafts or [])]


def test_텍스트_opt는_두_번_돌려도_같다() -> None:
    from app.ai.llm.text_opt import TextOpt

    eid = uuid4()
    text = "사회·문화 현상은 사람들의 가치나 의지가 반영되어 나타난다. 예를 들어 개인의 자유가 중시된다."
    outs = [_run(TextOpt(), [ExtractedContent(element_id=eid, corrected_text=text,
                                              ocr_confidence=1.0)])[0] for _ in range(3)]
    assert len({o.corrected_text for o in outs}) == 1, [o.corrected_text for o in outs]


def test_시각_초안은_두_번_돌려도_같다() -> None:
    """3안 문구와 선택 인덱스가 흔들리면 점역사 피커가 매번 달라진다."""
    from app.ai.llm.chart_graph_opt import ChartGraphOpt

    eid = uuid4()
    cap = "막대그래프. 연도별 인구 추이. 2020년 5,200만 명, 2021년 5,180만 명."
    outs = [_run(ChartGraphOpt(), [ExtractedContent(element_id=eid, corrected_text=cap,
                                                    ocr_confidence=1.0)])[0] for _ in range(3)]
    first = outs[0]
    for o in outs[1:]:
        assert [d.text for d in o.drafts] == [d.text for d in first.drafts]
        assert o.selected_idx == first.selected_idx


def test_점역은_두_번_돌려도_같다() -> None:
    """translator의 폴백 경로가 set 순회를 쓴다 — 결과 순서에 안 새는지 못박는다."""
    from app.ai.braille.translator import translate_tagged_text

    src = "<!주>그림: 연도별 인구 5,200만 명<!/주> 사회·문화 현상 A와 B"
    outs = {translate_tagged_text(src) for _ in range(5)}
    assert len(outs) == 1, outs


def test_CHAIN_SEQUENTIAL이_같은_결과를_낸다(monkeypatch: pytest.MonkeyPatch) -> None:
    """진단 스위치가 산출을 바꾸면 안 된다 — 순서만 바꾸는 것이지 내용이 아니다."""
    from app.core import pipeline as P

    async def _ok(v):
        return v

    async def _boom():
        raise RuntimeError("체인 실패")

    for seq in ("0", "1"):
        monkeypatch.setenv("CHAIN_SEQUENTIAL", seq)
        got = asyncio.run(P._gather_chains([_ok("a"), _boom(), _ok("c")]))
        assert got[0] == "a" and got[2] == "c", got
        assert isinstance(got[1], Exception), got      # 요소 격리 계약(불변 규칙 3)
