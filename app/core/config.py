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
    page_timeout_seconds: float = 180.0   # 페이지 하드 타임아웃(C7). 운영 정본 = 180초.
    # MinerU 추출 서브 타임아웃(초). 0 = 자동(페이지 예산 - 60초 여유, 최소 60초).
    # 병리적으로 무거운 페이지(C9)에서 MinerU가 페이지 예산을 다 태우고 C7 BLOCKED로
    # 죽는 대신, 추출을 먼저 끊고 텍스트레이어 폴백으로 부분 초안을 살리기 위한 예산.
    mineru_timeout_seconds: float = 0.0
    ocr_confidence_threshold: float = 0.90
    max_grpc_message_mb: int = 20

    # ── HCXT(단일 GPU 직렬 추론) 예산 ─────────────────────────────
    # HCXT는 GPU 하나를 잠그고 요소를 하나씩 처리하므로, 요소당 시간이 크면 페이지 예산을
    # 금방 소진한다(요소 N개 × 상한 = 페이지 초과). 요소당 상한은 작게 두고, 초과·저품질은
    # GPT-4o(락 밖, 병렬)로 폴백한다.
    hcxt_element_timeout_seconds: float = 8.0    # STANDARD 요소당 상한(초)
    hcxt_quality_timeout_seconds: float = 14.0   # QUALITY(저신뢰 스캔) 요소당 상한(초)
    # 페이지 누적 HCXT 상한 = page_timeout × 이 비율. 초과 후 요소는 HCXT를 건너뛰고
    # 곧바로 GPT-4o 병렬 폴백 → 직렬 HCXT가 페이지 예산을 독점하지 못하게 한다.
    hcxt_page_budget_ratio: float = 0.55

    # ── HCXT 추론 백엔드 ─────────────────────────────────────────
    # "transformers"(기본): 인프로세스 bitsandbytes 4bit(단일 GPU 직렬, 락 필요).
    # "vllm": 별도 vLLM OpenAI 호환 서버로 오프로드 — AWQ 양자화 모델 self-host 권장
    #   (bnb는 엔진 바꿔도 이득 없음, 실측 확인). 서버가 배칭/동시성 처리 → 인프로세스 GPU 락·
    #   페이지 누적 예산 불필요, 요소들이 병렬 추론된다. 파이프라인은 토크나이저만 로드(14B는 서버).
    hcxt_backend: str = "transformers"
    hcxt_vllm_url: str = "http://127.0.0.1:8100/v1"   # vLLM OpenAI 호환 엔드포인트
    hcxt_vllm_model: str = "hcxt"                       # --served-model-name 값
    hcxt_vllm_serve_cmd: str = ""                       # 비면 외부 서버 사용, 있으면 이 명령으로 자동 기동
    # vLLM 종료 토큰 id — 문자열 stop(<|endofturn|>/<|stop|>)은 vLLM이 skip_special_tokens=True로
    # 응답에서 지워 stop 매칭이 안 되므로(반복 생성 버그 원인), 특수토큰은 id로 끊어야 한다.
    # HCXT generation_config 기준: 100273=<|endofturn|>, 100274=<|stop|>, 100275=<|endoftext|>.
    hcxt_vllm_stop_token_ids: list[int] = [100273, 100274, 100275]

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
    anthropic_api_key: str = ""   # 폴백·캡셔닝 기본(태민 2026-07-17: openai 대신 anthropic)

    @property
    def is_debug(self) -> bool:
        return self.app_env.lower() == "debug"

    @property
    def mineru_timeout_resolved(self) -> float:
        """MinerU 추출 서브 타임아웃 실효값. 0(자동)이면 페이지 예산 - 60초(최소 60초)."""
        if self.mineru_timeout_seconds > 0:
            return self.mineru_timeout_seconds
        return max(60.0, self.page_timeout_seconds - 60.0)

    @property
    def max_grpc_message_bytes(self) -> int:
        return self.max_grpc_message_mb * 1024 * 1024


@lru_cache
def get_settings() -> Settings:
    return Settings()


config: Settings = get_settings()
