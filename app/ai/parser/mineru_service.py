"""영구 MinerU 서비스(mineru-api) 관리 — 모델 1회 프리로드로 페이지마다 재로드 비용 제거.

기존엔 mineru_runner가 페이지마다 `mineru` CLI를 띄워 VLM 모델을 새로 로드했다(추출 ~50-70s,
이 중 모델 로드·서비스 spin-up이 ~15-30s). 영구 mineru-api를 한 번 띄워두고 CLI에 `--api-url`로
붙이면 모델이 상주해 페이지마다 추론만 한다(~39s).

동작:
- `MINERU_API_URL` 환경변수가 있으면 그 외부 서비스 사용(자동 기동 안 함).
- 없고 `MINERU_PERSISTENT`≠0이면 mineru-api 자동 기동(모델 프리로드) 후 health 대기.
- 기동 실패/비활성 시 None → mineru_runner가 요청마다 CLI(vlm-engine)로 폴백(동작 보장).

VRAM: MinerU VLM ≈ 3GB로 가벼워 HCXT(~12.8GB)와 22GB GPU에서 공존 가능.
"""
from __future__ import annotations

import atexit
import os
import subprocess
import time
import urllib.request
from pathlib import Path

from app.utils.logger import get_logger

logger = get_logger(__name__)

_PORT = int(os.environ.get("MINERU_API_PORT", "30000"))
_proc: subprocess.Popen | None = None
_url: str | None = None


def _health(url: str, timeout: float = 2.0) -> bool:
    try:
        with urllib.request.urlopen(url + "/health", timeout=timeout) as r:
            return r.status == 200
    except Exception:  # noqa: BLE001
        return False


def _mineru_api_bin() -> str:
    """MINERU_BIN(.../bin/mineru) 옆의 mineru-api. 없으면 PATH의 mineru-api."""
    mb = os.environ.get("MINERU_BIN")
    if mb:
        cand = Path(mb).with_name("mineru-api")
        if cand.exists():
            return str(cand)
    return "mineru-api"


def get_url() -> str | None:
    """현재 사용 가능한 mineru-api URL(health 통과 시). 없으면 None."""
    return _url if (_url and _health(_url, 1.0)) else None


def ensure_started(wait: float = 240.0) -> str | None:
    """영구 mineru-api를 보장(외부 URL 사용 또는 자동 기동). 사용 URL 반환, 실패 시 None."""
    global _proc, _url

    ext = os.environ.get("MINERU_API_URL")
    if ext:
        _url = ext.rstrip("/")
        ok = _health(_url)
        logger.info("MinerU 외부 서비스 %s (health=%s)", _url, ok)
        return _url if ok else None

    if os.environ.get("MINERU_PERSISTENT", "1") == "0":
        return None  # 영구 서비스 비활성 → 요청마다 CLI 폴백

    url = f"http://127.0.0.1:{_PORT}"
    if _health(url):                       # 이미 떠 있으면 재사용
        _url = url
        logger.info("MinerU 영구 서비스 재사용: %s", url)
        return url

    logger.info("MinerU 영구 서비스 기동 중: %s (VLM 프리로드)…", url)
    try:
        _proc = subprocess.Popen(
            [_mineru_api_bin(), "--host", "127.0.0.1", "--port", str(_PORT),
             "--enable-vlm-preload", "true"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("MinerU 서비스 기동 실패(%s) → 요청마다 CLI 폴백", exc)
        return None
    atexit.register(stop)

    t0 = time.time()
    while time.time() - t0 < wait:
        if _health(url):
            _url = url
            logger.info("MinerU 영구 서비스 준비 완료 (%.0fs)", time.time() - t0)
            return url
        if _proc.poll() is not None:
            logger.warning("MinerU 서비스 프로세스 조기 종료 → CLI 폴백")
            return None
        time.sleep(2)
    logger.warning("MinerU 서비스 기동 타임아웃(%.0fs) → CLI 폴백", wait)
    return None


def stop() -> None:
    """자동 기동한 mineru-api 종료(atexit)."""
    global _proc
    if _proc and _proc.poll() is None:
        _proc.terminate()
        try:
            _proc.wait(timeout=5)
        except Exception:  # noqa: BLE001
            _proc.kill()
    _proc = None
