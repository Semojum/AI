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
    # ★ 키 유무는 **캡셔너가 쓰는 그 자리**에서 읽는다(2026-08-27).
    #   종전에는 os.getenv 로 읽었는데, 키는 `.env`로 들어오고 pydantic-settings 는 그것을
    #   `config` 에만 싣지 os.environ 에는 안 싣는다. 그래서 키가 `.env`에만 있는 서버에서는
    #   캡셔닝이 멀쩡히 도는데 /health 는 `caption_key: false` 를 찍었다 — 거짓 경보다.
    #   반대로 캡셔닝이 실제로 죽어 있어도 셸에 변수만 있으면 true 로 찍힌다.
    #   `captioner.backend_status()` 는 `config.anthropic_api_key` 를 본다 — 같은 자리다.
    try:
        from app.ai.captioning.captioner import backend_status
        st = backend_status()
        backend, model, key_present = st["backend"], st["model"], st["key_present"]
    except Exception:                       # noqa: BLE001 — 헬스체크가 죽으면 안 된다
        backend = os.getenv("CAPTION_BACKEND", "anthropic")
        model = os.getenv("CAPTION_MODEL", "claude-sonnet-5")
        key_present = bool(os.getenv("ANTHROPIC_API_KEY") or os.getenv("OPENAI_API_KEY"))
    return {
        "commit": commit or None,
        "caption_prompt_sha": prompt_hash,
        "caption_backend": backend,
        "caption_model": model,
        "caption_key": key_present,
        "caption_cache": caption_cache,
    }


def get_health() -> dict:
    status = model_manager.get_status()
    build = _build_info()
    # ★ 배포가 키를 안 실어 나른 것을 **사람이 보게** 한다(2026-08-27).
    #   배포 절차(RUNBOOK §8-4)는 git pull · protoc · restart 뿐이고 `.env` 는 gitignore 라
    #   손대지 않는다. 그래서 서버에 `.env` 가 없거나 키가 빠져도 배포는 성공으로 끝나고
    #   health 는 "ok" 를 찍는다. 그 상태로 돌면 **모든 시각자료가 '생략'으로 나간다** —
    #   2026-08-26 시연이 그랬다. status 는 BE 계약이라 건드리지 않고 경고만 덧붙인다.
    out = {
        "status": "ok",
        "grpc_port": config.grpc_port,
        "rest_port": config.rest_port,
        "app_env": config.app_env,
        "build": build,
        "models": status,
    }
    if not build.get("caption_key"):
        out["warnings"] = [
            f"{build.get('caption_backend')} 키가 없다 — 이 서버의 시각자료는 설명 없이 "
            f"'생략'으로만 나간다(요소 CAPTION_FAILED · 페이지 NEEDS_REVIEW)."
        ]
    return out


def get_models_status() -> dict:
    return model_manager.get_status()
