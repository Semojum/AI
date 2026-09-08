"""본문 OCR 교정 LLM 은 고급 점역 안에서만 돈다 (#770) + 폴백 응답 관문 (#768).

대표 지시(2026-09-08, `docs/DECISIONS.md`): LLM 은 시각자료·MinerU 폴백·고급 점역
셋에서만 돈다. 저화질 스캔(QUALITY 티어)이라는 이유만으로 본문을 다시 쓰지 않는다.

확인할 것 넷:
  1. 스위치 `TEXT_OCR_LLM` 이 **호출 시** 읽힌다(1=종전 · 0=전면 차단 · 기본=고급 점역만).
  2. **기본 경로는 호출 0** — 저화질이어도 원문 그대로. 계수기 `텍스트 call=0`.
  3. **양성 대조** — 고급 점역을 켠 팔은 같은 자리에서 `텍스트 call=1` 을 찍는다.
     (`llm_counter_line()` 은 `start_request()` 밖에서 **언제나** call=0 이라 이 대조가
      없으면 거짓 초록이 뜬다 — 2026-09-08 4-2 회차에서 실제로 떴다.)
  4. **폴백 유출 차단** — 폴백 응답에도 `transform` 과 관문(`guard_llm_text`)이 걸린다.
"""
import asyncio
import uuid

import pytest

from app.ai.llm.text_opt import TextOpt, _text_ocr_llm_on
from app.schemas.content import ExtractedContent


def _ext(text="가나다 라마바"):
    return ExtractedContent(element_id=uuid.uuid4(), corrected_text=text, ocr_confidence=0.30)


class Test스위치:
    """`TEXT_OCR_LLM` — 되돌리는 길(스위치 대장 2026-09-08)."""

    def test_기본은_고급_점역만(self, monkeypatch):
        monkeypatch.delenv("TEXT_OCR_LLM", raising=False)
        assert _text_ocr_llm_on(False) is False
        assert _text_ocr_llm_on(True) is True

    def test_1이면_종전_동작(self, monkeypatch):
        """저화질이면 고급 점역과 무관하게 부르던 종전 동작으로 되돌린다."""
        monkeypatch.setenv("TEXT_OCR_LLM", "1")
        assert _text_ocr_llm_on(False) is True

    def test_0이면_고급_점역에서도_안_부른다(self, monkeypatch):
        monkeypatch.setenv("TEXT_OCR_LLM", "0")
        assert _text_ocr_llm_on(True) is False

    def test_호출_시_읽는다(self, monkeypatch):
        """import 때 굳으면 프로세스 env 로 주는 A/B 가 안 먹는다(원장 0903 두 번 무효)."""
        monkeypatch.delenv("TEXT_OCR_LLM", raising=False)
        assert _text_ocr_llm_on(False) is False
        monkeypatch.setenv("TEXT_OCR_LLM", "1")
        assert _text_ocr_llm_on(False) is True


class Test본문_LLM_호출:
    """저화질(QUALITY) 요소 하나를 두 팔로 돌려 호출 수를 센다."""

    def _run(self, monkeypatch, advanced):
        from app.ai.llm import text_opt
        from app.utils import req_log

        calls = []

        async def _spy(prompt, *, timeout, element_id, kind, **kw):
            calls.append(kind)
            req_log.record_llm(kind, "claude-sonnet-5", 10, 5)
            return "LLM 이 다시 쓴 본문", True

        monkeypatch.setattr(text_opt, "generate_with_retry", _spy)
        req_log.start_request()          # ★ 이게 없으면 계수기가 언제나 call=0 이다
        out = asyncio.run(TextOpt(advanced)._optimize_one(_ext(), "QUALITY"))
        return calls, out, req_log.llm_counter_line()

    def test_기본_경로는_호출_0_이고_원문_그대로(self, monkeypatch):
        monkeypatch.delenv("TEXT_OCR_LLM", raising=False)
        calls, out, line = self._run(monkeypatch, advanced=False)
        assert calls == []
        assert out.corrected_text == "가나다 라마바"
        assert "텍스트 call=" not in line          # 텍스트 몫으로 센 호출이 아예 없다

    def test_고급_점역_팔은_부른다_양성대조(self, monkeypatch):
        monkeypatch.delenv("TEXT_OCR_LLM", raising=False)
        calls, out, line = self._run(monkeypatch, advanced=True)
        assert calls == ["텍스트"]
        assert out.corrected_text == "LLM 이 다시 쓴 본문"
        assert "텍스트 call=1" in line


class Test폴백_유출_차단:
    """#768 — 폴백 응답에도 `transform` 과 관문이 걸린다."""

    def test_transform이_폴백에도_걸린다(self, monkeypatch):
        from app.ai.llm import base_opt

        async def _boom(*a, **kw):
            raise asyncio.TimeoutError

        async def _fb(prompt, *, max_tokens=300, kind="요소"):
            return "```\n$$x$$\n```"

        monkeypatch.setattr(base_opt, "hcxt_optimize", _boom)
        monkeypatch.setattr(base_opt, "fallback_optimize", _fb)
        resp, used_fb = asyncio.run(base_opt.generate_with_retry(
            "p", timeout=1, element_id="e", kind="텍스트",
            transform=lambda t: t.replace("`", "").strip(),
        ))
        assert used_fb is True
        assert resp == "$$x$$"          # 종전에는 코드펜스가 그대로 나갔다

    def test_해설문_폴백은_관문이_걷고_원문이_남는다(self, monkeypatch):
        """모델이 본문 대신 「읽을 수 있는 글자가 없습니다」를 쓰면 그 자리는 원문으로 되돌린다."""
        pytest.importorskip("app.ai.captioning.captioner")
        from app.ai.llm import text_opt

        async def _spy(prompt, *, timeout, element_id, kind, **kw):
            return "이 이미지에는 읽을 수 있는 글자가 없습니다.", True

        monkeypatch.setenv("TEXT_OCR_LLM", "1")
        monkeypatch.setattr(text_opt, "generate_with_retry", _spy)
        out = asyncio.run(TextOpt(False)._optimize_one(_ext(), "QUALITY"))
        assert out.corrected_text == "가나다 라마바"

    def test_transform을_안_주는_파트는_그대로다(self, monkeypatch):
        """시각 초안·표는 `transform` 을 안 넘긴다 — 이 변경이 그쪽 산출을 못 건드린다.

        A/B 가 필요한지의 답이 여기 있다. `generate_with_retry(transform=…)` 를 주는 곳은
        `text_opt`(#770 로 고급 점역 안으로 들어갔다)와 `formula_opt`(#766 로 기본 끔)
        둘뿐이라, 켜져 있는 나머지 kind 의 응답은 종전과 **바이트로 같다**.
        """
        from app.ai.llm import base_opt

        async def _fb(prompt, *, max_tokens=300, kind="요소"):
            return "```\n원문 그대로\n```"

        async def _boom(*a, **kw):
            raise asyncio.TimeoutError

        monkeypatch.setattr(base_opt, "hcxt_optimize", _boom)
        monkeypatch.setattr(base_opt, "fallback_optimize", _fb)
        resp, _ = asyncio.run(base_opt.generate_with_retry(
            "p", timeout=1, element_id="e", kind="시각"))
        assert resp == "```\n원문 그대로\n```"
