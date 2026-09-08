"""상주 mineru-api 직행 배선 — 스위치·폴백·엔진 실측.

★ 2026-09-08 — 쪽마다 `mineru` CLI 를 새로 띄우던 것을 :30000 직행으로 바꿨다.
  CLI 기동(순수 import)만 2.9초인데 실제 VLM 추론은 1.1초다.
  이 파일이 지키는 것은 셋이다: ① 서버가 있으면 CLI 를 안 띄운다 ② 서버가 없거나
  `MINERU_CLIENT=cli` 면 종전 CLI 로 떨어진다 ③ 응답 zip 을 그대로 푼다.
"""
import io
import zipfile
from unittest.mock import patch

import pytest

from app.ai.parser import mineru_runner as MR


def _zip_bytes() -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("doc/hybrid/doc_content_list.json", '[{"type": "text"}]')
    return buf.getvalue()


def _pdf(tmp_path):
    f = tmp_path / "a.pdf"
    f.write_bytes(b"%PDF-1.7\n")
    return f


class _Resp:
    def __init__(self, code=200, content=b"", text=""):
        self.status_code, self.content, self.text = code, content, text


class TestClientSwitch:
    def test_서버가_있으면_CLI를_안_띄운다(self, tmp_path, monkeypatch):
        monkeypatch.delenv("MINERU_CLIENT", raising=False)
        with patch("app.ai.parser.mineru_service.get_url", return_value="http://x:30000"), \
             patch("app.ai.parser.mineru_runner.requests.post",
                   return_value=_Resp(content=_zip_bytes())) as post, \
             patch("app.ai.parser.mineru_runner.subprocess.run") as run:
            MR._run_mineru(_pdf(tmp_path), tmp_path / "out", 3, timeout=60)
        run.assert_not_called()
        form = dict(post.call_args.kwargs["data"])
        assert form["start_page_id"] == "3" and form["end_page_id"] == "3"
        # CLI 가 보내던 폼데이터와 같아야 한다 — 다르면 추출이 달라진다
        assert form["backend"] == "hybrid-engine" and form["effort"] == "medium"
        assert form["return_content_list"] == "true" and form["response_format_zip"] == "true"
        assert (tmp_path / "out/doc/hybrid/doc_content_list.json").exists()

    def test_스위치가_cli면_CLI로_간다(self, tmp_path, monkeypatch):
        monkeypatch.setenv("MINERU_CLIENT", "cli")
        with patch("app.ai.parser.mineru_service.get_url", return_value="http://x:30000"), \
             patch("app.ai.parser.mineru_runner.requests.post") as post, \
             patch("app.ai.parser.mineru_runner.subprocess.run") as run:
            run.return_value.returncode = 0
            MR._run_mineru(_pdf(tmp_path), tmp_path / "out", 0, timeout=60)
        post.assert_not_called()
        run.assert_called_once()

    def test_서버가_없으면_CLI로_떨어진다(self, tmp_path, monkeypatch):
        """CI·서버 미기동 환경의 길. 여기가 막히면 서버 없는 곳이 통째로 죽는다."""
        monkeypatch.delenv("MINERU_CLIENT", raising=False)
        with patch("app.ai.parser.mineru_service.get_url", return_value=None), \
             patch("app.ai.parser.mineru_runner.requests.post") as post, \
             patch("app.ai.parser.mineru_runner.subprocess.run") as run:
            run.return_value.returncode = 0
            MR._run_mineru(_pdf(tmp_path), tmp_path / "out", 0, timeout=60)
        post.assert_not_called()
        run.assert_called_once()

    def test_실패는_재시도_대상_예외로_올린다(self, tmp_path, monkeypatch):
        monkeypatch.delenv("MINERU_CLIENT", raising=False)
        with patch("app.ai.parser.mineru_service.get_url", return_value="http://x:30000"), \
             patch("app.ai.parser.mineru_runner.requests.post",
                   return_value=_Resp(code=500, text="boom")):
            with pytest.raises(RuntimeError):
                MR._run_mineru(_pdf(tmp_path), tmp_path / "out", 0, timeout=60)

    def test_타임아웃은_MineruTimeout(self, tmp_path, monkeypatch):
        """재시도하면 예산이 두 배다 — 타임아웃만은 따로 올려야 run() 이 안 다시 부른다."""
        monkeypatch.delenv("MINERU_CLIENT", raising=False)
        import requests
        with patch("app.ai.parser.mineru_service.get_url", return_value="http://x:30000"), \
             patch("app.ai.parser.mineru_runner.requests.post",
                   side_effect=requests.Timeout()):
            with pytest.raises(MR.MineruTimeout):
                MR._run_mineru(_pdf(tmp_path), tmp_path / "out", 0, timeout=60)


class TestServerEngineProbe:
    """물려받은 서버의 엔진이 `MINERU_BIN` 추정을 이긴다(2026-09-08 동시성 오판)."""

    def test_실측이_MINERU_BIN_추정을_이긴다(self, tmp_path, monkeypatch):
        from app.ai.parser import mineru_service as MS
        monkeypatch.delenv("MINERU_ENGINE", raising=False)
        monkeypatch.setenv("MINERU_BIN", str(tmp_path / "mineru"))   # 옆에 vllm 없음
        monkeypatch.setattr(MS, "_server_engine_vllm", None)
        assert MS._engine_is_vllm() is False
        monkeypatch.setattr(MS, "_server_engine_vllm", True)
        assert MS._engine_is_vllm() is True

    def test_MINERU_ENGINE이_실측보다_세다(self, monkeypatch):
        from app.ai.parser import mineru_service as MS
        monkeypatch.setenv("MINERU_ENGINE", "transformers")
        monkeypatch.setattr(MS, "_server_engine_vllm", True)
        assert MS._engine_is_vllm() is False

    def test_서버_실행파일_옆_vllm으로_판정(self, tmp_path, monkeypatch):
        from app.ai.parser import mineru_service as MS
        (tmp_path / "vllm").touch()
        monkeypatch.setattr(MS, "_server_engine_vllm", None)
        monkeypatch.setattr(MS, "_exe_of_local_port", lambda p: tmp_path / "python3.10")
        MS._probe_server_engine("http://127.0.0.1:30000")
        assert MS._server_engine_vllm is True

    def test_원격_서버는_안_건드린다(self, monkeypatch):
        from app.ai.parser import mineru_service as MS
        monkeypatch.setattr(MS, "_server_engine_vllm", None)
        monkeypatch.setattr(MS, "_exe_of_local_port",
                            lambda p: pytest.fail("원격인데 로컬 포트를 봤다"))
        MS._probe_server_engine("http://10.0.0.5:30000")
        assert MS._server_engine_vllm is None
