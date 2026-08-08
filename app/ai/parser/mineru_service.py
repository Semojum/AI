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
import signal
import subprocess
import time
import urllib.request
from pathlib import Path

from app.core.config import config
from app.utils.logger import get_logger

logger = get_logger(__name__)

_PORT = int(os.environ.get("MINERU_API_PORT", "30000"))
_proc: subprocess.Popen | None = None
# 기동 때 그룹 id를 붙잡아 둔다. 부모가 죽으면 pid가 회수돼 os.getpgid가 못 찾는데,
# **고아가 생기는 경우가 정확히 그때**다(세그폴트로 부모만 날아가고 손자가 남는다).
_pgid: int | None = None
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
    global _proc, _pgid, _url

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

    # 동시 요청 허용치. mineru-api 기본은 3이며 이 환경변수로 올린다.
    # 실측(2026-07-29, 서버 1대): 동시 1→716쪽/h · 2→1,080 · 4→1,632 · 8→1,905.
    # GPU 추론은 줄을 서지만 프로세스 기동·PDF 렌더가 겹쳐 4쪽에서 처리량 2.28배가 된다.
    # VRAM은 동시 8쪽에서도 3.5GB로 여유가 있다.
    # flashinfer는 어텐션·샘플링 커널을 JIT 컴파일할 때 PATH에서 `ninja`를 찾는다.
    # mineru-api를 절대경로로 띄우면 conda env의 bin/이 PATH에 없어 ninja를 못 찾고
    # FileNotFoundError로 EngineCore가 죽는다(2026-07-30 A10G 실측 — 메모리 문제로
    # 오인하기 쉽다. 트레이스백이 determine_available_memory 안에서 끝나기 때문).
    # systemd는 PATH가 더 최소라 반드시 필요하다.
    _api_dir = Path(_mineru_api_bin()).parent
    _path = os.environ.get("PATH", "")
    if _api_dir.name:                     # bare "mineru-api"(PATH 의존)면 손대지 않는다
        _path = f"{_api_dir}{os.pathsep}{_path}"
    env = {**os.environ,
           "PATH": _path,
           "MINERU_API_MAX_CONCURRENT_REQUESTS": str(config.mineru_max_concurrent)}

    # vLLM이 선점할 VRAM 비율. MinerU 기본 0.5는 HCXT와 GPU 한 장을 나눠 쓰는
    # 우리 배치에서 확보에 실패한다 — A10G 24GB 실측(2026-07-30):
    #   HCXT 4bit 12.6GB 점유 → 여유 9.49GB < 요구 11.03GB
    #   → EngineCore 기동 실패 → CLI 폴백으로 조용히 느려짐(39s → 50~70s/쪽).
    # 0.35(≈7.7GB)면 1.2B 가중치 ~2.5GB + KV 캐시로 충분하고 둘이 공존한다.
    # GPU를 독점하는 배치면 MINERU_GPU_MEM_UTIL로 올린다.
    gpu_util = os.environ.get("MINERU_GPU_MEM_UTIL", "0.35")

    # 자식 출력을 버리면 기동 실패 원인이 통째로 사라진다(위 사고를 20분 늦춘 원인).
    # 파일로 남겨 두고, 못 열면 그때만 DEVNULL로 떨어진다.
    log_path = Path(os.environ.get(
        "MINERU_API_LOG", str(Path.cwd() / "storage" / "logs" / "mineru_api.log")))
    try:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        sink = open(log_path, "ab")
    except Exception:  # noqa: BLE001
        sink = subprocess.DEVNULL
        log_path = None

    logger.info("MinerU 영구 서비스 기동 중: %s (VLM 프리로드 · 동시 %d · VRAM %s)…",
                url, config.mineru_max_concurrent, gpu_util)
    try:
        _proc = subprocess.Popen(
            [_mineru_api_bin(), "--host", "127.0.0.1", "--port", str(_PORT),
             "--enable-vlm-preload", "true",
             "--gpu-memory-utilization", gpu_util],
            stdout=sink, stderr=subprocess.STDOUT, env=env,
            # 자식들을 한 프로세스 그룹으로 묶는다. vLLM 백엔드는 `VLLM::EngineCore`를
            # 손자 프로세스로 띄우는데, 부모만 죽이면 그놈이 고아로 남아 VRAM을
            # 5.2GB씩 문다(실측 12,158MiB까지 누적). `pkill -f mineru-api`로도 안 잡힌다 —
            # 이름이 안 맞기 때문이다. 그룹으로 묶어야 stop()이 통째로 거둘 수 있다.
            start_new_session=True,
        )
        _pgid = _proc.pid          # start_new_session이면 pgid == 자식 pid
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
            logger.warning("MinerU 서비스 프로세스 조기 종료(exit=%s) → CLI 폴백. 원인: %s",
                           _proc.returncode, log_path or "(로그 미기록)")
            return None
        time.sleep(2)
    logger.warning("MinerU 서비스 기동 타임아웃(%.0fs) → CLI 폴백. 원인: %s",
                   wait, log_path or "(로그 미기록)")
    return None


def stop() -> None:
    """자동 기동한 mineru-api를 **프로세스 그룹째** 종료(atexit).

    부모만 죽이면 vLLM 백엔드의 `VLLM::EngineCore` 손자가 고아로 남아 VRAM을 문다.
    기동 때 `start_new_session=True`로 묶어 뒀으므로 그룹에 신호를 보낸다.

    부모가 이미 죽은 뒤에도(세그폴트) 그룹은 살아 있을 수 있으므로, `poll()`이
    None이 아니어도 그룹 정리는 시도한다 — 고아가 생기는 게 바로 그 경우다.
    """
    global _proc, _pgid
    if not _proc:
        return
    pgid = _pgid
    if pgid is None:                     # 예전 경로 호환
        try:
            pgid = os.getpgid(_proc.pid)
        except OSError:
            pgid = None

    if pgid is not None:
        for sig, wait_s in ((signal.SIGTERM, 5), (signal.SIGKILL, 2)):
            try:
                os.killpg(pgid, sig)
            except OSError:
                break                    # 그룹이 비었다 = 다 죽었다
            try:
                _proc.wait(timeout=wait_s)
            except Exception:            # noqa: BLE001 — 타임아웃이면 다음 신호로
                continue
            # 부모는 거뒀다. 손자가 남았을 수 있으니 그룹이 빌 때까지 본다.
            try:
                os.killpg(pgid, 0)
            except OSError:
                break                    # 그룹이 비었다
    _proc = None
    _pgid = None
