from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ── 서버 ──────────────────────────────────────────────────────
    grpc_port: int = 50051
    rest_port: int = 8080
    app_env: str = "production"  # "debug" 시 중간 산출물 JSON 저장

    # ── 타임아웃 / 임계값 ─────────────────────────────────────────
    page_timeout_seconds: float = 300.0
    ocr_confidence_threshold: float = 0.90
    max_grpc_message_mb: int = 20

    # ── 모델 경로 ─────────────────────────────────────────────────
    qwen3_vl_model_path: str = "/models/qwen3-vl-8b-awq"
    hcxt_model_path: str = "/models/hyperclovax-seed-think-14b"
    doclayout_yolo_path: str = "/models/doclayout-yolo-v2"
    docling_tableformer_path: str = "/models/docling-tableformer"

    # ── GPU 디바이스 배치 ─────────────────────────────────────────
    # L4 × 2: QWEN_GPU_DEVICE=0  HCXT_GPU_DEVICE=1  (기본값)
    # RTX 4090 Laptop (단일): QWEN_GPU_DEVICE=0  HCXT_GPU_DEVICE=0
    qwen_gpu_device: int = 0
    hcxt_gpu_device: int = 1

    # ── 외부 서비스 ───────────────────────────────────────────────
    formulanet_service_addr: str = "localhost:50052"
    chromadb_url: str = "http://localhost:8001"
    timescaledb_url: str = "postgresql://user:pass@localhost:5432/semojum_metrics"

    # ── TLS ───────────────────────────────────────────────────────
    tls_enabled: bool = True
    tls_cert_path: str = "/etc/ssl/semojum/server.crt"
    tls_key_path: str = "/etc/ssl/semojum/server.key"

    # ── API (GPT-4o 캡셔닝/분류, GPT-5.x FALLBACK) ───────────────
    openai_api_key: str = ""

    @property
    def is_debug(self) -> bool:
        return self.app_env.lower() == "debug"

    @property
    def max_grpc_message_bytes(self) -> int:
        return self.max_grpc_message_mb * 1024 * 1024


@lru_cache
def get_settings() -> Settings:
    return Settings()


config: Settings = get_settings()
