"""health_check API 단위 테스트."""

from unittest.mock import patch

import pytest


class TestHealthCheck:

    @patch("app.core.health_check.model_manager")
    def test_health_returns_dict(self, mock_mm) -> None:
        mock_mm.get_status.return_value = {}
        from app.core.health_check import get_health
        result = get_health()
        assert isinstance(result, dict)

    @patch("app.core.health_check.model_manager")
    def test_health_has_status_ok(self, mock_mm) -> None:
        mock_mm.get_status.return_value = {}
        from app.core.health_check import get_health
        result = get_health()
        assert result.get("status") == "ok"

    @patch("app.core.health_check.model_manager")
    def test_health_has_grpc_port(self, mock_mm) -> None:
        mock_mm.get_status.return_value = {}
        from app.core.health_check import get_health
        result = get_health()
        assert "grpc_port" in result


class TestHealthBuildInfo:
    """서버가 **어느 판인가**를 밖에서 볼 수 있어야 한다.

    오늘 하루에 네 번, "우리 판에서는 되는데 서버에서는 안 된다"를 판이 다른 줄 모르고 팠다.
    """

    def test_판_정보가_실린다(self):
        from app.core.health_check import _build_info
        b = _build_info()
        for k in ("commit", "caption_prompt_sha", "caption_backend",
                  "caption_model", "caption_key", "caption_cache"):
            assert k in b, k

    def test_프롬프트_해시는_프롬프트를_문다(self):
        """프롬프트를 고치면 해시가 바뀌어야 한다 — 안 그러면 판을 못 가른다."""
        import hashlib
        from app.ai.captioning.captioner import _COMMON, _PROMPTS
        from app.core.health_check import _build_info
        blob = _COMMON + "".join(f"{k}{v}" for k, v in sorted(_PROMPTS.items()))
        assert _build_info()["caption_prompt_sha"] == hashlib.sha256(blob.encode()).hexdigest()[:12]

    def test_키는_유무만_싣는다(self):
        """★ 값은 절대 안 싣는다. 헬스체크는 인증 없이 열려 있을 수 있다."""
        from app.core.health_check import _build_info
        assert _build_info()["caption_key"] in (True, False)

    def test_캐시가_꺼져_있어도_찍힌다(self):
        """꺼짐 자체가 정보다 — 그걸 알아야 '캐시 탓' 을 가른다."""
        from app.core.health_check import _build_info
        cc = _build_info()["caption_cache"]
        assert set(cc) == {"enabled", "entries"}


# ── 캡셔닝 키 유무를 캡셔너와 같은 자리에서 읽는다 (2026-08-27) ─────────────
# 키는 `.env` 로 들어오고 pydantic-settings 는 그것을 config 에만 싣는다 — os.environ 에는
# 안 싣는다. os.getenv 로 읽으면 키가 `.env` 에만 있는 서버에서 **거짓 경보**가 난다
# (실측: os.getenv False · config True, 캡셔닝은 정상).

def test_캡셔닝_키는_캡셔너와_같은_자리에서_읽는다(monkeypatch):
    from app.core import health_check as hc
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    # conftest 가 실호출을 막으려 CAPTION_BACKEND=openai 로 고정한다 — 여기선 anthropic 경로를 본다
    monkeypatch.setenv("CAPTION_BACKEND", "anthropic")
    from app.ai.captioning import captioner
    monkeypatch.setattr(captioner.config, "anthropic_api_key", "sk-ant-x")
    hc._build_info.cache_clear()
    assert hc._build_info()["caption_key"] is True
    hc._build_info.cache_clear()


def test_키가_없으면_health_가_경고를_단다(monkeypatch):
    """배포는 `.env` 를 안 실어 나른다(RUNBOOK §8-4: git pull · protoc · restart).
    키가 빠져도 배포는 성공으로 끝나므로 health 가 사람에게 알려야 한다."""
    from app.core import health_check as hc
    from app.ai.captioning import captioner
    monkeypatch.setattr(captioner.config, "anthropic_api_key", "")
    monkeypatch.setattr(captioner.config, "openai_api_key", "", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    hc._build_info.cache_clear()
    h = hc.get_health()
    assert h["build"]["caption_key"] is False
    assert h["status"] == "ok"                 # BE 계약이라 건드리지 않는다
    assert any("생략" in w for w in h.get("warnings", []))
    hc._build_info.cache_clear()


def test_키가_있으면_경고가_없다(monkeypatch):
    from app.core import health_check as hc
    from app.ai.captioning import captioner
    monkeypatch.setenv("CAPTION_BACKEND", "anthropic")   # conftest 가 openai 로 고정한다
    monkeypatch.setattr(captioner.config, "anthropic_api_key", "sk-ant-x")
    hc._build_info.cache_clear()
    assert "warnings" not in hc.get_health()
    hc._build_info.cache_clear()
