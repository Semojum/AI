"""헬스체크 로직 — GET /health 응답 생성."""

from __future__ import annotations

import hashlib
import importlib
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


# ── 이 **요청**이 어느 판이었나 (2026-09-08, 재구조화 0-c) ────────────────────
# 점역사 피드백은 며칠 뒤에 온다. 그때 "어느 커밋·어느 프롬프트에 대한 말인가"를 되짚을
# 자리가 요청 로그밖에 없다. `/health` 는 **지금 이 순간** 값이라 지난 요청은 못 되짚는다.
# ⚠ 프롬프트 본문은 절대 싣지 않는다. 12자 해시만 싣는다.
_PROMPT_SOURCES = (
    ("caption", "app.ai.captioning.captioner"),
    ("visual", "app.ai.llm.visual_drafts"),
    ("opus", "app.ai.parser.opus_fallback"),
    ("text", "app.ai.llm.text_opt"),
    ("formula", "app.ai.llm.formula_opt"),
    ("table", "app.ai.llm.table_opt"),
)


def _module_prompt_bytes(name: str) -> bytes:
    """한 모듈의 프롬프트 상수들을 이어 붙인 바이트. 못 읽으면 `b"?"`."""
    try:
        mod = importlib.import_module(name)
    except Exception:                       # noqa: BLE001 — 로그 한 줄이 요청을 죽이면 안 된다
        return b"?"
    out = bytearray()
    for attr in sorted(dir(mod)):
        if "PROMPT" in attr or attr == "_COMMON":
            out += f"{attr}={getattr(mod, attr, '')!r}".encode()
    return bytes(out)


@lru_cache(maxsize=1)
def prompt_sha_by_kind() -> dict:
    """kind → 프롬프트 12자 해시. 판 번호 지문 게이트(3-c)가 이 값을 본다."""
    return {label: hashlib.sha256(_module_prompt_bytes(name)).hexdigest()[:12]
            for label, name in _PROMPT_SOURCES}


@lru_cache(maxsize=1)
def prompt_sha() -> str:
    """여섯 모듈의 프롬프트 상수를 한 해시로. 하나라도 바뀌면 값이 바뀐다.

    `_build_info()["caption_prompt_sha"]` 는 캡셔너만 본다 — 그건 그대로 두고
    (배포 확인이 그 값을 쓴다), 요청 로그용으로 여섯 자리를 합친 값을 따로 낸다.
    """
    h = hashlib.sha256()
    for label, name in _PROMPT_SOURCES:
        h.update(label.encode())
        h.update(_module_prompt_bytes(name))
    return h.hexdigest()[:12]


def prompt_ver_drift() -> list:
    """★ 지문 게이트(3-c). 문안이 바뀌었는데 판 번호를 안 올린 kind 목록.

    판 번호 키는 "문안이 바뀌면 사람이 번호를 올린다" 는 규율에 기댄다. 규율만 두면
    잊는다 — 잊으면 **옛 캡션이 새 관측 규칙인 척** 그대로 나온다. 여기서 기계가 센다.
    번호를 올릴 때 `llm_cache.PROMPT_SHA` 의 값도 같이 새 값으로 적는다.
    """
    live = prompt_sha_by_kind()
    from app.utils.llm_cache import PROMPT_SHA
    return sorted(k for k, want in PROMPT_SHA.items()
                  if k in live and live[k] != want)


@lru_cache(maxsize=1)
def build_stamp() -> str:
    """요청 로그 한 줄에 싣는 판 지문 — `commit=… prompts=…`."""
    return f"commit={_build_info().get('commit') or '?'} prompts={prompt_sha()}"


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
    drift = prompt_ver_drift()
    if drift:
        out.setdefault("warnings", []).append(
            f"프롬프트 문안이 바뀌었는데 판 번호를 안 올렸다: {', '.join(drift)} — "
            f"`llm_cache.PROMPT_VER` 를 올리고 `PROMPT_SHA` 를 새 값으로 적어라. "
            f"이대로 두면 옛 캡션이 새 관측 규칙인 척 캐시에서 그대로 나온다."
        )
    if not build.get("caption_key"):
        out.setdefault("warnings", []).append(
            f"{build.get('caption_backend')} 키가 없다 — 이 서버의 시각자료는 설명 없이 "
            f"'생략'으로만 나간다(요소 CAPTION_FAILED · 페이지 NEEDS_REVIEW)."
        )
    return out


def get_models_status() -> dict:
    return model_manager.get_status()
