"""MinerU 영구 서비스 관리 — 서비스 없이 검증 가능한 로직 회귀 테스트."""
import os

from app.ai.parser import mineru_service as ms


class TestBinResolve:
    def test_MINERU_BIN_옆_api(self, tmp_path, monkeypatch):
        (tmp_path / "mineru").write_text("")
        (tmp_path / "mineru-api").write_text("")
        monkeypatch.setenv("MINERU_BIN", str(tmp_path / "mineru"))
        assert ms._mineru_api_bin() == str(tmp_path / "mineru-api")

    def test_없으면_PATH의_mineru_api(self, monkeypatch):
        monkeypatch.delenv("MINERU_BIN", raising=False)
        assert ms._mineru_api_bin() == "mineru-api"


class TestEnsureStarted:
    def test_PERSISTENT_0이면_None(self, monkeypatch):
        monkeypatch.delenv("MINERU_API_URL", raising=False)
        monkeypatch.setenv("MINERU_PERSISTENT", "0")
        assert ms.ensure_started() is None

    def test_외부URL_health실패시_None(self, monkeypatch):
        monkeypatch.setenv("MINERU_API_URL", "http://127.0.0.1:59999")  # 안 뜬 포트
        assert ms.ensure_started() is None


class TestGetUrl:
    def test_서비스없으면_None(self, monkeypatch):
        monkeypatch.setattr(ms, "_url", None)
        assert ms.get_url() is None
