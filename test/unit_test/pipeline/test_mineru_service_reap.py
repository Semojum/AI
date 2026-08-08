"""mineru-api를 프로세스 그룹째 거두는지 — 고아 VRAM 누수 회귀 (2026-08-09).

vLLM 백엔드는 `VLLM::EngineCore`를 **손자** 프로세스로 띄운다. 부모만 죽이면 그놈이
고아로 남아 VRAM을 5.2GB씩 문다(실측 12,158MiB까지 누적). 이름이 안 맞아
`pkill -f mineru-api`로도 안 잡힌다.

특히 ②가 핵심이다 — **고아가 생기는 경우가 정확히 "부모가 먼저 죽는" 세그폴트**이고,
그때는 pid가 회수돼 `os.getpgid`가 실패한다. 그래서 그룹 id를 기동 시점에 붙잡아 둔다.
"""
from __future__ import annotations

import os
import subprocess
import sys
import time

import pytest

import app.ai.parser.mineru_service as ms

# 부모가 손자를 띄우고 자신은 잠든다 (mineru-api → VLLM::EngineCore 구조)
_CHILD = "import subprocess,time;subprocess.Popen(['sleep','60']);time.sleep(60)"


def _spawn() -> subprocess.Popen:
    p = subprocess.Popen([sys.executable, "-c", _CHILD], start_new_session=True)
    ms._proc, ms._pgid = p, p.pid
    return p


def _group_alive(pgid: int) -> bool:
    try:
        os.killpg(pgid, 0)
        return True
    except OSError:
        return False


@pytest.fixture(autouse=True)
def _restore():
    yield
    ms._proc, ms._pgid = None, None


@pytest.mark.skipif(not hasattr(os, "killpg"), reason="POSIX 전용")
@pytest.mark.parametrize("kill_parent_first", [False, True],
                         ids=["정상종료", "부모먼저죽음(세그폴트)"])
def test_stop이_손자까지_거둔다(kill_parent_first: bool) -> None:
    proc = _spawn()
    time.sleep(1.5)                       # 손자가 뜰 틈
    pgid = proc.pid
    if kill_parent_first:
        proc.kill()
        proc.wait()                       # pid 회수 — getpgid가 실패하는 상태
    assert _group_alive(pgid), "손자가 안 떠서 회귀를 재현 못 함"

    ms.stop()
    time.sleep(0.6)
    assert not _group_alive(pgid), "고아가 남았다 — VRAM 누수"


def test_stop은_두_번_불러도_안전하다() -> None:
    proc = _spawn()
    time.sleep(1.0)
    ms.stop()
    ms.stop()                             # atexit + 명시 호출이 겹칠 수 있다
    assert ms._proc is None and ms._pgid is None
