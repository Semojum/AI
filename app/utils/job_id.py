"""job_id 생성 — 출처(BE/로컬)와 시각을 한눈에 구분.

형식:  job_{source}_{MMDDHHMMSS}_{6자리 hex}
  - source = "be"    : BE가 gRPC(원격 peer)로 보낸 요청
  - source = "local" : AI 서버 로컬 요청(be_check·local_runner 등, localhost/직접호출)
예:  job_be_0623143052_a3f9c1 / job_local_0623143108_7b20de

gRPC 핸들러는 peer 주소로 원격/로컬을 판별해 source를 정한다(아래 source_from_peer).
"""
from __future__ import annotations

import secrets
import time


def generate(source: str = "be") -> str:
    """job_{source}_{월일시분초}_{랜덤6hex} 형식 job_id 생성."""
    stamp = time.strftime("%m%d%H%M%S", time.localtime())
    return f"job_{source}_{stamp}_{secrets.token_hex(3)}"


def source_from_peer(peer: str | None) -> str:
    """gRPC peer 주소 → 출처. localhost(127.0.0.1/::1/unix)면 local, 그 외 원격이면 be."""
    if not peer:
        return "be"
    p = peer.lower()
    if "127.0.0.1" in p or "[::1]" in p or "localhost" in p or p.startswith("unix:"):
        return "local"
    return "be"
