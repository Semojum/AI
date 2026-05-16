"""헬스체크 로직 — GET /health 응답 생성."""

from __future__ import annotations

import time

import torch

from app.core.config import config
from app.core.model_manager import model_manager


def get_health() -> dict:
    status = model_manager.get_status()
    return {
        "status": "ok",
        "grpc_port": config.grpc_port,
        "rest_port": config.rest_port,
        "app_env": config.app_env,
        "models": status,
    }


def get_models_status() -> dict:
    return model_manager.get_status()
