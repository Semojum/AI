"""자원별 동시 실행 슬롯 — app/core/limits.py.

페이지 상한 하나가 모든 단계를 막던 구조를 자원별로 나눴다. 회귀로 고정할 것:
  1. 슬롯 크기가 config를 따른다(값을 바꾸면 따라온다).
  2. 슬롯이 실제로 동시 실행을 막는다.
  3. ★ 추출 타임아웃은 **슬롯을 잡은 뒤부터** 잰다 — 대기를 타임아웃에 넣으면
     줄이 길어질수록 정상 페이지가 '느린 페이지'로 오인돼 끊긴다.
"""
from __future__ import annotations

import asyncio

import pytest

from app.ai.parser import mineru_service
from app.core import limits
from app.core.config import config


@pytest.fixture(autouse=True)
def _reset():
    limits._reset_for_tests()
    yield
    limits._reset_for_tests()


def test_mineru_슬롯_크기는_config를_따른다(monkeypatch):
    """vLLM 엔진에서는 config 값이 그대로 슬롯 크기가 된다.

    ★ 2026-08-26 — 크기를 `mineru_service.concurrency()`가 정한다. 그 함수는 엔진이
      vLLM이 아니면 1로 조이므로(스레드 레이스), 이 테스트는 엔진을 vLLM으로 고정해야
      '설정을 따른다'는 성질만 본다. 조이는 쪽은 아래 테스트가 본다.
    """
    monkeypatch.setattr(config, "mineru_max_concurrent", 3)
    monkeypatch.setattr(mineru_service, "_engine_is_vllm", lambda: True)

    async def run():
        return limits.mineru_slot()._value

    assert asyncio.run(run()) == 3


def test_vLLM이_아니면_mineru_슬롯은_1이다(monkeypatch):
    """transformers 엔진에서 동시 2를 던지면 MinerU가 rope_deltas 레이스로 터진다.

    실측(2026-08-26, 로그 2,171쪽): 텍스트레이어 폴백 142쪽 중 102쪽이 그 에러였다.
    폴백 쪽은 표·그림 구조를 잃으므로 설정값보다 안전이 먼저다.
    """
    monkeypatch.setattr(config, "mineru_max_concurrent", 4)
    monkeypatch.setattr(mineru_service, "_engine_is_vllm", lambda: False)

    async def run():
        return limits.mineru_slot()._value

    assert asyncio.run(run()) == 1


def test_caption_슬롯_크기는_config를_따른다(monkeypatch):
    monkeypatch.setattr(config, "caption_max_concurrent", 5)
    assert limits.caption_slot()._value == 5


def test_같은_루프에서는_같은_슬롯을_공유한다():
    async def run():
        return limits.mineru_slot() is limits.mineru_slot()

    assert asyncio.run(run()) is True


def test_슬롯이_동시_실행을_막는다(monkeypatch):
    """크기 1이면 두 작업이 겹치지 않는다 — 겹치면 GPU 추출 서버가 과부하된다."""
    monkeypatch.setattr(config, "mineru_max_concurrent", 1)
    overlap = {"max": 0, "cur": 0}

    async def worker():
        async with limits.mineru_slot():
            overlap["cur"] += 1
            overlap["max"] = max(overlap["max"], overlap["cur"])
            await asyncio.sleep(0.01)
            overlap["cur"] -= 1

    async def run():
        await asyncio.gather(*[worker() for _ in range(4)])

    asyncio.run(run())
    assert overlap["max"] == 1


def test_추출_타임아웃은_슬롯_획득_후에_시작한다(monkeypatch, tmp_path):
    """대기 시간이 추출 상한을 갉아먹으면 안 된다(상한 = 비정상 탐지기).

    mineru 슬롯을 1로 두고 두 페이지를 동시에 넣는다. 뒤 페이지는 앞 페이지가
    끝날 때까지 기다리는데, 그 대기가 subprocess에 넘기는 timeout 값에서 깎이면 안 된다.
    """
    monkeypatch.setattr(config, "mineru_max_concurrent", 1)
    monkeypatch.setattr(config, "mineru_timeout_seconds", 60.0)
    seen: list[float] = []

    def fake_run(path, page_no, job_id, method, timeout=None):
        seen.append(timeout)
        import time
        time.sleep(0.05)                       # 슬롯을 붙잡고 있는 동안
        return []

    def fake_build(merged, job_id, page_no, method):
        return {"elements": [], "meta": {}}

    import app.core.pipeline as P
    from app.schemas.layout import DocumentMeta
    from app.schemas.task import PageTask

    monkeypatch.setattr("app.ai.parser.mineru_runner.run", fake_run, raising=False)
    monkeypatch.setattr("app.ai.builder.result_builder.build", fake_build, raising=False)

    task = PageTask(job_id="j", page_no=1, total_pages=1, pdf_data=b"%PDF-1.4\n",
                    mode="c", source_text="")
    meta = DocumentMeta(pdf_confidence=0.0, routing_tier="STANDARD", scan_only=True)

    async def run():
        await asyncio.gather(P._extract_via_models(task, meta),
                             P._extract_via_models(task, meta))

    asyncio.run(run())
    # 둘 다 온전한 60초를 받아야 한다 — 뒤 페이지가 대기했다고 깎이면 안 된다.
    assert seen == [60.0, 60.0], seen
