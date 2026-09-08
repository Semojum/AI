"""본문을 LLM 이 다시 쓰는 자리는 **없다** (#788) + 폴백 유출 차단은 남는다 (#768).

대표 결정 2026-09-08 「고급 점역의 정의」: 고급 점역 = 어려운 지면을 LLM 이 **직접 읽는다**.
그것뿐이다. 어려운 지면은 추출에서 LLM 이 읽으므로 뒤에서 본문을 고칠 자리가 없다.
`5a1ce49` 가 저화질 스캔의 본문 교정을 고급 점역 안으로 옮겼는데, 이 정의로는 거기 있을
자리가 아니라 **없앴다**(스위치 `TEXT_OCR_LLM` 도 같이).

확인할 것 셋:
  1. **어느 티어에서도 본문 LLM 호출 0.** QUALITY·저신뢰여도 추출 원문 그대로.
     ★ 계수기 양성 대조를 같이 둔다 — `llm_counter_line()` 은 `start_request()` 밖에서
       **언제나** call=0 이라, 대조가 없으면 거짓 초록이 뜬다(2026-09-08 실제로 떴다).
  2. 스위치도 되살아나지 않는다 — `TEXT_OCR_LLM=1` 을 줘도 안 부른다.
  3. **폴백 유출 차단(#768)은 그대로다.** `transform` 이 폴백 응답에도 걸린다 —
     운영은 `hcxt_backend='off'` 라 모든 호출이 폴백이고, 안 걸리면 프리필 스캐폴드·
     코드펜스가 요소 필드로 그대로 들어간다. 이건 다른 kind 도 지키는 뿌리 수정이라 남는다.
"""
import asyncio
import uuid

from app.ai.llm.text_opt import TextOpt
from app.schemas.content import ExtractedContent


def _ext(text="가나다 라마바"):
    return ExtractedContent(element_id=uuid.uuid4(), corrected_text=text, ocr_confidence=0.30)


class Test본문에_LLM을_안_부른다:
    """저화질(QUALITY) 저신뢰 요소 — 종전에 LLM 이 걸리던 바로 그 자리다."""

    def _run(self, monkeypatch, tier, env=None):
        from app.ai.llm import text_opt
        from app.utils import req_log

        calls = []

        async def _spy(prompt, *, timeout, element_id, kind, **kw):
            calls.append(kind)
            req_log.record_llm(kind, "claude-sonnet-5", 10, 5)
            return "LLM 이 다시 쓴 본문", True

        # 자리가 없어졌으니 이름도 없다. 남아 있으면 이 patch 가 살아나 호출을 잡는다.
        monkeypatch.setattr(text_opt, "generate_with_retry", _spy, raising=False)
        if env is not None:
            monkeypatch.setenv("TEXT_OCR_LLM", env)
        req_log.start_request()          # ★ 이게 없으면 계수기가 언제나 call=0 이다
        out = asyncio.run(TextOpt()._optimize_one(_ext(), tier))
        return calls, out, req_log.llm_counter_line()

    def test_QUALITY_저신뢰도_원문_그대로(self, monkeypatch):
        monkeypatch.delenv("TEXT_OCR_LLM", raising=False)
        calls, out, line = self._run(monkeypatch, "QUALITY")
        assert calls == []
        assert out.corrected_text == "가나다 라마바"
        assert "텍스트 call=" not in line
        # 종전 무-LLM 갈래 그대로 — QUALITY 는 STANDARD 로 나간다.
        assert out.routing_tier == "STANDARD"

    def test_스위치로도_안_되살아난다(self, monkeypatch):
        """`TEXT_OCR_LLM=1` 은 없어진 스위치다. 줘도 아무 일도 안 일어난다."""
        calls, out, _ = self._run(monkeypatch, "QUALITY", env="1")
        assert calls == [] and out.corrected_text == "가나다 라마바"

    def test_스위치가_코드에서_사라졌다(self):
        import inspect

        from app.ai.llm import text_opt
        assert "TEXT_OCR_LLM" not in inspect.getsource(text_opt)
        assert not hasattr(text_opt, "_text_ocr_llm_on")


class Test폴백_유출_차단은_남는다:
    """#768 — `transform` 이 폴백 응답에도 걸린다. 다른 kind 도 이걸로 지킨다."""

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

    def test_transform을_안_주는_파트는_그대로다(self, monkeypatch):
        """시각 초안·표는 `transform` 을 안 넘긴다 — 이 변경이 그쪽 산출을 못 건드린다."""
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
