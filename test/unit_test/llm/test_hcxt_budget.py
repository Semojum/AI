"""HCXT 페이지 예산·요소당 상한 회귀 — 단일 GPU 직렬이 페이지 예산을 독점하지 않도록.

- 예산 소진 시 HCXT 추론을 건너뛰고 즉시 GPT-4o 폴백(HCXT generate 호출 0회).
- 남은 예산이 요소 상한보다 작으면 요소 타임아웃을 남은 예산으로 클램프.
- 타임아웃은 재시도 없이 즉시 폴백(구 3회 재시도 낭비 제거).
"""
from __future__ import annotations

import asyncio
from uuid import uuid4
from unittest.mock import patch

import app.ai.llm.base_opt as base_opt
from app.utils import req_log


def test_budget_exhausted_skips_hcxt():
    """누적 HCXT가 예산에 도달하면 다음 요소는 HCXT 없이 바로 폴백."""
    async def run():
        req_log.start_request()
        req_log.set_hcxt_budget(10.0)
        req_log.record_hcxt("텍스트", 9.0)          # 사용 9s → 남은 1s(< _HCXT_MIN_SLICE)
        calls = {"gen": 0, "fb": 0}

        def fake_gen(*a, **k):
            calls["gen"] += 1
            return "x"

        async def fake_fb(*a, **k):
            calls["fb"] += 1
            return "폴백"

        with patch.object(base_opt, "hcxt_generate_sync", fake_gen), \
             patch.object(base_opt, "fallback_optimize", fake_fb):
            resp, used_fb = await base_opt.generate_with_retry(
                "p", timeout=8.0, element_id=uuid4(), kind="텍스트")
        assert calls["gen"] == 0, "예산 소진인데 HCXT 추론을 호출함"
        assert used_fb and resp == "폴백"

    asyncio.run(run())


def test_timeout_immediate_fallback_no_retry():
    """HCXT 타임아웃이면 재시도 없이 즉시 폴백(HCXT 1회만 시도)."""
    async def run():
        req_log.start_request()          # 예산 미설정 = 무제한
        calls = {"hcxt": 0, "fb": 0}

        async def fake_hcxt(*a, **k):
            calls["hcxt"] += 1
            raise asyncio.TimeoutError()

        async def fake_fb(*a, **k):
            calls["fb"] += 1
            return "폴백"

        with patch.object(base_opt, "hcxt_optimize", fake_hcxt), \
             patch.object(base_opt, "fallback_optimize", fake_fb):
            resp, used_fb = await base_opt.generate_with_retry(
                "p", timeout=8.0, element_id=uuid4(), kind="테스트")
        assert calls["hcxt"] == 1 and calls["fb"] == 1 and used_fb

    asyncio.run(run())


def test_element_timeout_uses_config_default():
    """decide_tier_timeout이 config의 요소당 상한을 기본으로 쓴다(작게)."""
    from app.core.config import config
    tier, t = base_opt.decide_tier_timeout(1.0)          # 고신뢰 → STANDARD
    assert tier == "STANDARD" and t == config.hcxt_element_timeout_seconds
    tier, t = base_opt.decide_tier_timeout(0.0)          # 저신뢰 → QUALITY
    assert tier == "QUALITY" and t == config.hcxt_quality_timeout_seconds
