"""점역·조판 전용 스레드풀 (2026-08-06, S3).

지키는 것:
  1. 점역이 이벤트 루프를 막지 않는다 — 이게 이 변경의 전부다.
  2. 전용 풀이라 기본 실행기(MinerU·PDF 추출의 `to_thread`)와 자리를 다투지 않는다.
  3. 풀 크기가 config로 조정된다.
  4. 예외가 호출부로 그대로 올라온다(요소 격리 규약이 깨지지 않는다).
  5. 영어 점역 캐시가 순수 함수 캐시로 동작한다(같은 입력 → 같은 출력).

왜 이걸 짜는가 — 점역은 순수 CPU 동기 작업인데 코루틴 안에서 그대로 불렸다.
실측(dev 60쪽) 쪽당 중앙 121ms · p95 2,122ms이고, 동시 4쪽이면 루프가 최대 8.6초 멈춘다.
그동안 LLM 응답도 MinerU 완료도 gRPC 응답도 처리되지 않는다. 눈에 안 보이는 고장이라
테스트로 잡아 둔다.
"""
from __future__ import annotations

import asyncio
import time

import pytest

from app.core import limits


def _burn(ms: int) -> str:
    """CPU를 ms만큼 태우는 가짜 점역(sleep이 아니라 실제 연산 — GIL 조건을 같게)."""
    end = time.perf_counter() + ms / 1000
    n = 0
    while time.perf_counter() < end:
        n += 1
    return f"done:{n > 0}"


class TestLoopNotBlocked:
    def test_점역_중에도_루프가_돈다(self) -> None:
        """전용 풀로 내렸으면 200ms짜리 점역 중에도 심박이 여러 번 뛴다."""
        async def go():
            beats = []

            async def heartbeat():
                try:
                    while True:
                        await asyncio.sleep(0.01)
                        beats.append(time.perf_counter())
                except asyncio.CancelledError:
                    pass

            hb = asyncio.create_task(heartbeat())
            await asyncio.sleep(0.02)                 # 심박 먼저 띄운다
            await limits.run_braille(_burn, 200)
            hb.cancel()
            await asyncio.gather(hb, return_exceptions=True)
            return beats

        beats = asyncio.run(go())
        assert len(beats) >= 10, f"점역 200ms 동안 심박 {len(beats)}회 — 루프가 막혔다"

    def test_직접_부르면_루프가_막힌다(self) -> None:
        """대조군 — 이 테스트가 실패하면 위 테스트가 무의미해진 것이다."""
        async def go():
            beats = []

            async def heartbeat():
                try:
                    while True:
                        await asyncio.sleep(0.01)
                        beats.append(1)
                except asyncio.CancelledError:
                    pass

            hb = asyncio.create_task(heartbeat())
            await asyncio.sleep(0.02)
            _burn(200)                                # 코루틴 안에서 그대로 = 종전 동작
            hb.cancel()
            await asyncio.gather(hb, return_exceptions=True)
            return beats

        beats = asyncio.run(go())
        assert len(beats) <= 4, f"막혀야 하는데 심박 {len(beats)}회"

    def test_여러_페이지_점역이_겹쳐_흐른다(self) -> None:
        """풀 크기 4면 100ms짜리 4건이 400ms가 아니라 대략 100ms대에 끝난다."""
        from app.core.config import config

        old = config.braille_max_concurrent
        config.braille_max_concurrent = 4
        limits._reset_for_tests()
        try:
            async def go():
                t0 = time.perf_counter()
                await asyncio.gather(*[limits.run_braille(_burn, 100) for _ in range(4)])
                return time.perf_counter() - t0

            elapsed = asyncio.run(go())
            # GIL 때문에 완전 병렬은 아니지만 직렬(0.4s)보다는 확실히 빨라야 한다.
            assert elapsed < 0.35, f"겹쳐 흐르지 않는다({elapsed:.3f}s)"
        finally:
            config.braille_max_concurrent = old
            limits._reset_for_tests()


class TestPool:
    def test_기본_실행기와_다른_풀이다(self) -> None:
        """같은 풀을 쓰면 점역이 몰릴 때 MinerU 대기가 CPU 작업 뒤에 줄을 선다."""
        async def go():
            ours = await limits.run_braille(lambda: __import__("threading").current_thread().name)
            theirs = await asyncio.to_thread(
                lambda: __import__("threading").current_thread().name)
            return ours, theirs

        ours, theirs = asyncio.run(go())
        assert ours.startswith("braille"), f"전용 풀이 아니다: {ours}"
        assert not theirs.startswith("braille"), f"기본 실행기가 오염됐다: {theirs}"

    def test_풀_크기가_config를_따른다(self) -> None:
        from app.core.config import config

        old = config.braille_max_concurrent
        config.braille_max_concurrent = 2
        limits._reset_for_tests()
        try:
            assert limits.braille_pool()._max_workers == 2
        finally:
            config.braille_max_concurrent = old
            limits._reset_for_tests()

    def test_예외가_그대로_올라온다(self) -> None:
        """요소 격리(불변규칙 3)는 호출부의 gather가 한다 — 풀이 삼키면 안 된다."""
        def boom():
            raise ValueError("점역 실패")

        async def go():
            await limits.run_braille(boom)

        with pytest.raises(ValueError, match="점역 실패"):
            asyncio.run(go())

    def test_키워드_인자가_전달된다(self) -> None:
        async def go():
            return await limits.run_braille(lambda a, b=0: a + b, 1, b=2)

        assert asyncio.run(go()) == 3


class TestEngCache:
    """영어 점역 캐시 — `_break_offsets`의 O(n²)를 3.1배 줄인 자리."""

    def test_같은_입력은_같은_출력(self) -> None:
        from app.ai.braille import eng_braille

        a = eng_braille.translate("the quick brown fox")
        b = eng_braille.translate("the quick brown fox")
        assert a == b and a != ""

    def test_캐시가_실제로_맞는다(self) -> None:
        from app.ai.braille import eng_braille

        eng_braille.translate.cache_clear()
        for _ in range(50):
            eng_braille.translate("ATP mV pH")
        info = eng_braille.translate.cache_info()
        assert info.hits == 49 and info.misses == 1

    def test_캐시가_값을_안_바꾼다(self) -> None:
        """캐시를 끈 원본과 결과가 같아야 한다 — 순수 함수 전제의 확인."""
        import re

        from app.ai.braille import eng_braille

        raw = eng_braille.translate.__wrapped__
        for s in ["the", "ATP", "mmHg 3", "MP4 Player", "", "a-b", "Hello World"]:
            assert eng_braille.translate(s) == raw(s), s
        assert isinstance(eng_braille._WORD_RE, re.Pattern)
