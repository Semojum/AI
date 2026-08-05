"""외부 LLM 동시 실행 슬롯 + 분당 상한 (2026-08-06, S2).

지키는 것:
  1. 분당 상한이 실제로 막는다 — 요청 수·입력 토큰·출력 토큰 세 창 각각.
  2. 창이 흐르면 다시 통과한다(영구 차단이 아니다).
  3. 상한 0 = 무제한(끄기 스위치가 산다).
  4. 스레드와 코루틴이 **같은 리미터**를 쓴다 — 계정이 하나이므로.
  5. 창보다 큰 단발 요청이 영원히 굶지 않는다.
  6. `llm_slot()`이 동시 호출 수를 실제로 조인다.

왜 이걸 짜는가 — 상한은 조직 공용 계정을 지키는 안전선이다. 평시엔 발동하지 않으므로
(실측 소비가 상한의 1/250) 운영 로그로는 고장 났는지 알 수 없다. 테스트가 유일한 확인이다.
"""
from __future__ import annotations

import asyncio
import threading
import time

import pytest

from app.core import limits
from app.core.limits import RateLimiter, estimate_tokens


class TestWindow:
    """단일 창 — 상한·복구·무제한."""

    def test_상한까지는_통과(self) -> None:
        rl = RateLimiter(rpm=3, input_tpm=0, output_tpm=0)
        for _ in range(3):
            assert rl._try(0, 0) == 0.0

    def test_상한_넘으면_대기시간을_준다(self) -> None:
        rl = RateLimiter(rpm=2, input_tpm=0, output_tpm=0)
        rl._try(0, 0)
        rl._try(0, 0)
        wait = rl._try(0, 0)
        assert 0 < wait <= 60.0

    def test_창이_흐르면_다시_통과(self) -> None:
        rl = RateLimiter(rpm=2, input_tpm=0, output_tpm=0)
        rl.req.span = 0.05                      # 창을 짧게 줄여 실제로 흐르게 한다
        rl._try(0, 0)
        rl._try(0, 0)
        assert rl._try(0, 0) > 0
        time.sleep(0.06)
        assert rl._try(0, 0) == 0.0

    def test_입력_토큰_창이_따로_막는다(self) -> None:
        rl = RateLimiter(rpm=0, input_tpm=100, output_tpm=0)
        assert rl._try(100, 999_999) == 0.0     # 출력은 무제한이라 안 막힌다
        assert rl._try(1, 0) > 0

    def test_출력_토큰_창이_따로_막는다(self) -> None:
        rl = RateLimiter(rpm=0, input_tpm=0, output_tpm=100)
        assert rl._try(999_999, 100) == 0.0
        assert rl._try(0, 1) > 0

    def test_0이면_무제한(self) -> None:
        rl = RateLimiter(rpm=0, input_tpm=0, output_tpm=0)
        assert not rl.enabled
        for _ in range(1000):
            assert rl._try(10**9, 10**9) == 0.0

    def test_창보다_큰_요청도_결국_통과한다(self) -> None:
        """상한보다 큰 단발 요청을 막아 버리면 그 요소가 영원히 처리되지 않는다."""
        rl = RateLimiter(rpm=0, input_tpm=10, output_tpm=0)
        rl.tin.span = 0.05
        rl._try(10, 0)
        assert rl._try(50, 0) > 0               # 창이 차 있는 동안은 기다린다
        time.sleep(0.06)
        assert rl._try(50, 0) == 0.0            # 비면 통과 — 굶지 않는다


class TestAcquire:
    """실제 대기 경로 — 코루틴·스레드."""

    def test_코루틴이_기다렸다_통과한다(self) -> None:
        rl = RateLimiter(rpm=1, input_tpm=0, output_tpm=0)
        rl.req.span = 0.15

        async def go():
            t0 = time.monotonic()
            await rl.acquire(0, 0)              # 즉시
            await rl.acquire(0, 0)              # 창이 흐를 때까지 대기
            return time.monotonic() - t0

        elapsed = asyncio.run(go())
        assert elapsed >= 0.15, f"대기하지 않았다({elapsed:.3f}s)"
        assert rl.waits == 1

    def test_스레드가_기다렸다_통과한다(self) -> None:
        rl = RateLimiter(rpm=1, input_tpm=0, output_tpm=0)
        rl.req.span = 0.15
        t0 = time.monotonic()
        rl.acquire_sync(0, 0)
        rl.acquire_sync(0, 0)
        assert time.monotonic() - t0 >= 0.15

    def test_스레드와_코루틴이_같은_창을_쓴다(self) -> None:
        """계정이 하나이므로 캡셔닝(스레드)과 opt(asyncio)가 상한을 나눠 써야 한다."""
        rl = RateLimiter(rpm=2, input_tpm=0, output_tpm=0)
        rl.acquire_sync(0, 0)                   # 스레드가 1칸 먹는다

        async def go():
            await rl.acquire(0, 0)              # 코루틴이 2칸째
            return rl._try(0, 0)                # 3칸째는 막혀야 한다

        assert asyncio.run(go()) > 0

    def test_동시_스레드에서_상한을_안_넘는다(self) -> None:
        """락이 없으면 경쟁 상태로 상한을 넘겨 통과한다."""
        rl = RateLimiter(rpm=20, input_tpm=0, output_tpm=0)
        rl.req.span = 30.0
        passed = []
        lock = threading.Lock()

        def worker():
            if rl._try(0, 0) == 0.0:
                with lock:
                    passed.append(1)

        ts = [threading.Thread(target=worker) for _ in range(100)]
        for t in ts:
            t.start()
        for t in ts:
            t.join()
        assert len(passed) == 20, f"상한 20인데 {len(passed)}건 통과"


