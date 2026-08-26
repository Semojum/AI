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
import json
import os
import signal
import shutil
import subprocess
import threading
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
    mb = os.environ.get("MINERU_BIN") or config.mineru_bin
    if mb:
        cand = Path(mb).with_name("mineru-api")
        if cand.exists():
            return str(cand)
    return "mineru-api"


def _engine_is_vllm() -> bool:
    """MinerU가 vLLM 엔진으로 도는가.

    MinerU는 `mineru/utils/engine_utils.py:_select_linux_engine`에서 `import vllm`이
    되면 vLLM, 안 되면 transformers를 고른다. 우리는 **다른 conda env의 bin을** 부르므로
    우리 프로세스에서 import로는 못 본다 — 그 env의 bin/에 vllm 실행파일이 있는지로 본다.
    경로를 못 정하면(PATH의 bare mineru) PATH에서 찾고, 그래도 모르면 False다.
    모를 때 False로 두는 건 의도다 — 아래 concurrency()가 안전한 쪽(동시 1)으로 간다.
    """
    mb = os.environ.get("MINERU_BIN") or config.mineru_bin
    if mb:
        return Path(mb).with_name("vllm").exists()
    return shutil.which("vllm") is not None


_clamped_logged = False


def concurrency() -> int:
    """MinerU 동시 요청 실효값. **transformers 엔진이면 1로 조인다.**

    ★ 2026-08-26 — MinerU 3.4.0 hybrid-engine이 vLLM 없는 env에서 도는 경우, VLM 추론은
      `mineru_vl_utils/vlm_client/transformers_client.py`의 `aio_batch_predict`가
      `asyncio.to_thread`로 스레드에 던진다. **락이 없다.** 그 스레드들이 같은
      `Qwen2VLForConditionalGeneration` 인스턴스를 쓰는데, 이 모델은 호출 사이에
      `self.model.rope_deltas`를 남겨 두고 재사용한다(transformers 4.57.6
      `modeling_qwen2_vl.py:1454`). 동시 요청 둘이 서로의 rope_deltas를 덮어써 터진다:

        RuntimeError: The expanded size of the tensor (2) must match the existing size (0)
                      at non-singleton dimension 1. Target sizes: [3, 2, 1]. Tensor sizes: [0, 1]

      실측(로그 2,171쪽 전수): 텍스트레이어 폴백 142쪽(6.5%) 중 **102쪽(72%)이 이 에러**다.
      폴백은 표·그림 구조를 통째로 잃으므로(`pipeline._fallback_text_layer`) 표가 텍스트
      줄로 풀려 왼칸·오른칸·행이름이 뒤섞인다 — 2026-08-26 시연 지적 1번이 이것이다.

      재시도(#307)로는 못 막는다. 상대 요청이 도는 동안은 두 번째 시도도 같이 터진다
      (2026-08-26 실측: 사회문화 p105 재시도 1·2차 모두 실패, 231.7초 소모).

    vLLM 엔진에는 이 공유 상태가 없다(연속 배칭). 그래서 vLLM일 때만 설정값을 그대로 쓴다.
    처리량 대가는 vLLM 경로에서 0이고, transformers 경로에서만 발생한다
    (동시 1→716쪽/h · 2→1,080). transformers 경로는 어차피 RUNBOOK이 권하는 경로가 아니다.
    """
    global _clamped_logged
    n = max(1, config.mineru_max_concurrent)
    if _engine_is_vllm():
        return n
    # ★ 조이든 안 조이든 **엔진이 느린 쪽으로 떨어졌다는 사실 자체를 크게 알린다**
    #   (2026-08-26 pm 지시). 이게 조용해서 밤새 전수 재추출 한 벌이 잘못된 엔진 위에서
    #   돌 뻔했다. 종전에는 `mineru_runner._announce_engine`이 INFO 한 줄을 낼 뿐이었다.
    if not _clamped_logged:
        _clamped_logged = True
        logger.warning(
            "⚠ MinerU 엔진이 vLLM이 아니다(bin=%s). 느린 경로이고(RUNBOOK 기준 57.7s/p) "
            "transformers 클라이언트가 스레드 비안전이라 동시 요청이 겹치면 rope_deltas "
            "레이스로 추출이 터진다 — 그 쪽은 표·그림을 통째로 잃는다(텍스트레이어 폴백). "
            "동시 요청을 %d→1로 조인다. vLLM env(RUNBOOK §1 mnr_vllm)로 띄우면 원래 값을 쓴다.",
            os.environ.get("MINERU_BIN") or config.mineru_bin or "(PATH)", n)
    return 1


