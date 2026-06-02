"""HCLOVA X 추론 직렬화 락 단위 테스트 (#1 동시성)."""
import asyncio

from app.ai.llm.inference_lock import hcxt_lock


class TestInferenceLock:
    def test_동시추론_직렬화(self):
        # 5개 코루틴이 동시에 락을 잡아도 임계구역 동시 진입은 최대 1
        state = {"cur": 0, "max": 0}

        async def worker():
            async with hcxt_lock():
                state["cur"] += 1
                state["max"] = max(state["max"], state["cur"])
                await asyncio.sleep(0.01)
                state["cur"] -= 1

        async def run():
            await asyncio.gather(*[worker() for _ in range(5)])

        asyncio.run(run())
        assert state["max"] == 1, f"동시 진입 {state['max']} (기대 1)"

    def test_같은_루프_같은_락(self):
        async def two():
            return hcxt_lock() is hcxt_lock()
        assert asyncio.run(two()) is True

    def test_다른_루프_별도_락_오류없음(self):
        # asyncio.run 반복(루프 교체)에서도 "다른 루프 Future" 오류 없이 동작
        async def use():
            async with hcxt_lock():
                return True
        assert asyncio.run(use()) and asyncio.run(use())