class TestEstimateTokens:
    def test_텍스트는_문자_수(self) -> None:
        assert estimate_tokens("가나다라") == 4

    def test_이미지는_바이트당_1000분의_1(self) -> None:
        assert estimate_tokens("", image_bytes=1_500_000) == 1500

    def test_빈_입력(self) -> None:
        assert estimate_tokens("") == 0
        assert estimate_tokens(None) == 0


class TestLlmSlot:
    def test_동시_실행_수를_조인다(self) -> None:
        from app.core.config import config

        old = config.llm_max_concurrent
        config.llm_max_concurrent = 3
        limits._reset_for_tests()
        try:
            peak = 0
            cur = 0

            async def one():
                nonlocal peak, cur
                async with limits.llm_slot():
                    cur += 1
                    peak = max(peak, cur)
                    await asyncio.sleep(0.01)
                    cur -= 1

            async def all_of():
                await asyncio.wait_for(
                    asyncio.gather(*[one() for _ in range(20)]), timeout=10)

            asyncio.run(all_of())
            assert peak == 3, f"상한 3인데 동시 {peak}건"
        finally:
            config.llm_max_concurrent = old
            limits._reset_for_tests()


class TestDefaults:
    """기본값 = Anthropic 계정 실측 한도의 절반 (2026-08-06 응답 헤더 측정)."""

    def test_기본값이_계정_한도의_절반(self) -> None:
        from app.core.config import config

        # 실측: RPM 10,000 · 입력 10,000,000/분 · 출력 2,000,000/분 (Scale 티어)
        assert config.llm_rpm == 5_000
        assert config.llm_input_tpm == 5_000_000
        assert config.llm_output_tpm == 1_000_000

    def test_기본_상한은_평시_처리량을_안_막는다(self) -> None:
        """코퍼스 1,462쪽 실측 최악 = 쪽당 22호출 × 동시 4쪽 = 88건 순간.

        이게 분당 상한에 걸리면 상한이 잘못 잡힌 것이다.
        """
        from app.core.config import config

        rl = RateLimiter(config.llm_rpm, config.llm_input_tpm, config.llm_output_tpm)
        for _ in range(88):
            assert rl._try(2_000, 500) == 0.0

    @pytest.mark.parametrize("field", ["llm_rpm", "llm_input_tpm", "llm_output_tpm",
                                       "llm_max_concurrent"])
    def test_환경변수로_조정된다(self, field: str, monkeypatch) -> None:
        from app.core.config import Settings

        monkeypatch.setenv(field.upper(), "7")
        assert getattr(Settings(), field) == 7


class TestWiring:
    """배선 확인 — 상한 코드가 실제 호출 경로에 걸려 있는가.

    상한을 짜 놓고 호출부에 안 걸면 테스트만 통과하고 계정은 그대로 노출된다.
    여기서는 가짜 클라이언트로 `fallback_optimize`를 태워 리미터 창이 움직이는지 본다.
    """

    def test_fallback_optimize가_슬롯과_상한을_지난다(self, monkeypatch) -> None:
        import sys
        import types

        from app.ai.llm import base_opt
        from app.core.config import config

        class _Msg:
            type = "text"
            text = "결과"

        class _Resp:
            content = [_Msg()]
            usage = types.SimpleNamespace(input_tokens=11, output_tokens=7)

        class _Messages:
            async def create(self, **kw):
                return _Resp()

        class _Client:
            def __init__(self, **kw):
                self.messages = _Messages()

        monkeypatch.setitem(sys.modules, "anthropic",
                            types.SimpleNamespace(AsyncAnthropic=_Client))
        monkeypatch.setattr(config, "anthropic_api_key", "sk-test", raising=False)
        monkeypatch.delenv("DISABLE_LLM_FALLBACK", raising=False)
        limits._reset_for_tests()

        out = asyncio.run(base_opt.fallback_optimize("가나다", max_tokens=50, kind="시험"))
        assert out == "결과"

        rl = limits.llm_limiter()
        assert rl.req.used == 1, "요청 창이 안 움직였다 — 상한이 호출 경로에 안 걸렸다"
        assert rl.tin.used == len("가나다"), "입력 토큰 예약이 안 됐다"
        assert rl.tout.used == 50, "출력 토큰 예약이 안 됐다"
        limits._reset_for_tests()

    def test_차단_스위치가_상한보다_먼저_선다(self, monkeypatch) -> None:
        """DISABLE_LLM_FALLBACK=1이면 슬롯·상한을 잡기도 전에 돌아온다(과금 0)."""
        from app.ai.llm import base_opt

        monkeypatch.setenv("DISABLE_LLM_FALLBACK", "1")
        limits._reset_for_tests()
        assert asyncio.run(base_opt.fallback_optimize("가나다", kind="시험")) == ""
        assert limits.llm_limiter().req.used == 0
        limits._reset_for_tests()

    @pytest.mark.parametrize("mod,fn", [
        ("app.ai.captioning.captioner", "_caption_anthropic"),
        ("app.ai.captioning.classifier", "_classify_anthropic"),
        ("app.ai.parser.opus_fallback", "extract"),
    ])
    def test_다른_호출부에도_상한이_걸려_있다(self, mod: str, fn: str) -> None:
        """소스에 리미터 호출이 있는지 확인 — 실호출은 과금되므로 배선만 본다."""
        import importlib
        import inspect

        src = inspect.getsource(getattr(importlib.import_module(mod), fn))
        assert "llm_limiter()" in src, f"{mod}.{fn}에 분당 상한이 없다"
        assert "acquire_sync" in src, f"{mod}.{fn}이 상한을 기다리지 않는다"
