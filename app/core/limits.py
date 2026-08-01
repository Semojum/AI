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

from app.core.config import config

# 이벤트 루프별로 만든다 — 운영 서버는 단일 루프라 사실상 프로세스 전역이고,
# 테스트(asyncio.run 반복)에서는 루프가 달라도 "다른 루프의 Future" 오류가 안 난다.
# (inference_lock과 같은 방식)
_mineru_slots: "dict[asyncio.AbstractEventLoop, asyncio.Semaphore]" = {}
_caption_sem: threading.Semaphore | None = None
_caption_lock = threading.Lock()


def mineru_slot() -> asyncio.Semaphore:
    """MinerU 추출 동시 실행 슬롯. 크기 = config.mineru_max_concurrent.

    GPU 추출 서버를 보호한다. 무릎(실측 2)을 넘겨 던지면 처리량은 안 늘고 꼬리만 길어져,
    상한에 걸리는 정상 페이지가 생긴다.
    """
    loop = asyncio.get_running_loop()
    sem = _mineru_slots.get(loop)
    if sem is None:
        sem = asyncio.Semaphore(max(1, config.mineru_max_concurrent))
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


def _reset_for_tests() -> None:
    """테스트에서 config를 바꾼 뒤 슬롯 크기를 다시 잡기 위한 훅."""
    global _caption_sem
    _mineru_slots.clear()
    _caption_sem = None
