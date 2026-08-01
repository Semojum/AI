"""HCXT 추론 백엔드 스위치 회귀 — off / vllm / transformers.

- off(기본, 2026-08-02): 로드도 추론도 하지 않고 HcxtDisabled → 호출부가 즉시 폴백.
  ★ 비활성은 "폐기"가 아니라 "비활성"이다. 배선이 남아 있어 백엔드 값만 바꾸면 되살아난다는
  것까지 검증한다(모델 파일·서빙 스크립트 보존은 코드 밖 사항).
- vllm 백엔드: hcxt_optimize가 hcxt_client.vllm_generate를 호출(인프로세스 모델·GPU 락 불필요).
- 반환은 prefill+생성분(각 opt의 _extract가 프리필 제거하도록 transformers 경로와 동일).
- model_manager: vllm이면 14B 인프로세스 로드 생략, get_status는 사용 가능으로 보고.
"""
from __future__ import annotations

import asyncio

import pytest
from unittest.mock import patch

import app.ai.llm.base_opt as base_opt
from app.core.config import Settings, config


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


# ── off 백엔드 (2026-08-02 기본값) ────────────────────────────────────────


def test_default_backend_is_off():
    """기본값이 off — .env 없이 띄우면 HCXT를 건드리지 않는다."""
    assert Settings().hcxt_backend == "off"
    assert Settings().hcxt_enabled is False


def test_off_raises_disabled_without_touching_models(monkeypatch):
    """off는 모델도 vLLM 서버도 만지지 않고 HcxtDisabled를 올린다."""
    monkeypatch.setattr(config, "hcxt_backend", "off")

    async def run():
        from app.utils.req_log import start_request
        start_request()

        async def boom(*a, **kw):                      # 호출되면 실패
            raise AssertionError("off인데 vLLM 클라이언트를 호출했다")

        with patch("app.ai.llm.hcxt_client.vllm_generate", new=boom):
            with pytest.raises(base_opt.HcxtDisabled):
                await base_opt.hcxt_optimize("p", timeout=5.0, kind="테스트")

    asyncio.run(run())


def test_off_falls_back_immediately_without_retries(monkeypatch):
    """off면 전이 예외 재시도 루프를 타지 않고 곧바로 폴백한다(요소마다 헛돌면 안 됨)."""
    monkeypatch.setattr(config, "hcxt_backend", "off")

    async def run():
        from app.utils.req_log import start_request
        start_request()
        calls = {"fallback": 0}

        async def fake_fallback(prompt, *, max_tokens=300, kind="요소"):
            calls["fallback"] += 1
            return "폴백결과"

        monkeypatch.setattr(base_opt, "fallback_optimize", fake_fallback)
        out, used_fallback = await base_opt.generate_with_retry(
            "p", timeout=5.0, element_id="e1", kind="테스트")
        assert out == "폴백결과" and used_fallback is True
        assert calls["fallback"] == 1                  # 재시도 없이 정확히 1회

    asyncio.run(run())


def test_off_load_and_status(monkeypatch):
    """off면 인프로세스 로드를 생략하고 status는 미탑재로 보고한다."""
    monkeypatch.setattr(config, "hcxt_backend", "off")
    from app.core.model_manager import model_manager
    saved = dict(model_manager._gpu1_models)
    try:
        model_manager._gpu1_models = {}
        model_manager._load_hcxt()
        assert model_manager._gpu1_models.get("hcxt") is None
        s = model_manager.get_status()
        assert s["hcxt_backend"] == "off"
        assert s["hcxt_loaded"] is False
    finally:
        model_manager._gpu1_models = saved


def test_backend_typo_is_rejected():
    """오타가 조용히 transformers 경로로 새면 14B가 GPU에 올라간다 → 기동 시점에 막는다."""
    for bad in ("of", "vLLM2", "none", ""):
        with pytest.raises(Exception):
            Settings(hcxt_backend=bad)
    # 되살리기 경로는 살아 있어야 한다(비활성 ≠ 폐기).
    assert Settings(hcxt_backend="vllm").hcxt_enabled is True
    assert Settings(hcxt_backend="VLLM").hcxt_backend == "vllm"     # 대소문자 관대
