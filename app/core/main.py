"""서버 진입점.

asyncio 이벤트 루프에서 gRPC 서버와 FastAPI REST 서버를 동시에 기동한다.
기동 직후 model_manager.load_all()로 GPU 0/1 모델 상시 로드.

실행:
    python -m app.core.main
"""

from __future__ import annotations

import asyncio
import logging

import uvicorn
from fastapi import FastAPI

from app.core.config import config
from app.core.routes import router
from app.utils.logger import get_logger, setup_root_logging

setup_root_logging(level=logging.DEBUG if config.is_debug else logging.INFO)
logger = get_logger(__name__)


def create_app() -> FastAPI:
    app = FastAPI(
        title="Semojum V2 AI Server",
        version="2.0.0",
        description="AI 점자 번역 파이프라인 — gRPC 기반 페이지 단위 처리",
    )
    app.include_router(router)
    return app


app = create_app()


async def _run_grpc() -> None:
    from app.core.grpc_server import serve
    await serve()


async def _run_rest() -> None:
    uvicorn_config = uvicorn.Config(
        app=app,
        host="0.0.0.0",
        port=config.rest_port,
        log_level="debug" if config.is_debug else "info",
        loop="none",
        ssl_certfile=config.tls_cert_path if config.tls_enabled else None,
        ssl_keyfile=config.tls_key_path if config.tls_enabled else None,
    )
    server = uvicorn.Server(uvicorn_config)
    await server.serve()


async def main() -> None:
    logger.info(
        "Semojum V2 AI Server 시작 — gRPC:%d REST:%d env:%s",
        config.grpc_port,
        config.rest_port,
        config.app_env,
    )

    # GPU 0/1 모델 상시 로드 (서버 기동 시 1회)
    from app.core.model_manager import model_manager
    logger.info("GPU 0/1 모델 로드 시작...")
    await model_manager.load_all()
    logger.info("GPU 0/1 모델 로드 완료")

    await asyncio.gather(_run_grpc(), _run_rest())


if __name__ == "__main__":
    asyncio.run(main())
