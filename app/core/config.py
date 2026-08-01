from __future__ import annotations

from functools import lru_cache

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# HCXT 추론 백엔드 허용값 — 아래 hcxt_backend 주석 참조.
_HCXT_BACKENDS = {"off", "transformers", "vllm"}


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
    # MinerU 추출 서브 타임아웃(초). 0 = 자동(아래 mineru_timeout_resolved).
    # 병리적으로 무거운 페이지(C9)에서 MinerU가 페이지 예산을 다 태우고 C7 BLOCKED로
    # 죽는 대신, 추출을 먼저 끊고 텍스트레이어 폴백으로 부분 초안을 살리기 위한 예산.
    mineru_timeout_seconds: float = 0.0
    ocr_confidence_threshold: float = 0.90
    max_grpc_message_mb: int = 20

    # ── 동시 처리 상한 (M2, 2026-07-28 결정) ─────────────────────
    # 한 서버가 동시에 붙잡는 페이지 수. 초과 요청은 gRPC가 큐에 세운다.
    # 상한이 없으면 요청이 몰릴 때 전부 동시에 진행되어 각 페이지가 느려지고,
    # 180초 페이지 예산에 뒤쪽 요청이 통째로 걸린다(C7).
    # 1차 = 2, 2차 개발부터 5로 확대.
    max_concurrent_pages: int = 2
    # MinerU 추출 서버(mineru-api)의 동시 요청 허용치.
    # 2026-08-02 4→2. 처리량 무릎이 2다 — 실측(effort=medium, RTX 4090 Laptop):
    #   동시 1: 쪽당 7.75s · 0.129쪽/s
    #   동시 2: 쪽당 8.97s · 0.218쪽/s   ← 무릎
    #   동시 4: 쪽당 13.86s · 0.217쪽/s  ← 처리량 이득 0인데 최대 지연 21.4→36.9초
    # 2→4는 처리량을 못 올리면서 꼬리만 늘린다. 꼬리가 늘면 추출 상한(비정상 탐지기)에
    # 걸리는 정상 페이지가 생기므로 무릎을 넘길 이유가 없다.
    # ⚠ vCPU보다 크게 잡으면 CPU가 병목이 된다(g4dn.xlarge·g5.xlarge는 vCPU 4).
    # ⚠ 위 수치는 전부 개발 랩탑 값이다. 운영(A10G 24GB)에서 무릎을 다시 재라.
    mineru_max_concurrent: int = 2

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
    # "off"(기본, 2026-08-02): HCXT를 아예 쓰지 않는다. 모델 로드도 추론 시도도 하지 않고
    #   곧바로 외부 API 폴백(base_opt.fallback_optimize)으로 간다.
    #   근거 = 1차 PoC 품질 비교에서 HCXT가 탈락(태깅 실문장 48/100 vs claude-sonnet-5 91/100,
    #   실패 47건 중 46건이 본문 훼손. 8초 상한 초과는 0/100이라 "느려서"가 아니라 "틀려서" 탈락).
    #   ★ 폐기가 아니라 비활성이다 — 모델 파일(models/hcxt·hcxt-gptq)과 아래 배선·서빙
    #   스크립트는 보존한다. 되살리려면 이 값을 "vllm"으로 바꾸고 vLLM 서버를 띄우면 된다
    #   (기동 인자는 model_manager._load_hcxt 주석 참조).
    # "transformers": 인프로세스 bitsandbytes 4bit(단일 GPU 직렬, 락 필요).
    # "vllm": 별도 vLLM OpenAI 호환 서버로 오프로드 — AWQ 양자화 모델 self-host 권장
    #   (bnb는 엔진 바꿔도 이득 없음, 실측 확인). 서버가 배칭/동시성 처리 → 인프로세스 GPU 락·
    #   페이지 누적 예산 불필요, 요소들이 병렬 추론된다. 파이프라인은 토크나이저만 로드(14B는 서버).
    hcxt_backend: str = "off"
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

    @field_validator("hcxt_backend")
    @classmethod
    def _check_hcxt_backend(cls, v: str) -> str:
        """오타가 조용히 transformers 경로로 새는 것을 막는다(기본이 off인 이상 치명적).

        예: HCXT_BACKEND=of / vLLM / "" → 분기가 전부 else로 떨어져 14B를 GPU에 올려버린다.
        """
        v = (v or "").strip().lower()
        if v not in _HCXT_BACKENDS:
            raise ValueError(
                f"hcxt_backend={v!r} 은(는) 허용되지 않는다. 가능한 값: {sorted(_HCXT_BACKENDS)}"
            )
        return v

    @property
    def hcxt_enabled(self) -> bool:
        """HCXT 추론을 시도할지 여부. off면 로드도 추론도 하지 않고 곧바로 외부 API 폴백."""
        return self.hcxt_backend != "off"

    @property
    def is_debug(self) -> bool:
        return self.app_env.lower() == "debug"

    @property
    def mineru_timeout_resolved(self) -> float:
        """MinerU 추출 서브 타임아웃 실효값. 0(자동)이면 60초.

        2026-08-02 120초 → 60초. 이 상한은 성능 조절기가 아니라 **비정상 탐지기 + 사용자
        인내 한계**다. 그 목적에 맞는지 실측으로 확인했다.

        ① 비정상 탐지 — 정상 페이지의 꼬리가 어디서 끊기나
           코퍼스 60쪽 무작위 표본(effort=medium, 동시 2, RTX 4090 Laptop):
             p50 6.8s · p90 14.5s · p95 33.3s · p99·최대 36.6s
           60초는 정상 최대의 1.6배이고 표본 0/60이 걸린다 → 넘으면 비정상으로 볼 만하다.
           40초는 1.1배라 여유가 없어 무거운 정상 페이지를 끊을 위험이 실재한다.
           종전 120초는 3.3배 — 병리 페이지가 페이지 예산을 다 태울 여유를 준다.

        ② 사용자 대기 한계 — 남는 120초로 뒷단이 되나
           캡셔닝(외부 API, 동시 4): 요소당 8.9초 실측 · 시각요소 p99 7개 → 2웨이브 ≈ 18초
           규칙기반(opt+점역+조판): 코퍼스 1131쪽 메트릭 p99 0.9초 · 최대 1.6초
           합쳐 최악 ~30초. 120초는 충분하다(재시도 2회를 다 써도 남는다).

        ③ 상한에 걸리면 무엇이 살아남나
           `pipeline._fallback_text_layer` — 텍스트레이어가 있으면 본문을 살려
           NEEDS_REVIEW로 응답한다(표·그림 구조는 잃는다). 페이지 통째 BLOCKED가 아니다.
           스캔 전용(레이어 없음)만 빈 결과로 격리된다.

        ⚠ 위 수치는 전부 개발 랩탑 값이다. 운영(A10G 24GB)에서 꼬리를 다시 재고 정할 것.
        ⚠ 페이지 예산이 줄면 뒷단 몫(60초)을 먼저 지킨다 — 그래서 min을 건다.
        """
        if self.mineru_timeout_seconds > 0:
            return self.mineru_timeout_seconds
        return max(10.0, min(60.0, self.page_timeout_seconds - 60.0))

    @property
    def max_grpc_message_bytes(self) -> int:
        return self.max_grpc_message_mb * 1024 * 1024


@lru_cache
def get_settings() -> Settings:
    return Settings()


config: Settings = get_settings()
