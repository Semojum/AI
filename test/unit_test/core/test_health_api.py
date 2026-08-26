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
