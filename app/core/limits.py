"""자원별 동시 실행 슬롯 — 페이지 상한 하나로는 파이프라인이 논다.

종전에는 `max_concurrent_pages`(= gRPC `maximum_concurrent_rpcs`) 하나가 전부를 막았다.
페이지는 수명 내내 그 슬롯을 붙잡으므로, 1번 페이지가 캡셔닝(외부 API — GPU를 안 쓴다)을
도는 동안 MinerU(GPU)는 놀고, 반대도 마찬가지다. 자원마다 슬롯을 따로 두면 페이지들이
단계별로 겹쳐 흐른다 — "한 파트가 끝나면 다음 페이지가 바로 그 파트에 들어간다".

★ 슬롯 대기는 그 단계의 타임아웃에 넣지 않는다.
  대기까지 타임아웃에 포함하면 줄이 길어질수록 **정상 페이지가 '느린 페이지'로 오인돼**
  끊긴다. 상한은 비정상 탐지기이므로 그러면 탐지기가 망가진다. 그래서 호출부는
  **슬롯을 잡은 뒤에** 타이머를 시작한다(`base_opt.hcxt_optimize`가 락을 잡은 뒤에 t0을
  잡는 것과 같은 규약).
  MinerU는 특히 그렇다 — mineru-api 서버가 자체 동시 상한(MINERU_API_MAX_CONCURRENT_REQUESTS)
  으로 요청을 큐에 세우는데, 그 대기 중에도 subprocess 타임아웃은 이미 돌고 있었다.

★ 페이지 예산(180초)과의 산술 — 상한 값을 함부로 올리면 안 되는 이유.
  in-flight 페이지 수를 P, MinerU 슬롯을 M, 추출 상한을 T라 하면 MinerU 슬롯을 기다리는
  페이지는 최대 P-M개이고 대기는 대략 ceil((P-M)/M)×T다.
    P=4, M=2, T=60  →  대기 ≤ 60초 + 추출 60초 + 뒷단(캡셔닝 p99 ~18초 + 규칙기반 ~1초)
                        ≈ 140초  < 180초 ✔
    P=6, M=2, T=60  →  대기 ≤ 120초 + 60초 + 뒷단 ≈ 200초  > 180초 ✘ (큐에서 죽는다)
  즉 P를 올리려면 M이나 T를 같이 손봐야 한다. 한쪽만 올리면 처리량은 그대로인 채
  뒤쪽 요청이 C7로 죽기 시작한다.
"""
from __future__ import annotations

import asyncio
import threading
import time
from collections import deque

from app.core.config import config
from app.utils.logger import get_logger

logger = get_logger(__name__)

# 이벤트 루프별로 만든다 — 운영 서버는 단일 루프라 사실상 프로세스 전역이고,
# 테스트(asyncio.run 반복)에서는 루프가 달라도 "다른 루프의 Future" 오류가 안 난다.
# (inference_lock과 같은 방식)
_mineru_slots: "dict[asyncio.AbstractEventLoop, asyncio.Semaphore]" = {}
_llm_slots: "dict[asyncio.AbstractEventLoop, asyncio.Semaphore]" = {}
_caption_sem: threading.Semaphore | None = None
_caption_lock = threading.Lock()


def mineru_slot() -> asyncio.Semaphore:
    """MinerU 추출 동시 실행 슬롯. 크기 = `mineru_service.concurrency()`.

    GPU 추출 서버를 보호한다. 무릎(실측 2)을 넘겨 던지면 처리량은 안 늘고 꼬리만 길어져,
    상한에 걸리는 정상 페이지가 생긴다.

    ★ 크기를 config에서 직접 읽지 않는다 — vLLM이 아닌 엔진에서는 동시 2가 MinerU를
      스레드 레이스로 터뜨려 그 쪽이 표·그림을 잃는다(`mineru_service.concurrency()` 주석).
      서버에 주는 상한과 우리가 던지는 수가 **같은 자리에서** 정해져야 한다.
    """
    from app.ai.parser import mineru_service   # 지연 import — 파서가 core를 물지 않게

    loop = asyncio.get_running_loop()
    sem = _mineru_slots.get(loop)
    if sem is None:
        sem = asyncio.Semaphore(mineru_service.concurrency())
        _mineru_slots[loop] = sem
    return sem


def caption_slot() -> threading.Semaphore:
    """캡셔닝(외부 API) 프로세스 전역 슬롯. 크기 = config.caption_max_concurrent.

    캡셔닝은 페이지 안에서 이미 스레드풀로 동시 실행된다(`CAPTION_CONCURRENCY`, 기본 4).
    페이지 상한을 올리면 그 곱만큼 동시 요청이 늘어(4페이지 × 4 = 16) 외부 API 요청
    한도(429)에 걸린다. 페이지를 가로질러 한 번 더 조인다.
    스레드풀에서 쓰므로 asyncio가 아니라 threading 세마포어다.
    """
    global _caption_sem
    if _caption_sem is None:
        with _caption_lock:
            if _caption_sem is None:
                _caption_sem = threading.Semaphore(max(1, config.caption_max_concurrent))
    return _caption_sem