# 죽은 서비스를 되살릴 때 쓰는 자물쇠·한도.
# 쪽은 병렬로 도는데 하나가 재기동하는 동안 나머지가 우르르 또 띄우면 GPU가 터진다.
_restart_lock = threading.Lock()
_restarts = 0
_last_restart = 0.0
_MAX_RESTARTS = int(os.environ.get("MINERU_MAX_RESTARTS", "3"))
_RESTART_COOLDOWN = float(os.environ.get("MINERU_RESTART_COOLDOWN", "60"))
# 재기동은 기동보다 짧게 기다린다 — 쪽 예산이 180초라 여기서 다 쓰면 안 된다.
# 실측 기동 중앙 26.6초(75회)라 120초면 넉넉하다.
_RESTART_WAIT = float(os.environ.get("MINERU_RESTART_WAIT", "120"))


def get_url() -> str | None:
    """현재 사용 가능한 mineru-api URL. 죽어 있으면 **한 번 되살려 본다**.

    ★ 2026-08-09 — 종전엔 health가 실패하면 그냥 None을 돌려줬다. 그러면 쪽마다 CLI가
      자기 서버를 새로 띄워 조용히 느려지고, 그 작업의 **남은 쪽이 전부 폴백**한다.
      폴트 주입으로 재현했다: mineru-api에 SIGSEGV를 넣으니 뒤따른 4쪽이 4쪽 다 폴백했고
      health는 계속 False였다(`temp/segv/inject.jsonl`). vLLM 백엔드는 세그폴트가
      드물지만(75회 450쪽 0건, 조건별 95% 상한 12%) **한 번 나면 그 뒤가 통째로 무너진다** —
      그래서 빈도보다 회복이 중요하다.

    되살리기 전에 `stop()`으로 죽은 그룹을 먼저 거둔다. 안 그러면 `VLLM::EngineCore`가
    VRAM을 문 채 남아 새 인스턴스가 메모리를 못 잡는다(실측 5,955MiB 잔존).
    """
    global _restarts, _last_restart
    if _url and _health(_url, 1.0):
        return _url
    # 우리가 띄운 게 아니면 손대지 않는다(외부 URL은 남의 것, 비활성은 의도된 것).
    if os.environ.get("MINERU_API_URL") or os.environ.get("MINERU_PERSISTENT", "1") == "0":
        return None

    with _restart_lock:
        # 자물쇠를 기다리는 동안 다른 쪽이 이미 살렸을 수 있다.
        if _url and _health(_url, 1.0):
            return _url
        now = time.time()
        if _restarts >= _MAX_RESTARTS:
            logger.error("MinerU 재기동 한도 초과(%d회) → CLI 폴백으로 계속한다", _restarts)
            return None
        if now - _last_restart < _RESTART_COOLDOWN:
            return None                     # 방금 살려봤는데 또 죽었다 — 잠시 쉰다
        _restarts += 1
        _last_restart = now
        logger.warning("MinerU 서비스가 죽었다(health 실패) → 재기동 %d/%d",
                       _restarts, _MAX_RESTARTS)
        stop()                              # 죽은 그룹을 먼저 거둔다(VRAM 회수)
        return ensure_started(wait=_RESTART_WAIT)


