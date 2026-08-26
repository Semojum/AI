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
        """환경변수도 .env도 없으면 PATH에 맡긴다.

        ★ 2026-08-09 — `config.mineru_bin`(.env) 폴백이 생겨서 환경변수만 지우면
          부족하다. 이 기계의 .env에는 vLLM 경로가 들어 있어 그게 이긴다.
          우선순위는 `환경변수 > .env > PATH`이므로 **둘 다** 비워야 PATH 경로를 본다.
        """
        monkeypatch.delenv("MINERU_BIN", raising=False)
        monkeypatch.setattr(ms.config, "mineru_bin", "", raising=False)
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
        """URL을 모르면 None.

        ★ 2026-08-09 — `_url=None`만으로는 부족해졌다. get_url이 죽은 서비스를 **되살리려
          시도**하므로(#142), 개발 기계에 mineru-api가 실제로 떠 있으면 그걸 잡아 온다.
          이 테스트가 보려는 건 "모르면 None"이지 "재기동이 되는가"가 아니므로,
          우리가 띄운 게 아닌 상태(외부 URL 지정)로 고정해 재기동 경로를 끈다.
        """
        monkeypatch.setattr(ms, "_url", None)
        monkeypatch.setenv("MINERU_PERSISTENT", "0")      # 자동 기동 비활성 = 되살리지 않는다
        assert ms.get_url() is None


class TestConcurrency:
    """vLLM이 아닌 엔진에서 동시 2를 던지면 MinerU가 스레드 레이스로 터진다.

    실측(2026-08-26, 로그 2,171쪽 전수): 텍스트레이어 폴백 142쪽(6.5%) 중 **102쪽(72%)**이
      RuntimeError: The expanded size of the tensor (2) must match the existing size (0)
    이었다. 폴백 쪽은 표·그림 구조를 잃는다 — 시연 지적 1번(표가 텍스트로 풀림)이 이것이다.
    """

    def test_vLLM이면_설정값_그대로(self, monkeypatch):
        monkeypatch.setattr(ms.config, "mineru_max_concurrent", 4, raising=False)
        monkeypatch.setattr(ms, "_engine_is_vllm", lambda: True)
        assert ms.concurrency() == 4

    def test_transformers면_1로_조인다(self, monkeypatch):
        monkeypatch.setattr(ms.config, "mineru_max_concurrent", 4, raising=False)
        monkeypatch.setattr(ms, "_engine_is_vllm", lambda: False)
        assert ms.concurrency() == 1

    def test_설정이_1이면_엔진과_무관하게_1(self, monkeypatch):
        monkeypatch.setattr(ms.config, "mineru_max_concurrent", 1, raising=False)
        monkeypatch.setattr(ms, "_engine_is_vllm", lambda: True)
        assert ms.concurrency() == 1


class TestEngineDetect:
    def test_bin_옆에_vllm이_있으면_vLLM(self, tmp_path, monkeypatch):
        (tmp_path / "mineru").write_text("")
        (tmp_path / "vllm").write_text("")
        monkeypatch.setenv("MINERU_BIN", str(tmp_path / "mineru"))
        assert ms._engine_is_vllm() is True

    def test_bin_옆에_vllm이_없으면_transformers(self, tmp_path, monkeypatch):
        (tmp_path / "mineru").write_text("")
        monkeypatch.setenv("MINERU_BIN", str(tmp_path / "mineru"))
        assert ms._engine_is_vllm() is False
