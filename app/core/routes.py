"""REST 엔드포인트 — 헬스체크·모델 상태 조회 전용.

점자 변환 요청은 반드시 gRPC (grpc_server.py) 로만 처리한다.
"""

from __future__ import annotations

from fastapi import APIRouter

router = APIRouter()


@router.get("/health")
async def health_check():
    from app.core.health_check import get_health
    return get_health()


@router.get("/models/status")
async def models_status():
    from app.core.health_check import get_models_status
    return get_models_status()
