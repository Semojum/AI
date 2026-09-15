"""엔진 사망 신호 — `/health` 200 뒤에 숨은 죽은 엔진 (#870).

2026-09-12 00:02:31 에 mineru-api 의 vLLM `EngineCore` 가 OOM 으로 죽었는데
`/health` 는 계속 200 을 냈고 `/file_parse` 만 409 `EngineDeadError` 를 냈다.
`get_url()` 은 health 만 보므로 재기동 길이 한 번도 안 열렸고, `EBS-E26-013` 56쪽(6.2%)이
조용히 텍스트레이어 폴백으로 떴다. 러너 요약은 `blk0 fail0` 이라 정상 런과 구별이 안 됐다.

#848 은 **반대쪽 구멍**(살아 있는 서버를 죽었다고 오판)을 고쳤다. 이 파일은 이쪽을 지킨다.
"""
from __future__ import annotations

import io
import zipfile
from pathlib import Path
from unittest.mock import patch

import pytest

import app.ai.parser.mineru_service as ms
from app.ai.parser import mineru_runner as MR


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    """모듈 전역을 매 시험마다 초기화한다 — 사망 표시가 다음 시험으로 새면 안 된다."""
    monkeypatch.setattr(ms, "_engine_dead", False, raising=False)
    monkeypatch.setattr(ms, "_engine_dead_warned", False, raising=False)
    monkeypatch.setattr(ms, "_url", "http://127.0.0.1:30000", raising=False)
    monkeypatch.setattr(ms, "_restarts", 0, raising=False)
    monkeypatch.setattr(ms, "_last_restart", 0.0, raising=False)
    monkeypatch.delenv("MINERU_API_URL", raising=False)
    monkeypatch.delenv("MINERU_PERSISTENT", raising=False)


class TestDeathSignal:
    def test_health가_200이어도_사망_신호가_오면_재기동한다(self):
        """★ 이게 없으면 재기동 길이 **한 번도 안 열린다** — 56쪽 사고의 핵심."""
        ms.report_engine_dead("http://127.0.0.1:30000")
        with patch.object(ms, "_health", return_value=True), \
             patch.object(ms, "stop"), \
             patch.object(ms, "ensure_started", return_value="RESTARTED") as started:
            assert ms.get_url() == "RESTARTED"
        started.assert_called_once()

    def test_신호가_없으면_종전대로_health를_믿는다(self):
        with patch.object(ms, "_health", return_value=True), \
             patch.object(ms, "ensure_started") as started:
            assert ms.get_url() == "http://127.0.0.1:30000"
        started.assert_not_called()

    def test_재기동하면_사망_표시를_내린다(self):
        ms.report_engine_dead()
        with patch.object(ms, "_health", return_value=True), \
             patch.object(ms, "stop"), \
             patch.object(ms, "ensure_started", return_value="RESTARTED"):
            ms.get_url()
        assert ms._engine_dead is False

    def test_다른_서버_이야기는_무시한다(self):
        ms.report_engine_dead("http://other:1234")
        assert ms._engine_dead is False

    def test_외부_서버는_못_살리니_URL을_그대로_준다(self, monkeypatch):
        """남의 서버에 None 을 주면 쪽마다 CLI 가 자기 VLM 을 새로 올려 더 나빠진다(#848)."""
        monkeypatch.setenv("MINERU_API_URL", "http://127.0.0.1:30000")
        ms.report_engine_dead()
        with patch.object(ms, "_health", return_value=True), \
             patch.object(ms, "ensure_started") as started:
            assert ms.get_url() == "http://127.0.0.1:30000"
        started.assert_not_called()


class TestReportedFrom409:
    """처리 경로가 사망을 알려 주는가 — 409 가 유일한 신호다."""

    def _pdf(self, tmp_path: Path) -> Path:
        f = tmp_path / "a.pdf"
        f.write_bytes(b"%PDF-1.7\n")
        return f

    class _Resp:
        def __init__(self, code, text=""):
            self.status_code, self.text, self.content = code, text, b""

    def test_409면_사망을_보고한다(self, tmp_path):
        with patch("app.ai.parser.mineru_runner.requests.post",
                   return_value=self._Resp(409, "EngineDeadError")), \
             patch("app.ai.parser.mineru_service.report_engine_dead") as rep, \
             pytest.raises(RuntimeError):
            MR._post_mineru_api("http://127.0.0.1:30000", self._pdf(tmp_path),
                                tmp_path / "out", 0, "hybrid-engine", "medium", 60)
        rep.assert_called_once()

    def test_보통_실패는_사망이_아니다(self, tmp_path):
        with patch("app.ai.parser.mineru_runner.requests.post",
                   return_value=self._Resp(500, "boom")), \
             patch("app.ai.parser.mineru_service.report_engine_dead") as rep, \
             pytest.raises(RuntimeError):
            MR._post_mineru_api("http://127.0.0.1:30000", self._pdf(tmp_path),
                                tmp_path / "out", 0, "hybrid-engine", "medium", 60)
        rep.assert_not_called()

    def test_정상_응답은_그대로_푼다(self, tmp_path):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("doc/hybrid/doc_content_list.json", "[]")

        class _Ok:
            status_code, text, content = 200, "", buf.getvalue()

        with patch("app.ai.parser.mineru_runner.requests.post", return_value=_Ok()), \
             patch("app.ai.parser.mineru_service.report_engine_dead") as rep:
            MR._post_mineru_api("http://127.0.0.1:30000", self._pdf(tmp_path),
                                tmp_path / "out", 0, "hybrid-engine", "medium", 60)
        rep.assert_not_called()
        assert (tmp_path / "out/doc/hybrid/doc_content_list.json").exists()


class TestRunnerVisibility:
    """폴백을 **도는 동안** 보이게 한다 — 끝 요약만으로는 밤새 못 본다."""

    def test_폴백_판정은_content_list_유무다(self, tmp_path):
        from test.corpus_runner import fell_back
        page = tmp_path / "temp" / "page_007" / "mineru_raw"
        page.mkdir(parents=True)
        assert fell_back(tmp_path, 7, "STANDARD") is True     # 아무것도 안 나왔다
        (page / "doc_content_list.json").write_text("[]", encoding="utf-8")
        assert fell_back(tmp_path, 7, "STANDARD") is False

    def test_ZERO는_원래_MinerU를_안_탄다(self, tmp_path):
        from test.corpus_runner import fell_back
        assert fell_back(tmp_path, 1, "ZERO") is False
        assert fell_back(tmp_path, 1, None) is False

    def test_상태바에_fb가_뜬다(self, capsys):
        from test.corpus_runner import bar
        bar(3, 10, ok=3, review=0, blocked=0, fail=0, to=0, fb=2, eta=0, label="x")
        assert "fb2" in capsys.readouterr().out

    def test_폴백이_0이면_상태바를_안_어지럽힌다(self, capsys):
        from test.corpus_runner import bar
        bar(3, 10, ok=3, review=0, blocked=0, fail=0, to=0, fb=0, eta=0, label="x")
        assert "fb" not in capsys.readouterr().out
