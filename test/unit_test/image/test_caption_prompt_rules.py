"""캡셔닝 요청·프롬프트 불변식 (2026-08-08 QA 16번).

두 가지를 고정한다. 둘 다 실측으로 잡은 것이라, 지우면 조용히 되돌아간다.

1. **사고(thinking)를 꺼서 호출한다.** `claude-sonnet-5`는 `thinking`을 안 주면 적응형
   사고가 기본이고, `max_tokens`는 사고+본문 합계 상한이다. 그래서 복잡한 그림에서
   500토큰을 사고가 다 먹고 **빈 캡션**이 돌아왔다 — 지침 예3-50(순서도) 실측:
   `stop_reason=max_tokens`, `thinking_tokens=499`, text 블록 0개.
   규정 정답 22건 중 3건(14%)이 이 경로였다.

2. **정답에서 뽑은 금지 어휘가 프롬프트에 남아 있다.** 「점자 도서 제작 지침」 3장 2절
   정답 24건에 색·음영어 1건(대사 인용), 장식·도형어 0건, 화면 위치어 0건, 메타서술
   0건이다. 이 넷을 금지하는 문장이 공통 프롬프트에서 빠지면 캡션이 다시 길어진다.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from app.ai.captioning import captioner


class _Block:
    type = "text"
    text = "그림: 확대경"


class TestThinkingDisabled:
    def test_anthropic_호출에_thinking_disabled가_붙는다(self) -> None:
        resp = MagicMock(content=[_Block()], usage=MagicMock(input_tokens=1, output_tokens=1))
        client = MagicMock()
        client.messages.create.return_value = resp
        with patch("anthropic.Anthropic", return_value=client), \
             patch("app.ai.captioning.captioner.llm_limiter", create=True), \
             patch("app.core.limits.llm_limiter"), \
             patch("app.utils.req_log.inc_ext_llm"):
            captioner._caption_anthropic("Zm9v", "image/png", "설명하세요")
        kwargs = client.messages.create.call_args.kwargs
        assert kwargs["thinking"] == {"type": "disabled"}, (
            "사고가 켜지면 max_tokens를 사고가 다 먹고 캡션이 빈 문자열로 돌아온다")


class TestObserveFirst:
    """#665 · 원장 B-08 — 공통 머리가 **관측을 금지하고 해석을 시키면** 안 된다.

    「점자 자료 제작 지침」 §6.1.4 는 (2) 핵심에 초점 · (7) **사실에 대한 설명** ·
    (8) **묘사를 활용**이라 적는다("무엇이 보이는지가 아니다"는 원문에 없다).
    gold 실측도 관측 89.6% · 해석 2.9%(temp/capobs/goldkind.py, 층화표본 130건 374줄).
    """

    def test_보이는_것을_금지하지_않는다(self) -> None:
        assert "무엇이 보이는지가 아닙니다" not in captioner._COMMON, (
            "관측을 금지하면 남는 것은 추론뿐이라 크롭에 없는 것을 지어낸다")

    def test_확인한_사실을_먼저_시킨다(self) -> None:
        assert "확인한 사실" in captioner._COMMON      # §6.1.4(7)
        assert "핵심에 초점" in captioner._COMMON      # §6.1.4(2)


class TestGoldDerivedBans:
    """정답 실측에서 빈도 0(또는 1)이라 금지한 어휘가 공통 프롬프트에 남아 있는가."""

    @pytest.mark.parametrize("needle", ["색·음영", "도형·장식", "화면 위치", "보인다"])
    def test_공통_프롬프트에_금지_문장이_있다(self, needle: str) -> None:
        assert needle in captioner._COMMON

    def test_그래프는_추세를_쓰지_않는다(self) -> None:
        # 정답 그래프 6건(예3-32~3-36·3-45)에 추세 문장 0건.
        assert "추세" in captioner._PROMPTS["chart"] and "붙이지 마세요" in captioner._PROMPTS["chart"]

    def test_조직도는_화살표가_아니라_위계_번호다(self) -> None:
        # 정답 화살표 2/24건은 둘 다 과정 도식(예3-22·3-51). 조직도(예3-46)는 0개.
        assert "위계 번호" in captioner._PROMPTS["diagram"]

    def test_대상이_하나면_이름만_적는다(self) -> None:
        # 예3-26 '퍼킨스 점자 타자기' · 예3-90 '고추장찌개' · 예3-18 '파르테논 신전'.
        assert "이름만" in captioner._PROMPTS["image"]

    def test_만화_대본_형식은_그대로다(self) -> None:
        # 오늘 §5.3.3(3)로 고친 것 — 이번 변경이 되돌리지 않았는지 확인.
        p = captioner._PROMPTS["cartoon"]
        assert "장면 1" in p and "인물명: 대사" in p and "§5.3.3(2)" in p


class TestPromptCaching:
    """프롬프트를 `system`에 두어 캐시가 얹히는가 (2026-08-23, API비용 2번).

    캐시는 접두 일치이고 렌더 순서가 `tools → system → messages`다. 프롬프트가
    사용자 턴에서 이미지 **뒤**에 있으면 접두에 매번 다른 이미지가 끼어 적중률이
    구조적으로 0이 된다 — 캐시를 켰다고 믿는데 한 푼도 안 아끼는 상태다.
    """

    def _call(self):
        resp = MagicMock(content=[_Block()], usage=MagicMock(input_tokens=1, output_tokens=1))
        client = MagicMock()
        client.messages.create.return_value = resp
        with patch("anthropic.Anthropic", return_value=client), \
             patch("app.core.limits.llm_limiter"), \
             patch("app.utils.req_log.record_anthropic"):
            captioner._caption_anthropic("Zm9v", "image/png", "설명하세요")
        return client.messages.create.call_args.kwargs

    def test_프롬프트가_system에_캐시_표시와_함께_간다(self) -> None:
        kwargs = self._call()
        assert kwargs["system"] == [{"type": "text", "text": "설명하세요",
                                     "cache_control": {"type": "ephemeral"}}]

    def test_사용자_턴에는_이미지만_남는다(self) -> None:
        # 이미지 뒤에 텍스트가 남아 있으면 접두가 매번 달라져 캐시가 안 붙는다.
        content = self._call()["messages"][0]["content"]
        assert [b["type"] for b in content] == ["image"]

    @pytest.mark.parametrize("kind", ["image", "cartoon", "diagram", "chart"])
    def test_네_프롬프트_모두_최소_캐시_길이를_넘는다(self, kind: str) -> None:
        # 1,024토큰 미만은 표시를 달아도 조용히 캐시되지 않는다. 한국어는 글자당
        # 약 1토큰이라 글자 수로 하한을 잡아 둔다(실측 1,784~3,041자).
        assert len(captioner._PROMPTS[kind]) > 1200


class TestUsableByTranslator:
    """대표 기준(2026-08-26) — 그림을 이해시키는 것이 아니라 **그대로 쓸 수 있는 문장**.

    "점역사가 읽으면 무슨 그림인지 아는 걸로 끝나면 안 된다. 우리가 제공하는 설명이,
    점역사가 그 시각자료를 점역할 때 쓸 설명과 유사해야 한다."

    이 테스트는 프롬프트가 그 기준을 실제로 담고 있는지만 본다(출력 품질은 눈검사 몫).
    """

    def test_존재_확인형_금지가_들어_있다(self):
        from app.ai.captioning.captioner import _COMMON
        assert "무엇이 있다/나타나 있다/작용한다" in _COMMON
        assert "값" in _COMMON

    def test_대립_방향어를_요구한다(self):
        from app.ai.captioning.captioner import _COMMON
        assert "대립·방향" in _COMMON

    def test_한_사실은_한_번만(self):
        from app.ai.captioning.captioner import _COMMON
        assert "한 사실은 한 번만" in _COMMON

    def test_자체_검증_질문이_있다(self):
        """'그대로 옮겨 쓸 수 있는가' 를 모델이 스스로 묻게 한다."""
        from app.ai.captioning.captioner import _COMMON
        assert "그대로 옮겨 쓸 수" in _COMMON

    def test_도표_템플릿_둘(self):
        from app.ai.captioning.captioner import _PROMPTS as PROMPTS
        d = PROMPTS["diagram"]
        assert "같은 문장 틀로 나란히" in d      # 작용 비교형
        # 2026-09-07 뒤집음 — gold 그림 565건 중 범례 7건(1.2%), 우리 1,208건 중 126건(10.4%).
        # 범례를 옮기는 대신 각 대상을 그 뜻으로 바로 부른다.
        assert "범례 줄을 쓰지 마세요" in d      # 가계도
        assert "범례는 처음 한 번만" not in d

    def test_우리만_쓰는_말을_금지한다(self):
        """gold 가 한 번도 안 쓰는 말은 프롬프트가 막아야 한다(2026-09-07).

        종류어  gold 그림 565건 중 **0건** / 우리 1,208건 중 652건(54.0%)
        범례    gold 7건(1.2%)            / 우리 126건(10.4%)
        추세    gold 그래프 34건 중 0건    / 우리(쪽 추출) 16건 중 11건(68.8%)
        """
        from app.ai.captioning.captioner import _PROMPTS as PROMPTS
        from app.ai.parser.opus_fallback import _PROMPT as PAGE
        assert "종류 이름(모식도" in PROMPTS["diagram"]
        # 쪽 단위 추출도 같은 것을 시켜야 한다 — 한쪽만 고치면 다른 경로가 옛 동작으로 남는다.
        assert "종류 이름(모식도" in PAGE
        assert "대소 관계·추세·해석은 한 글자도" in PAGE
        assert "값의 대소 관계를" not in PAGE

    def test_줄_길이는_gold_그림_실측이다(self):
        """구 값(10/18자)은 규정 정본 42구간에서 온 것이라 도서 gold 그림과 안 맞았다.

        gold 그림 논리줄 1,827줄: 중앙 21자 · 3사분위 33자.
        """
        from app.ai.captioning.captioner import _COMMON
        from app.ai.parser.opus_fallback import _PROMPT as PAGE
        assert "21자(중앙값)~33자(3사분위)" in _COMMON
        assert "21자(중앙값)~33자(3사분위)" in PAGE
        assert "10자(중앙값)~18자" not in _COMMON

    def test_만화_상황문은_있음으로_끝낸다(self):
        """gold 만화 27/27 이 `…있음.` · 우리 92건 중 0건(2026-09-07)."""
        from app.ai.captioning.captioner import _PROMPTS as PROMPTS, _MATERIAL_BLOCK
        assert "'…하고 있음.'" in PROMPTS["cartoon"]
        assert "'…하고 있음.' 으로 끝낸다" in _MATERIAL_BLOCK
        # 말풍선이 없는데 대사를 지어내는 반대쪽 실패도 같이 막는다(실물 file55).
        assert "말풍선이 없거나 안이 비어 있으면" in PROMPTS["cartoon"]

    def test_그래프는_값을_비우지_않는다(self):
        from app.ai.captioning.captioner import _PROMPTS as PROMPTS
        c = PROMPTS["chart"]
        assert "값을 비우지 마세요" in c
        assert "등간격 눈금을 처음부터 끝까지 나열하지는" in c


class TestLabelAndSceneRules:
    """#734 (2026-09-08) — 칸마다 그 칸의 내용, 이름표가 줄머리, 해석과 환각의 경계.

    ★ 과적합 가드가 핵심이다. 대표가 준 모범 답안(테스트_이미지.pdf 8쪽 = 규정 예5-4·5-5·
      6-1·6-7·3-23~3-27)의 **문장이 프롬프트에 들어가면 그 문서만 좋아진다.** 규칙은 넣되
      시험 답은 넣지 않는다 — 여기서 그 답의 낱말이 프롬프트 어디에도 없음을 못 박는다.
    """

    def test_칸마다_이름표와_그_칸의_내용(self):
        from app.ai.captioning.captioner import _COMMON
        assert "이름표: 그 칸에서 누가 무엇을 하는가" in _COMMON
        assert "③보다 이 규칙이 먼저" in _COMMON

    def test_같은_문장_되풀이_금지(self):
        from app.ai.captioning.captioner import _COMMON
        assert "같은 문장을 줄만 바꿔 되풀이하지 마세요" in _COMMON

    def test_해석과_환각의_경계가_예로_박혀_있다(self):
        from app.ai.captioning.captioner import _COMMON
        assert "그 근거가 그림 안에 있는가" in _COMMON
        assert "예3-20" in _COMMON              # 시험 문서 밖 규정 예시
        assert "그림에 없는 것은 쓰지 마세요" in _COMMON   # 환각 방어는 그대로

    def test_도표_번호는_층_표시일_뿐_내용은_이름표(self):
        from app.ai.captioning.captioner import _PROMPTS
        assert "이름 없는 항목만 번호로 부릅니다" in _PROMPTS["diagram"]

    @pytest.mark.parametrize("answer", [
        "학교에 다니고 있다", "화가가 된다", "큐레이터",            # 예3-24 (5쪽)
        "석가 상", "왕관을 씌워", "율령을 반포", "칼을 들고",        # 예6-7 (4쪽)
        "최외각 전자", "그 다음 껍질에 전자 8개", "양성자(+17)",     # 예6-1 (3쪽)
        "탄산 약수", "토론회",                                    # 예5-5·5-4 (1·2쪽)
        "퍼킨스", "계단 옆에", "북반구",                           # 예3-26·3-27·3-25 (7·8·6쪽)
    ])
    def test_시험_문서의_답이_프롬프트에_없다(self, answer):
        from app.ai.captioning.captioner import _COMMON, _PROMPTS, _CONTEXT_BLOCK, _MATERIAL_BLOCK
        for text in [_COMMON, _CONTEXT_BLOCK, _MATERIAL_BLOCK, *_PROMPTS.values()]:
            assert answer not in text, f"시험 답 {answer!r} 이 프롬프트에 있다 — 과적합"


class TestSentenceFormRules:
    """#734 후속(2026-09-08 대표 재대조) — 완결 문장·수치 우선·윤곽 머리줄·유형어 1회."""

    def test_전사_항목은_완결_문장(self):
        from app.ai.captioning.captioner import _COMMON
        assert "완결된 문장으로 쓰고 마침표로 끝냅니다" in _COMMON

    def test_수치가_길이를_이긴다(self):
        from app.ai.captioning.captioner import _COMMON
        assert "수치가 이깁니다" in _COMMON and "층마다 각각" in _COMMON

    def test_머리줄은_항목_압축이_아니다(self):
        from app.ai.captioning.captioner import _COMMON, _PROMPTS
        assert "항목 압축" in _COMMON and "사슬('A … + B … → C')을 첫 줄로" in _PROMPTS["diagram"]

    def test_유형어_두_번은_후처리로_뗀다(self):
        from app.ai.captioning.captioner import _finish
        assert _finish("그림: 개념도. 불교 수용: 절하고 있다.", "diagram").startswith("그림: 불교 수용")
        assert _finish("그림: 구조도, 두 원자가 결합한다.\nH: 전자 1개", "diagram") == "그림: 두 원자가 결합한다.\nH: 전자 1개"
        # 그래프의 종류어와 구분 부호 없는 제목은 그대로
        assert _finish("그래프: 비율 그래프, 갑국", "chart") == "그래프: 비율 그래프, 갑국"
        assert _finish("그림: 개념도 학습 활동", "image") == "그림: 개념도 학습 활동"
