"""시각자료 대체텍스트 **4안 보장** 불변식 (D-02).

계약: 시각 요소(image·cartoon·chart_graph·diagram·table)는 **언제나 4안**을 낸다.
LLM이 죽든, 형식을 어기든, 캡션이 비든 개수는 4로 고정이다 — 점역사가 고르는 피커가
비거나 줄어들면 안 되기 때문이다.

배경(2026-07-28): BE가 "대체 텍스트가 1개만 온다"고 보고했다. 조사 결과 **AI 출력은 정상**
(코퍼스 실측 image 4·table 4)이고, 원인은 **BE 스텁이 5월 협의본 proto로 생성돼
`TextElement.drafts`(15) 필드 자체를 모르는 것**이었다(protobuf는 모르는 필드를 조용히 버린다).
그래도 이 불변식이 코드로 지켜지는지는 별개 문제라 여기서 못박는다.

과거 실제 사고: 구 3안 시절 HCLOVA X가 `[방식N]` 포맷을 안 지켜 1안만 생성됐다
(메모리 `stage5-backlog-visual-3draft`). 2026-07-05 `79b4fb7`이 캡션 폴백으로 해소했고,
이 테스트가 그 회귀를 막는다.
"""
from __future__ import annotations

import asyncio
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.ai.llm import visual_drafts as vd

_EXPECTED = 4


def _ext(conf: float = 1.0):
    return SimpleNamespace(element_id=uuid4(), ocr_confidence=conf)


def _build(**kw) -> list:
    """build_visual_drafts를 동기로 돌려 drafts만 반환."""
    base = dict(routing_tier="ZERO", label="그림", caption="", kind="image")
    base.update(kw)
    drafts, _sel, _ind, _tier = asyncio.run(vd.build_visual_drafts(_ext(), **base))
    return drafts


class TestAlwaysFourWithoutLLM:
    """ZERO 티어(모델 미사용) — 입력이 어떻든 4안."""

    def test_캡션도_제목도_없을_때(self) -> None:
        assert len(_build()) == _EXPECTED

    def test_캡션만_있을_때(self) -> None:
        assert len(_build(caption="막대그래프. 연도별 인구.")) == _EXPECTED

    def test_제목만_있을_때(self) -> None:
        assert len(_build(title="연도별 인구")) == _EXPECTED

    def test_공백만_있는_캡션(self) -> None:
        assert len(_build(caption="   ", title="  ")) == _EXPECTED

    def test_장식용_요소(self) -> None:
        """장식용은 기본 선택이 '생략'으로 바뀔 뿐, 개수는 그대로 4다."""
        drafts, sel, _ind, _t = asyncio.run(vd.build_visual_drafts(
            _ext(), routing_tier="ZERO", label="그림", caption="장식", kind="image",
            decorative=True))
        assert len(drafts) == _EXPECTED
        assert sel == vd.OMIT_IDX

    @pytest.mark.parametrize("kind", ["image", "cartoon", "chart_graph", "diagram"])
    def test_모든_시각_유형(self, kind: str) -> None:
        assert len(_build(kind=kind, caption="설명")) == _EXPECTED


class TestAlwaysFourWhenLLMMisbehaves:
    """LLM이 죽거나 형식을 어겨도 4안 — 과거 1안 사고의 회귀 가드."""

    def _with_llm(self, monkeypatch: pytest.MonkeyPatch, reply):
        """LLM 응답을 주입한다. 실제 심볼은 `generate_with_retry`(모듈 네임스페이스에 import돼 있다)."""
        async def _fake(*_a, **_kw):
            if isinstance(reply, Exception):
                raise reply
            return reply, False          # (응답, 폴백 사용 여부)
        monkeypatch.setattr(vd, "generate_with_retry", _fake)
        # 비ZERO + seed 있음 → LLM 경로 진입
        return _build(routing_tier="STANDARD", caption="원본 캡션 문장.")

    def test_LLM이_빈_문자열(self, monkeypatch: pytest.MonkeyPatch) -> None:
        assert len(self._with_llm(monkeypatch, "")) == _EXPECTED

    def test_LLM이_형식을_어김(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """구 사고 재현 — 섹션 표지 없이 한 덩어리로 답하는 경우."""
        assert len(self._with_llm(monkeypatch, "그냥 줄글로만 답한다 방식 구분 없이")) == _EXPECTED

    def test_LLM이_한_섹션만(self, monkeypatch: pytest.MonkeyPatch) -> None:
        assert len(self._with_llm(monkeypatch, "[개조식]\n- 항목 하나")) == _EXPECTED

    def test_LLM이_예외를_던짐(self, monkeypatch: pytest.MonkeyPatch) -> None:
        assert len(self._with_llm(monkeypatch, RuntimeError("추론 실패"))) == _EXPECTED

    def test_LLM이_None(self, monkeypatch: pytest.MonkeyPatch) -> None:
        assert len(self._with_llm(monkeypatch, None)) == _EXPECTED


def test_초안_라벨이_네_개_모두_구별된다() -> None:
    """피커에 같은 이름이 두 번 뜨면 점역사가 고를 수 없다."""
    labels = [d.label for d in _build(caption="설명")]
    assert len(labels) == _EXPECTED
    assert len(set(labels)) == _EXPECTED, labels


def test_표는_렌더_4안() -> None:
    """표는 visual_drafts가 아니라 table_braille이 4안(풀어쓰기·격자·전치·선형)을 만든다."""
    from app.ai.braille.table_braille import TableBraille
    from app.schemas.content import LLMOutput

    opt = LLMOutput(
        element_id=uuid4(),
        corrected_text="<!표><!행><!칸>이름<!칸>값<!/행><!행><!칸>가<!칸>1<!/행><!/표>",
        render_mode="unfold", routing_tier="ZERO", processing_time_ms=0,
    )
    out = TableBraille().translate([opt])
    assert len(out) == 1
    assert len(out[0].drafts) == _EXPECTED
    assert len({d.label for d in out[0].drafts}) == _EXPECTED
