"""모델 매니저 — GPU 정적 배치.

기본(L4 × 2): GPU 0 = Qwen3-VL-8B + YOLO + TableFormer / GPU 1 = HyperCLOVA X 14B
단일 GPU 환경: .env에서 QWEN_GPU_DEVICE=0 HCXT_GPU_DEVICE=0 으로 덮어씀.

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
        self._gpu0_models: dict[str, Any] = {}
        self._gpu1_models: dict[str, Any] = {}

    # ── 기동 시 1회 로드 ──────────────────────────────────────────

    async def load_all(self) -> None:
        """GPU 0과 GPU 1에 모델 스택을 동시 로드."""
        await asyncio.gather(
            self._load_gpu0_stack(),
            self._load_gpu1_stack(),
        )

    async def _load_gpu0_stack(self) -> None:
        """Qwen3-VL-8B + DocLayout-YOLO v2 + Docling TableFormer → cuda:0"""
        await asyncio.to_thread(self._load_qwen)
        await asyncio.to_thread(self._load_yolo)
        await asyncio.to_thread(self._load_tableformer)

    async def _load_gpu1_stack(self) -> None:
        """HyperCLOVA X SEED Think 14B INT4 → cuda:{config.hcxt_gpu_device}"""
        await asyncio.to_thread(self._load_hcxt)

    # ── 내부 로더 ─────────────────────────────────────────────────

    def _load_qwen(self) -> None:
        logger.info("Qwen3-VL-8B AWQ 로드: %s", config.qwen3_vl_model_path)
        try:
            from awq import AutoAWQForCausalLM
            from transformers import AutoProcessor
            self._gpu0_models["qwen"] = AutoAWQForCausalLM.from_quantized(
                config.qwen3_vl_model_path,
                fuse_layers=True,
                device_map=f"cuda:{config.qwen_gpu_device}",
            )
            self._gpu0_models["qwen_processor"] = AutoProcessor.from_pretrained(
                config.qwen3_vl_model_path
            )
            logger.info("Qwen3-VL-8B AWQ 로드 완료")
        except Exception as exc:
            # 치명적 중단 대신 격리: qwen=None → property RuntimeError → layout/ocr가 빈 결과로
            # 격리. 모델 하나 없다고 서버 전체가 안 뜨는 것을 막는다(요소 격리 철학).
            logger.exception("Qwen3-VL-8B 로드 실패 — 레이아웃/OCR 비활성, 서버는 계속: %s", exc)
            self._gpu0_models["qwen"] = None
            self._gpu0_models["qwen_processor"] = None

    def _load_yolo(self) -> None:
        logger.info("DocLayout-YOLO v2 로드: %s", config.doclayout_yolo_path)
        try:
            from ultralytics import YOLO
            self._gpu0_models["yolo"] = YOLO(config.doclayout_yolo_path).to(f"cuda:{config.qwen_gpu_device}")
            logger.info("DocLayout-YOLO v2 로드 완료")
        except Exception as exc:
            logger.warning("DocLayout-YOLO 로드 실패 (보조 모델, 계속 진행): %s", exc)
            self._gpu0_models["yolo"] = None

    def _load_tableformer(self) -> None:
        logger.info("Docling TableFormer 로드: %s", config.docling_tableformer_path)
        try:
            from docling.models.tableformer_model import TableFormerModel
            self._gpu0_models["tableformer"] = TableFormerModel(
                config.docling_tableformer_path, device=f"cuda:{config.qwen_gpu_device}"
            )
            logger.info("Docling TableFormer 로드 완료")
        except Exception as exc:
            logger.warning("TableFormer 로드 실패 (단계 4 필요, 계속 진행): %s", exc)
            self._gpu0_models["tableformer"] = None

    def _load_hcxt(self) -> None:
        logger.info("HyperCLOVA X SEED Think 14B INT4 로드: %s", config.hcxt_model_path)
        try:
            from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig
            quant_cfg = BitsAndBytesConfig(
                load_in_4bit=True,
                bnb_4bit_compute_dtype=torch.float16,
                bnb_4bit_use_double_quant=True,
                bnb_4bit_quant_type="nf4",
            )
            self._gpu1_models["hcxt"] = AutoModelForCausalLM.from_pretrained(
                config.hcxt_model_path,
                quantization_config=quant_cfg,
                device_map=f"cuda:{config.hcxt_gpu_device}",
                trust_remote_code=True,  # HyperCLOVA X = 커스텀 모델 코드. 미지정 시 백그라운드
                                         # 스레드에서 동의 prompt(SIGALRM) 시도 → signal 오류로 로드 실패.
            )
            self._gpu1_models["hcxt_tokenizer"] = AutoTokenizer.from_pretrained(
                config.hcxt_model_path,
                trust_remote_code=True,
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
    def qwen_model(self) -> Any:
        m = self._gpu0_models.get("qwen")
        if m is None:
            raise RuntimeError("Qwen3-VL 로드되지 않음. load_all() 먼저 호출 필요.")
        return m

    @property
    def qwen_processor(self) -> Any:
        p = self._gpu0_models.get("qwen_processor")
        if p is None:
            raise RuntimeError("Qwen3-VL 프로세서 로드되지 않음.")
        return p

    @property
    def yolo_model(self) -> Any:
        return self._gpu0_models.get("yolo")  # None이면 yolo_layout.py에서 스킵

    @property
    def tableformer(self) -> Any:
        return self._gpu0_models.get("tableformer")  # None이면 table_cap.py에서 스킵

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
        return {
            "gpu0": {
                "qwen_loaded": "qwen" in self._gpu0_models,
                "yolo_loaded": self._gpu0_models.get("yolo") is not None,
                "tableformer_loaded": self._gpu0_models.get("tableformer") is not None,
            },
            "gpu1": {
                "hcxt_loaded": "hcxt" in self._gpu1_models,
            },
            "gpu_available": torch.cuda.is_available(),
            "gpu_count": torch.cuda.device_count() if torch.cuda.is_available() else 0,
        }


model_manager = ModelManager()
