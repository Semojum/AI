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
