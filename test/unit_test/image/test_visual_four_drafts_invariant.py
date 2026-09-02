"""시각자료 대체텍스트 **안 개수 보장** 불변식 (D-02).

계약: 시각 요소(image·cartoon·chart_graph·diagram)는 **언제나 3안**, 표는 **4안**을 낸다.
LLM이 죽든, 형식을 어기든, 캡션이 비든 개수는 고정이다 — 점역사가 고르는 피커가
비거나 줄어들면 안 되기 때문이다.

★ 시각 6→3 (2026-08-20): 규정이 인정하는 처리는 생략·설명·참조 셋뿐이다(§6.1.1).
  '짧은 제목'·'줄글'·'유형만'은 **설명을 쓰는 방식**이 다를 뿐 같은 처리라, 피커에 여섯을
  세워도 점역사는 셋을 헛읽었다. 표 4안(풀어쓰기·격자·전치·선형)은 성격이 달라 그대로다.

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

_EXPECTED = 3          # 재료(캡션·제목·원본 글자)가 있을 때의 시각 3안(생략·설명·참조)
# 재료(캡션·제목·원본 글자)가 하나도 없으면 **생략 한 안만** 낸다.

# ★ 2026-08-12 계약 강화 (대표 지시 "4가지 유형 모두 생략으로 나온다").
#   종전 계약은 "언제나 6안"뿐이라 **여섯 칸이 같은 문구로 채워져도 통과**했다.
#   실측(캡션 없는 조건의 코퍼스 job 10,185요소): 짧은 제목·줄글이 각 41.3%에서
#   "…생략"으로 떨어져, 4안 중 서로 다른 것이 4개인 요소는 10%뿐이었다.
#   개수만 지키는 계약은 목적(설명 방식을 **고르게** 한다)을 못 지킨다.
#   그래서 "개수" 대신 "**서로 다른** 안의 수"를 센다. 재료가 없으면 생략 한 안만 낸다.
#   (3안 체제에서는 셋이 구조적으로 안 겹쳐 접기가 걸릴 일이 없다 — 그래도 계약은 남긴다.)


def _assert_distinct(drafts, *, expect: int | None = None) -> None:
    """안은 서로 달라야 한다. 개수는 재료에 따라 1 또는 3."""
    texts = [d.text for d in drafts]
    assert len(set(texts)) == len(texts), f"같은 문구의 안이 겹친다: {texts}"
    assert drafts, "안이 하나도 없다"
    if expect is not None:
        assert len(drafts) == expect, f"{expect}안이어야 하는데 {len(drafts)}: {texts}"


def _assert_omit_only(drafts) -> None:
    """재료가 없으면 생략 한 안만 (2026-08-12 대표 지시)."""
    assert [d.label for d in drafts] == [vd.LABELS[0]], [d.label for d in drafts]
# 표 렌더 5안 — §3.1.1 (1) 이 정한 세 갈래(정렬 유지·가로 풀어쓰기·번호 체계)에
# 전치와 테두리 변형을 더한 것이다. 번호 체계는 2026-09-02 신설.
_EXPECTED_TABLE = 5


def _ext(conf: float = 1.0):
    return SimpleNamespace(element_id=uuid4(), ocr_confidence=conf)


def _build(**kw) -> list:
    """build_visual_drafts를 동기로 돌려 drafts만 반환."""
    base = dict(routing_tier="ZERO", label="그림", caption="", kind="image")
    base.update(kw)
    drafts, _sel, _ind, _tier, _src = asyncio.run(vd.build_visual_drafts(_ext(), **base))
    return drafts


class TestAlwaysFourWithoutLLM:
    """ZERO 티어(모델 미사용) — 재료가 있으면 입력이 어떻든 3안."""

    def test_캡션도_제목도_없을_때(self) -> None:
        _assert_omit_only(_build())

    def test_캡션만_있을_때(self) -> None:
        _assert_distinct(_build(caption="막대그래프. 연도별 인구."))

    def test_제목만_있을_때(self) -> None:
        _assert_distinct(_build(title="연도별 인구"))

    def test_공백만_있는_캡션(self) -> None:
        _assert_omit_only(_build(caption="   ", title="  "))

    def test_장식용_요소(self) -> None:
        """장식용은 기본 선택이 '생략'으로 바뀔 뿐, 개수는 그대로 3이다."""
        drafts, sel, _ind, _t, _src = asyncio.run(vd.build_visual_drafts(
            _ext(), routing_tier="ZERO", label="그림", caption="장식", kind="image",
            decorative=True))
        _assert_distinct(drafts)
        assert sel == vd.OMIT_IDX

    @pytest.mark.parametrize("kind", ["image", "cartoon", "chart_graph", "diagram"])
    def test_모든_시각_유형(self, kind: str) -> None:
        _assert_distinct(_build(kind=kind, caption="막대그래프. 연도별 인구 추이. 2020년 5,200만 명, 2021년 5,180만 명."))


class TestAlwaysFourWhenLLMMisbehaves:
    """LLM이 죽거나 형식을 어겨도 3안 — 과거 1안 사고의 회귀 가드."""

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
        _assert_distinct(self._with_llm(monkeypatch, ""))

    def test_LLM이_형식을_어김(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """구 사고 재현 — 섹션 표지 없이 한 덩어리로 답하는 경우."""
        _assert_distinct(self._with_llm(monkeypatch, "그냥 줄글로만 답한다 방식 구분 없이"))

    def test_LLM이_한_섹션만(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _assert_distinct(self._with_llm(monkeypatch, "[개조식]\n- 항목 하나"))

    def test_LLM이_예외를_던짐(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _assert_distinct(self._with_llm(monkeypatch, RuntimeError("추론 실패")))

    def test_LLM이_None(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _assert_distinct(self._with_llm(monkeypatch, None))


def test_초안_라벨이_모두_구별된다() -> None:
    """피커에 같은 이름이 두 번 뜨면 점역사가 고를 수 없다."""
    labels = [d.label for d in _build(caption="막대그래프. 연도별 인구 추이. 2020년 5,200만 명, 2021년 5,180만 명.",
                                      struct_outline=[(0, "2020년 5,200만"), (0, "2021년 5,180만")])]
    assert len(set(labels)) == len(labels), labels


def test_재료가_있으면_세_안이_다_다르다() -> None:
    """생략·설명·참조는 서로 다른 **처리**라 재료만 있으면 문구가 겹치지 않는다.

    6안 시절에는 여기에 조건이 둘 붙었다 — 개조식이 항목을 가질 것, 캡션이 한 문장보다
    길 것. 짧은 제목·줄글·개조식이 같은 캡션을 다르게 자르는 안이었기 때문이다.
    세 안은 그 조건과 무관하게 갈린다.
    """
    drafts = _build(
        caption="막대그래프. 연도별 인구 추이를 보여 준다. "
                "2020년 5,200만 명에서 2021년 5,180만 명으로 줄었다.",
        struct_outline=[(0, "2020년 5,200만 명"), (0, "2021년 5,180만 명")])
    _assert_distinct(drafts, expect=_EXPECTED)
    assert [d.label for d in drafts] == [
        vd.LABELS[0], vd.desc_label("이미지"), vd.LABELS[2]]


def test_한_낱말_캡션도_세_안_그대로() -> None:
    """캡션이 한 낱말이어도 접히지 않는다 — 6안 시절 접기가 걸리던 자리다.

    그때는 짧은 제목·개조식·줄글이 '그림: 설명' 한 줄로 수렴해 셋이 겹쳤다.
    지금은 생략·설명·참조가 각자 다른 처리라 한 낱말에서도 셋이 남는다.
    """
    drafts = _build(caption="설명")
    _assert_distinct(drafts, expect=_EXPECTED)
    assert [d.label for d in drafts] == [
        vd.LABELS[0], vd.desc_label("이미지"), vd.LABELS[2]]


def test_표는_렌더_4안_그대로() -> None:
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
    assert len(out[0].drafts) == _EXPECTED_TABLE
    assert len({d.label for d in out[0].drafts}) == _EXPECTED_TABLE


def test_짧은제목은_캡션_첫줄까지만() -> None:
    """1안 '짧은 제목'은 캡션 **첫 줄**로 끊는다 — 둘째 줄 데이터 한가운데서 자르지 않는다.

    캡셔너 프롬프트가 "전체 윤곽을 한 줄로 먼저"(지침 §6.1.4(4))라고 지시하므로 첫 줄이
    곧 제목이다. 종전 구현은 줄 구조를 먼저 뭉개고 45자에서 잘라 val 50건 중 29건이
    '… 전체: 7.6% 1~2세: 6.8%…' 꼴로 끝났다(2026-08-09 실측).
    """
    from app.ai.llm.visual_drafts import _shorten

    cap = "막대그래프, 연령별 비율(%)\n전체: 7.6%\n1~2세: 6.8%\n3~5세: 8.8%"
    assert _shorten(cap) == "막대그래프, 연령별 비율(%)"
    assert _shorten("한 줄뿐인 짧은 캡션") == "한 줄뿐인 짧은 캡션"   # 한 줄이면 종전 그대로
    assert _shorten("") == ""
    assert _shorten("\n둘째 줄만 내용") == "둘째 줄만 내용"          # 첫 줄이 비면 전문 폴백
    long1 = "가" * 80
    # ★ 2026-08-19 계약 변경 — 첫 줄이 길어도 **말줄임표를 남기지 않는다.**
    #   종전에는 45자에서 기계적으로 자르고 …를 붙였는데, 캡셔너가 개조식으로 쓴 설명은
    #   마침표가 없어 전부 그 길로 갔다(캡션 13,393개 중 7,241개 = 54.1%).
    #   점역사에게 문장 중간이 잘린 초안이 나가 말줄임표째로 지워야 했다.
    #   지금은 항목 경계(글머리·쉼표·공백)에서 온전한 조각만 남긴다.
    cut = _shorten(long1 + "\n둘째 줄")
    assert not cut.endswith("…") and len(cut) <= 45, cut
