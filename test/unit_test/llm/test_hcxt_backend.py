"""HCXT 추론 백엔드 스위치 회귀 — config.hcxt_backend="vllm"이면 별도 서버로 라우팅.

- vllm 백엔드: hcxt_optimize가 hcxt_client.vllm_generate를 호출(인프로세스 모델·GPU 락 불필요).
- 반환은 prefill+생성분(각 opt의 _extract가 프리필 제거하도록 transformers 경로와 동일).
- model_manager: vllm이면 14B 인프로세스 로드 생략, get_status는 사용 가능으로 보고.
- 기본(transformers)은 기존 경로 유지 — 다른 테스트가 커버.
"""
from __future__ import annotations

import asyncio

from unittest.mock import patch

import app.ai.llm.base_opt as base_opt
from app.core.config import config


def test_vllm_backend_routes_to_client(monkeypatch):
    monkeypatch.setattr(config, "hcxt_backend", "vllm")

    async def run():
        from app.utils.req_log import start_request
        start_request()
        seen = {}

        async def fake_vllm(prompt, max_new_tokens, prefill):
            seen["prompt"] = prompt
            seen["prefill"] = prefill
            return prefill + "생성됨"      # transformers 경로처럼 prefill+생성분

        # hcxt_optimize 내부에서 지연 import하므로 모듈 속성을 patch.
        with patch("app.ai.llm.hcxt_client.vllm_generate", new=fake_vllm):
            out = await base_opt.hcxt_optimize(
                "캡션 최적화", timeout=10.0, prefill="[개조식]\n", kind="테스트")
        assert out == "[개조식]\n생성됨"
        assert seen["prefill"] == "[개조식]\n" and seen["prompt"] == "캡션 최적화"

    asyncio.run(run())


def test_vllm_backend_needs_no_inprocess_model(monkeypatch):
    """vllm 경로는 model_manager 모델을 만지지 않는다(로드 안 된 상태에서도 동작)."""
    monkeypatch.setattr(config, "hcxt_backend", "vllm")

    async def run():
        from app.utils.req_log import start_request
        start_request()

        async def fake_vllm(prompt, max_new_tokens, prefill):
            return "ok"

        # model_manager.hcxt_model 접근 시 RuntimeError가 나야 정상(로드 안 됨) — 그런데도 성공하면
        # transformers 경로를 안 탔다는 뜻.
        with patch("app.ai.llm.hcxt_client.vllm_generate", new=fake_vllm):
            out = await base_opt.hcxt_optimize("p", timeout=5.0, kind="테스트")
        assert out == "ok"

    asyncio.run(run())


def test_get_status_reports_vllm_available(monkeypatch):
    monkeypatch.setattr(config, "hcxt_backend", "vllm")
    from app.core.model_manager import model_manager
    s = model_manager.get_status()
    assert s["hcxt_backend"] == "vllm"
    assert s["hcxt_loaded"] is True          # 서버 보유 → 사용 가능(다운 시 호출부가 폴백)


def test_load_hcxt_skips_inprocess_in_vllm(monkeypatch):
    monkeypatch.setattr(config, "hcxt_backend", "vllm")
    from app.core.model_manager import model_manager
    saved = dict(model_manager._gpu1_models)
    try:
        model_manager._gpu1_models = {}
        model_manager._load_hcxt()
        assert model_manager._gpu1_models.get("hcxt") is None
        assert model_manager._gpu1_models.get("hcxt_tokenizer") is None
    finally:
        model_manager._gpu1_models = saved