_braille_pool: "object | None" = None
_braille_pool_lock = threading.Lock()


def braille_pool():
    """점역·조판(CPU 동기 작업) 전용 스레드풀. 크기 = config.braille_max_concurrent.

    왜 **전용** 풀인가 — `asyncio.to_thread`는 기본 실행기를 쓰는데, 파이프라인의 다른
    대기(MinerU subprocess·PDF 추출)도 그 풀을 쓴다. 점역이 7체인 × 페이지 수만큼
    몰리면 기본 풀(4 vCPU면 8칸)이 차서 **MinerU 대기가 CPU 작업 뒤에 줄을 선다**.
    풀을 갈라 두면 점역이 아무리 밀려도 I/O 대기는 막지 않는다.

    ★ 왜 이 작업이 이벤트 루프 밖으로 나가야 하나 — 점역은 순수 CPU 동기 작업인데
      코루틴 안에서 그대로 불렸다. 실측(dev 60쪽): 쪽당 중앙 121ms · p95 2,122ms
      (표 요소 하나가 2초를 먹는다). 동시 4쪽이면 루프가 최대 8.6초 멈춰서 그동안
      LLM 응답도, MinerU 완료도, gRPC 응답도 처리되지 않는다.

    ★ GIL 때문에 스레드를 늘려도 CPU 처리량은 안 는다. 크기 4는 처리량이 아니라
      **한 페이지의 긴 점역이 다른 페이지를 붙잡지 않게** 하는 값이다.
    """
    global _braille_pool
    if _braille_pool is None:
        with _braille_pool_lock:
            if _braille_pool is None:
                from concurrent.futures import ThreadPoolExecutor
                _braille_pool = ThreadPoolExecutor(
                    max_workers=max(1, config.braille_max_concurrent),
                    thread_name_prefix="braille")
    return _braille_pool


async def run_braille(fn, *args, **kwargs):
    """점역·조판 동기 함수를 전용 풀에서 돌린다(이벤트 루프 비점유)."""
    import functools

    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(braille_pool(), functools.partial(fn, *args, **kwargs))


def llm_slot() -> asyncio.Semaphore:
    """opt 단계 외부 LLM 호출 동시 실행 슬롯. 크기 = config.llm_max_concurrent.

    캡셔닝(`caption_slot`, 스레드)과 짝이 되는 async 쪽 슬롯이다. opt는 요소별
    `asyncio.gather`라 페이지 하나가 이미 요소 수만큼 동시에 던지고, 페이지가 겹치면
    그만큼 곱해진다(실측 최대 22요소 × 4페이지 = 88건 순간).

    ⚠ 이 슬롯은 **속도 제한이 아니라 동시 연결 제한**이다. 시간당 호출 상한은
      `llm_limiter()`가 따로 건다 — 둘은 막는 대상이 다르다(연결 수 vs 분당 소비량).
    """
    loop = asyncio.get_running_loop()
    sem = _llm_slots.get(loop)
    if sem is None:
        sem = asyncio.Semaphore(max(1, config.llm_max_concurrent))
        _llm_slots[loop] = sem
    return sem


# ── 시간당 호출 상한 ────────────────────────────────────────────────────────
class _Window:
    """1분 슬라이딩 윈도 누계. limit<=0이면 무제한(검사 자체를 건너뛴다)."""

    __slots__ = ("limit", "span", "events", "used", "name")

    def __init__(self, name: str, limit: int, span: float = 60.0) -> None:
        self.name, self.limit, self.span = name, limit, span
        self.events: deque = deque()      # (만료시각, 양)
        self.used = 0

    def _trim(self, now: float) -> None:
        while self.events and self.events[0][0] <= now:
            self.used -= self.events.popleft()[1]

    def wait_for(self, now: float, amount: int) -> float:
        """지금 amount를 넣을 수 있으면 0.0, 아니면 기다려야 할 초."""
        if self.limit <= 0:
            return 0.0
        self._trim(now)
        if self.used + amount <= self.limit:
            return 0.0
        need = self.used + amount - self.limit
        freed = 0
        for expire_at, a in self.events:
            freed += a
            if freed >= need:
                return max(0.0, expire_at - now)
        # 한 번에 창 전체보다 큰 요청 — 창을 비워도 안 들어간다. 비운 뒤 통과시킨다
        # (막아 버리면 큰 요소가 영원히 처리되지 않는다).
        return max(0.0, self.events[-1][0] - now) if self.events else 0.0

    def add(self, now: float, amount: int) -> None:
        if self.limit <= 0:
            return
        self.events.append((now + self.span, amount))
        self.used += amount


