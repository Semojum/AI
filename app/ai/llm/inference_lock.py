"""HyperCLOVA X 단일 GPU 모델 추론 직렬화 락.

GPU에 상주하는 HCLOVA X 모델 인스턴스는 하나뿐이고, transformers `generate`는
동시 호출에 안전하지 않다(같은 모델에 동시 generate → race·VRAM 폭증·출력 손상).
한 페이지의 6체인이 asyncio.gather로 동시에 돌고, 각 체인도 요소별로 동시 실행되며,
동시 gRPC 요청까지 겹칠 수 있으므로 **모든 opt가 이 락을 공유**해 한 번에 하나만 추론한다.

이벤트 루프별로 락을 만든다 — 운영 서버는 단일 루프라 사실상 전역 직렬화이고,
테스트(asyncio.run 반복)에서는 루프가 달라도 "다른 루프의 Future" 오류가 안 난다.
"""
from __future__ import annotations

import asyncio

_locks: "dict[asyncio.AbstractEventLoop, asyncio.Lock]" = {}


def hcxt_lock() -> asyncio.Lock:
    """현재 실행 중인 이벤트 루프에 바인딩된 HCLOVA X 추론 락(공유)."""
    loop = asyncio.get_running_loop()
    lock = _locks.get(loop)
    if lock is None:
        lock = asyncio.Lock()
        _locks[loop] = lock
    return lock