def _warn_if_unsafe_reuse(url: str) -> None:
    """남이 띄워 둔 서버를 물려받았는데 그게 동시 2 이상이면 알린다.

    우리 슬롯을 1로 조여도 **다른 프로세스가 같은 서버에 동시에 던지면** 레이스는 그대로다
    (concurrency() 주석 참조). 서버는 한 번 뜨면 재사용되므로, 나중에 MINERU_BIN을 바꿔도
    이미 뜬 transformers 서버에 붙는다 — 2026-08-26에 이 조용함이 전수 재추출 한 벌을
    통째로 오염시켰다. 고칠 수는 없으니 최소한 보이게 한다.
    """
    if _engine_is_vllm():
        return
    try:
        with urllib.request.urlopen(url + "/health", timeout=2.0) as r:
            n = json.loads(r.read().decode("utf-8")).get("max_concurrent_requests")
    except Exception:  # noqa: BLE001
        return
    if isinstance(n, int) and n > 1:
        logger.warning(
            "재사용한 MinerU 서버가 동시 %d로 떠 있다(엔진 transformers). 우리 요청은 1로 "
            "조이지만 다른 프로세스가 같이 던지면 rope_deltas 레이스로 추출이 터진다. "
            "그 쪽은 표·그림을 잃는다. 이 서버를 내리고 vLLM env로 다시 띄우는 것이 정답이다.", n)


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
        _warn_if_unsafe_reuse(url)
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
           "MINERU_API_MAX_CONCURRENT_REQUESTS": str(concurrency())}

    # vLLM 백엔드 필수 둘. 자식 프로세스에만 얹는다 — 우리 프로세스의 링커를 건드리면
    # 다른 확장 모듈이 엉뚱한 libstdc++를 물 수 있다.
    ld = os.environ.get("MINERU_LD_LIBRARY_PATH") or config.mineru_ld_library_path
    if ld:
        prev = env.get("LD_LIBRARY_PATH", "")
        env["LD_LIBRARY_PATH"] = f"{ld}{os.pathsep}{prev}" if prev else ld
    if config.mineru_batch_invariant:
        # 같은 입력 → 같은 출력. 끄면 같은 조건 재실행이 80.0%만 일치해 A/B가 불가능하다.
        # ★ 켜도 100%는 아니다(2026-08-21 실측). 같은 커밋·같은 조건 두 벌에서 최종 산출이
        #   갈린 쪽이 **1/709(0.14%)** 있었다 — MinerU vlm 추론이 표 요소에서 새는 자리가
        #   남는다(EBS-E26-014 p0079, table_body가 갈려 점자 2줄 차이).
        #   레버는 이것뿐이다: mineru CLI·mineru-api 어느 쪽에도 seed·temperature 옵션이
        #   없고(--host/--port/--reload/--allow-public-http-client/--enable-vlm-preload가 전부),
        #   vLLM 엔진 인자는 MinerU 내부에서 만들어 우리가 못 준다.
        #   → 추출 계열 A/B의 **총편집 잡음 바닥 ±10셀은 구조적 하한**이다. 없앨 수 없다.
        env.setdefault("VLLM_BATCH_INVARIANT", "1")

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
        # ★ 회전(2026-08-21). 이어붙이기만 하다 보니 16MB까지 자랐다. MinerU가 쪽마다
        #   INFO를 쏟아 기동 실패 원인이 오히려 묻힌다 — 로그를 남기는 목적이 그거였는데.
        #   기동 시점에 한 번만 본다(도는 중에는 안 자른다 — 파일 핸들이 열려 있다).
        cap = int(os.environ.get("MINERU_API_LOG_MAX_MB", "32")) * 1024 * 1024
        if log_path.exists() and log_path.stat().st_size > cap:
            prev = log_path.with_suffix(".log.1")
            prev.unlink(missing_ok=True)
            log_path.rename(prev)          # 직전 한 벌만 남긴다
        sink = open(log_path, "ab")
    except Exception:  # noqa: BLE001
        sink = subprocess.DEVNULL
        log_path = None

    logger.info("MinerU 영구 서비스 기동 중: %s (VLM 프리로드 · 동시 %d · VRAM %s)…",
                url, concurrency(), gpu_util)
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
    global _proc, _pgid, _url
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
    _url = None          # 죽은 URL을 남겨두면 get_url이 계속 그걸 물고 health를 친다