class RateLimiter:
    """외부 LLM 계정의 분당 소비 상한. 요청 수·입력 토큰·출력 토큰 세 창을 함께 본다.

    왜 필요한가 — 계정은 조직 공용이다. 우리 서버가 폭주하면(배치 도구 오작동, 재시도
    루프) 다른 작업까지 429로 밀린다. 상한을 계정 한도의 **절반**으로 두면 우리가
    최악으로 굴러도 나머지 절반은 남는다.

    ★ 토큰 수는 **추정치**다(입력 = 프롬프트 문자 수, 출력 = max_tokens).
      실제 usage로 되맞추지 않는다 — 평시 소비가 상한의 1/250이라(실측 쪽당 2.4건)
      2배 오차가 나도 여유가 100배 남는다. 정밀도보다 단순함이 낫다.
      # ponytail: 추정치 예약만. 실사용이 상한에 근접하면 record_ext_llm의 실제 usage로
      #           보정하는 단계를 붙일 것.

    ★ 스레드와 코루틴이 함께 쓴다 — 캡셔닝은 스레드풀, opt는 asyncio다. 계정이 하나이므로
      리미터도 하나여야 한다. 그래서 asyncio가 아니라 threading.Lock으로 짠다.
    """

    def __init__(self, rpm: int, input_tpm: int, output_tpm: int) -> None:
        self._lock = threading.Lock()
        self.req = _Window("요청", rpm)
        self.tin = _Window("입력토큰", input_tpm)
        self.tout = _Window("출력토큰", output_tpm)
        self.waited_s = 0.0          # 누적 대기 시간(진단용)
        self.waits = 0

    @property
    def enabled(self) -> bool:
        return any(w.limit > 0 for w in (self.req, self.tin, self.tout))

    def _try(self, in_tok: int, out_tok: int) -> float:
        with self._lock:
            now = time.monotonic()
            wait = max(self.req.wait_for(now, 1),
                       self.tin.wait_for(now, in_tok),
                       self.tout.wait_for(now, out_tok))
            if wait > 0:
                return wait
            self.req.add(now, 1)
            self.tin.add(now, in_tok)
            self.tout.add(now, out_tok)
            return 0.0

    def _note(self, waited: float) -> None:
        with self._lock:
            self.waited_s += waited
            self.waits += 1

    async def acquire(self, in_tok: int, out_tok: int) -> None:
        """코루틴에서 자리가 날 때까지 기다린다(opt 경로)."""
        if not self.enabled:
            return
        waited = 0.0
        while True:
            wait = self._try(in_tok, out_tok)
            if wait <= 0:
                break
            await asyncio.sleep(min(wait, 1.0))     # 창이 흐르므로 1초씩 다시 본다
            waited += min(wait, 1.0)
        if waited:
            self._note(waited)
            logger.info("LLM 상한 대기 %.1fs (입력 %d·출력 %d 토큰 예약)",
                        waited, in_tok, out_tok)

    def acquire_sync(self, in_tok: int, out_tok: int) -> None:
        """스레드에서 자리가 날 때까지 기다린다(캡셔닝·분류 경로)."""
        if not self.enabled:
            return
        waited = 0.0
        while True:
            wait = self._try(in_tok, out_tok)
            if wait <= 0:
                break
            time.sleep(min(wait, 1.0))
            waited += min(wait, 1.0)
        if waited:
            self._note(waited)
            logger.info("LLM 상한 대기 %.1fs (입력 %d·출력 %d 토큰 예약)",
                        waited, in_tok, out_tok)


_limiter: RateLimiter | None = None
_limiter_lock = threading.Lock()


def llm_limiter() -> RateLimiter:
    """외부 LLM 분당 상한. 크기 = config.llm_rpm / llm_input_tpm / llm_output_tpm."""
    global _limiter
    if _limiter is None:
        with _limiter_lock:
            if _limiter is None:
                _limiter = RateLimiter(config.llm_rpm, config.llm_input_tpm,
                                       config.llm_output_tpm)
                if _limiter.enabled:
                    logger.info("LLM 분당 상한: 요청 %s · 입력 %s · 출력 %s 토큰",
                                f"{config.llm_rpm:,}" if config.llm_rpm > 0 else "무제한",
                                f"{config.llm_input_tpm:,}" if config.llm_input_tpm > 0 else "무제한",
                                f"{config.llm_output_tpm:,}" if config.llm_output_tpm > 0 else "무제한")
    return _limiter


def estimate_tokens(text: str, image_bytes: int = 0) -> int:
    """프롬프트 → 입력 토큰 추정. 상한 예약용이라 **넉넉히** 잡는다.

    한국어는 Claude 토크나이저에서 대략 문자당 1~1.5토큰이라 문자 수를 그대로 쓴다.
    이미지는 Anthropic 문서 근사식 (가로×세로)/750을 못 쓰므로(여기선 바이트만 안다)
    바이트/1000으로 잡는다 — 1024×1024 PNG ≈ 1.5MB ≈ 1,500토큰으로, 실제
    (1024×1024)/750 ≈ 1,400과 같은 자릿수다.
    """
    return len(text or "") + image_bytes // 1000


def _reset_for_tests() -> None:
    """테스트에서 config를 바꾼 뒤 슬롯 크기를 다시 잡기 위한 훅."""
    global _caption_sem, _limiter, _braille_pool
    _mineru_slots.clear()
    _llm_slots.clear()
    _caption_sem = None
    _limiter = None
    if _braille_pool is not None:
        _braille_pool.shutdown(wait=False)   # 스레드를 남기면 테스트마다 쌓인다
        _braille_pool = None
