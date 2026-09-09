"""mineru_service._health — 느린 서버는 살아 있는 것이다(#848).

health 가 1초를 넘기면 죽은 것으로 보고 CLI 폴백으로 빠지던 것을 막는다.
"""
import socket
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer

from app.ai.parser import mineru_service


class _Slow(BaseHTTPRequestHandler):
    def do_GET(self):
        time.sleep(1.5)
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"{}")

    def log_message(self, *a):
        pass


def test_slow_health_is_alive():
    srv = HTTPServer(("127.0.0.1", 0), _Slow)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        url = f"http://127.0.0.1:{srv.server_port}"
        assert mineru_service._health(url, timeout=0.3) is True      # 느림 = 바쁨
        assert mineru_service._health(url, timeout=5.0) is True      # 정상 200
    finally:
        srv.shutdown()


def test_dead_health_is_dead():
    s = socket.socket(); s.bind(("127.0.0.1", 0)); port = s.getsockname()[1]; s.close()
    assert mineru_service._health(f"http://127.0.0.1:{port}", timeout=1.0) is False
