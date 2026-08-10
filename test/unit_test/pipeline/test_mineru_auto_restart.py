"""mineru-api가 죽으면 get_url()이 되살리는지 — 세그폴트 회복 회귀 (2026-08-09).

폴트 주입으로 확인한 것(`temp/segv/inject.jsonl`): mineru-api에 SIGSEGV를 넣으면
health가 False로 굳고 **뒤따른 4쪽이 4쪽 다 폴백**했다. 세그폴트 자체는 드물지만
(75회 450쪽 0건) 한 번 나면 그 작업의 남은 쪽이 통째로 무너진다.

여기서는 진짜 mineru-api 대신 /health만 돌려주는 가짜 서버를 쓴다 — GPU도 모델도
필요 없고, 검증하려는 것은 "죽으면 다시 띄우는가"이지 추출 품질이 아니다.
"""
from __future__ import annotations

import os
import socket
import subprocess
import sys
import time

import pytest

import app.ai.parser.mineru_service as ms

# /health에 200을 돌려주는 최소 서버. 인자로 받은 포트를 쓴다.
_FAKE = """
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer
class H(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200 if self.path == "/health" else 404)
        self.end_headers()
    def log_message(self, *a): pass
HTTPServer(("127.0.0.1", int(sys.argv[1])), H).serve_forever()
"""


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture()
def fake_service(monkeypatch):
    """ensure_started가 가짜 서버를 띄우도록 갈아끼운다."""
    port = _free_port()
    url = f"http://127.0.0.1:{port}"
    spawned: list[subprocess.Popen] = []

    def fake_ensure(wait: float = 240.0):
        p = subprocess.Popen([sys.executable, "-c", _FAKE, str(port)],
                             start_new_session=True)
        spawned.append(p)
        ms._proc, ms._pgid = p, p.pid
        for _ in range(50):
            if ms._health(url, 0.5):
                ms._url = url
                return url
            time.sleep(0.1)
        return None

    monkeypatch.setattr(ms, "ensure_started", fake_ensure)
    monkeypatch.delenv("MINERU_API_URL", raising=False)
    monkeypatch.setenv("MINERU_PERSISTENT", "1")
    ms._restarts, ms._last_restart = 0, 0.0
    ms._url, ms._proc, ms._pgid = None, None, None
    yield url, spawned
    ms.stop()
    for p in spawned:
        try:
            p.kill()
        except Exception:  # noqa: BLE001
            pass
    ms._restarts, ms._last_restart = 0, 0.0


def test_죽으면_되살린다(fake_service) -> None:
    url, spawned = fake_service
    assert ms.ensure_started() == url
    assert ms.get_url() == url, "살아 있는데 못 찾는다"

    ms._proc.kill()                        # 세그폴트 흉내
    ms._proc.wait()
    time.sleep(0.3)
    assert not ms._health(url, 0.5), "안 죽어서 회귀를 재현 못 함"

    assert ms.get_url() == url, "죽은 뒤 되살리지 못했다 — 남은 쪽이 전부 폴백한다"
    assert ms._restarts == 1
    assert len(spawned) == 2               # 처음 + 재기동


def test_재기동_한도를_넘으면_포기한다(fake_service, monkeypatch) -> None:
    """무한 재기동은 GPU를 태운다. 한도를 넘으면 CLI 폴백으로 넘긴다."""
    url, _ = fake_service
    monkeypatch.setattr(ms, "_MAX_RESTARTS", 0)
    ms._url = url                          # 죽은 URL을 물고 있는 상태
    assert ms.get_url() is None


def test_쿨다운_중에는_다시_안_띄운다(fake_service) -> None:
    """살리자마자 또 죽으면 곧바로 재시도하지 않는다(우르르 방지)."""
    url, spawned = fake_service
    assert ms.ensure_started() == url
    ms._proc.kill(); ms._proc.wait(); time.sleep(0.3)
    assert ms.get_url() == url             # 1회차 — 살아난다
    ms._proc.kill(); ms._proc.wait(); time.sleep(0.3)
    assert ms.get_url() is None            # 쿨다운 안이라 안 띄운다
    assert len(spawned) == 2


def test_외부_URL은_손대지_않는다(monkeypatch) -> None:
    """남이 띄운 서비스는 우리가 죽이고 살릴 대상이 아니다."""
    monkeypatch.setenv("MINERU_API_URL", "http://127.0.0.1:1")   # 죽어 있는 주소
    ms._url, ms._restarts = "http://127.0.0.1:1", 0
    assert ms.get_url() is None
    assert ms._restarts == 0, "외부 서비스를 재기동하려 들었다"
