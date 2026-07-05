"""모델 매니저 — GPU 정적 배치.

현재 아키텍처(MinerU 전환): 현주 추출(레이아웃·OCR·수식·표)은 MinerU2.5-Pro가
subprocess(`mineru_runner`)로 처리하므로 이 매니저는 더 이상 Qwen3-VL·DocLayout-YOLO·
Docling TableFormer를 상주 로드하지 않는다. 여기서 상시 로드하는 모델은
**태민 점역 최적화용 HyperCLOVA X(HCXT)** 하나다.

서버 기동 시 load_all() 1회 호출 → 이후 상시 상주. VRAM Swap 없음.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import torch

from app.core.config import config

logger = logging.getLogger(__name__)


class ModelManager:
    _instance: "ModelManager | None" = None

    def __new__(cls) -> "ModelManager":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self) -> None:
        if self._initialized:
            return
        self._initialized = True
        self._gpu1_models: dict[str, Any] = {}

    # ── 기동 시 1회 로드 ──────────────────────────────────────────

    async def load_all(self) -> None:
        """상주 모델 로드. 현재는 HCXT 하나 (추출은 MinerU subprocess 담당)."""
        await asyncio.to_thread(self._load_hcxt)

    # ── 내부 로더 ─────────────────────────────────────────────────

    def _load_hcxt(self) -> None:
        if config.hcxt_backend == "vllm":
            # 14B는 별도 vLLM 서버가 보유(AWQ self-host 권장). 파이프라인은 추론을 HTTP로 요청만
            # 하므로 인프로세스 로드가 없다(VRAM은 서버가 사용). 추론 경로 = hcxt_client.vllm_generate.
            self._gpu1_models["hcxt"] = None
            self._gpu1_models["hcxt_tokenizer"] = None
            logger.info("HCXT 백엔드=vLLM: 인프로세스 로드 생략 (서버 %s, 모델명 %s)",
                        config.hcxt_vllm_url, config.hcxt_vllm_model)
            return
        logger.info("HyperCLOVA X SEED Think 14B INT4 로드: %s", config.hcxt_model_path)
        try:
            from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig
            quant_cfg = BitsAndBytesConfig(
                load_in_4bit=True,
                bnb_4bit_compute_dtype=torch.float16,
                bnb_4bit_use_double_quant=True,
                bnb_4bit_quant_type="nf4",
            )
            # transformers>=5.9.0 의 네이티브 hyperclovax 클래스를 사용한다.
            # 모델 config 의 auto_map(커스텀 .py 참조)은 폴더에 .py가 없으므로 쓰지 않는다
            # → trust_remote_code=False 로 네이티브 경로 강제(백그라운드 스레드에서 prompt 방지).
            self._gpu1_models["hcxt"] = AutoModelForCausalLM.from_pretrained(
                config.hcxt_model_path,
                quantization_config=quant_cfg,
                device_map=f"cuda:{config.hcxt_gpu_device}",
                trust_remote_code=False,
            )
            self._gpu1_models["hcxt_tokenizer"] = AutoTokenizer.from_pretrained(
                config.hcxt_model_path,
                trust_remote_code=False,
            )
            logger.info("HyperCLOVA X SEED Think 14B INT4 로드 완료")
            # CUDA JIT 커널 선컴파일 — 첫 실제 추론의 지연(~20s) 방지
            self._warmup_hcxt()
        except Exception as exc:
            # 치명적 중단 대신 격리: hcxt=None → property RuntimeError → opt가 fallback/passthrough.
            # QUALITY 최적화만 비활성되고 ZERO/규칙 기반 경로·서버는 정상 기동.
            logger.exception("HyperCLOVA X 14B 로드 실패 — QUALITY 최적화 비활성, 서버는 계속: %s", exc)
            self._gpu1_models["hcxt"] = None
            self._gpu1_models["hcxt_tokenizer"] = None

    def _warmup_hcxt(self) -> None:
        logger.info("HyperCLOVA X 워밍업 시작")
        try:
            model = self._gpu1_models["hcxt"]
            tokenizer = self._gpu1_models["hcxt_tokenizer"]
            device = next(model.parameters()).device
            inputs = tokenizer("안녕", return_tensors="pt").to(device)
            with torch.no_grad():
                # generation_config.json에 stop string이 박혀 있어 tokenizer를 함께
                # 넘기지 않으면 transformers 5.9가 generate를 거부한다(실추론 경로와 동일).
                model.generate(**inputs, max_new_tokens=5, use_cache=True,
                               pad_token_id=tokenizer.eos_token_id,
                               tokenizer=tokenizer)
            logger.info("HyperCLOVA X 워밍업 완료")
        except Exception as exc:
            logger.warning("HyperCLOVA X 워밍업 실패 (무시): %s", exc)

    # ── 퍼블릭 속성 ───────────────────────────────────────────────

    @property
    def hcxt_model(self) -> Any:
        m = self._gpu1_models.get("hcxt")
        if m is None:
            raise RuntimeError("HyperCLOVA X 로드되지 않음.")
        return m

    @property
    def hcxt_tokenizer(self) -> Any:
        t = self._gpu1_models.get("hcxt_tokenizer")
        if t is None:
            raise RuntimeError("HyperCLOVA X 토크나이저 로드되지 않음.")
        return t

    def get_status(self) -> dict:
        # vllm 백엔드는 별도 서버가 HCXT를 보유 → 사용 가능으로 본다(서버 다운 시 호출부가 폴백).
        vllm = config.hcxt_backend == "vllm"
        return {
            "hcxt_loaded": vllm or (self._gpu1_models.get("hcxt") is not None),
            "hcxt_backend": config.hcxt_backend,
            "extraction": "MinerU2.5-Pro (subprocess)",  # 레이아웃·OCR·표·수식
            "gpu_available": torch.cuda.is_available(),
            "gpu_count": torch.cuda.device_count() if torch.cuda.is_available() else 0,
        }


model_manager = ModelManager()
