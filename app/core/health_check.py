"""헬스체크 로직 — GET /health 응답 생성."""

from __future__ import annotations

import hashlib
import os
import subprocess
import time
from functools import lru_cache
from pathlib import Path

import torch

from app.core.config import config
from app.core.model_manager import model_manager


# ── 이 서버가 **어느 판인가** (2026-08-26) ────────────────────────────────────
# 오늘 하루에 네 번, "우리 판에서는 되는데 서버에서는 안 된다"를 판이 다른 줄 모르고 팠다.
# 서버가 어느 커밋·어느 프롬프트로 도는지 밖에서 볼 길이 없었기 때문이다.
# ⚠ 키 **값**은 절대 싣지 않는다. 있음/없음만 싣는다.
@lru_cache(maxsize=1)
def _build_info() -> dict:
    try:
        from app.ai.captioning.captioner import _COMMON, _PROMPTS
        blob = _COMMON + "".join(f"{k}{v}" for k, v in sorted(_PROMPTS.items()))
        prompt_hash = hashlib.sha256(blob.encode()).hexdigest()[:12]
    except Exception:                       # noqa: BLE001 — 헬스체크가 죽으면 안 된다
        prompt_hash = None
    commit = os.getenv("GIT_COMMIT") or ""
    if not commit:
        try:                                # 배포본은 .git 이 없을 수 있다 — 그때는 빈 값
            commit = subprocess.run(
                ["git", "rev-parse", "--short", "HEAD"], capture_output=True,
                text=True, timeout=2, cwd=Path(__file__).resolve().parents[2],
            ).stdout.strip()
        except Exception:                   # noqa: BLE001
            commit = ""
    cache_dir = os.getenv("CAPTION_CACHE_DIR")
    if cache_dir and Path(cache_dir).is_dir():
        caption_cache = {"enabled": True, "entries": len(list(Path(cache_dir).glob("*.txt")))}
    else:
        caption_cache = {"enabled": False, "entries": 0}
    return {
        "commit": commit or None,
        "caption_prompt_sha": prompt_hash,
        "caption_backend": os.getenv("CAPTION_BACKEND", "anthropic"),
        "caption_model": os.getenv("CAPTION_MODEL", "claude-sonnet-5"),
        "caption_key": bool(os.getenv("ANTHROPIC_API_KEY") or os.getenv("OPENAI_API_KEY")),
        "caption_cache": caption_cache,
    }


def get_health() -> dict:
    status = model_manager.get_status()
    return {
        "status": "ok",
        "grpc_port": config.grpc_port,
        "rest_port": config.rest_port,
        "app_env": config.app_env,
        "build": _build_info(),
        "models": status,
    }


def get_models_status() -> dict:
    return model_manager.get_status()
