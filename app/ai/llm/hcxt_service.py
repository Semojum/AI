"""HCXT vLLM 서버 관리 — config.hcxt_backend="vllm"일 때 헬스체크·(옵션)자동 기동.

mineru_service와 같은 패턴. `hcxt_vllm_serve_cmd`가 있으면 그 명령으로 vLLM 서버를 띄우고 health를
기다리고, 없으면 외부 `hcxt_vllm_url`을 그대로 쓴다(헬스만 확인). 미응답/비활성 시 opt가 GPT-4o로 폴백.

서버 실행 예(배포 ops):
  vllm serve /models/hcxt-awq --served-model-name hcxt --quantization awq \
             --port 8100 --max-model-len 4096 --gpu-memory-utilization 0.6
"""
from __future__ import annotations

import atexit
import shlex
import subprocess
import time
import urllib.request

from app.core.config import config
from app.utils.logger import get_logger

logger = get_logger(__name__)

_proc: subprocess.Popen | None = None


def _health(base: str, timeout: float = 2.0) -> bool:
    """vLLM OpenAI 서버 health = GET {base}/models 200."""
    try:
        with urllib.request.urlopen(base.rstrip("/") + "/models", timeout=timeout) as r:
            return r.status == 200
    except Exception:  # noqa: BLE001
        return False


def ensure_started(wait: float = 600.0) -> bool:
    """HCXT vLLM 서버 보장. backend!=vllm이면 no-op(False). 사용 가능하면 True."""
    if config.hcxt_backend != "vllm":
        return False
    base = config.hcxt_vllm_url.rstrip("/")   # 예: http://127.0.0.1:8100/v1
    if _health(base):
        logger.info("HCXT vLLM 서버 사용: %s", base)
        return True
    if not config.hcxt_vllm_serve_cmd:
        logger.warning("HCXT vLLM 서버 미응답(%s)·자동기동 명령 없음 → 호출 시 GPT-4o 폴백", base)
        return False

    logger.info("HCXT vLLM 서버 기동 중: %s", config.hcxt_vllm_serve_cmd)
    global _proc
    try:
        _proc = subprocess.Popen(
            shlex.split(config.hcxt_vllm_serve_cmd),
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("HCXT vLLM 기동 실패(%s) → GPT-4o 폴백", exc)
        return False
    atexit.register(stop)

    t0 = time.time()
    while time.time() - t0 < wait:
        if _health(base):
            logger.info("HCXT vLLM 서버 준비 완료 (%.0fs)", time.time() - t0)
            return True
        if _proc.poll() is not None:
            logger.warning("HCXT vLLM 프로세스 조기 종료 → GPT-4o 폴백")
            return False
        time.sleep(3)
    logger.warning("HCXT vLLM 기동 타임아웃(%.0fs) → GPT-4o 폴백", wait)
    return False


def stop() -> None:
    """자동 기동한 vLLM 서버 종료(atexit)."""
    global _proc
    if _proc and _proc.poll() is None:
        _proc.terminate()
        try:
            _proc.wait(timeout=5)
        except Exception:  # noqa: BLE001
            _proc.kill()
    _proc = None
