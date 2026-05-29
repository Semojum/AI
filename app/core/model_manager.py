"""모델 매니저 — 2-GPU 정적 배치.

GPU 0: Qwen3-VL-8B INT4 AWQ + DocLayout-YOLO v2 + Docling TableFormer
GPU 1: HyperCLOVA X SEED Think 14B INT4

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
        """HyperCLOVA X SEED Think 14B INT4 → cuda:1"""
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
                device_map="cuda:0",
            )
            self._gpu0_models["qwen_processor"] = AutoProcessor.from_pretrained(
                config.qwen3_vl_model_path
            )
            logger.info("Qwen3-VL-8B AWQ 로드 완료")
        except Exception as exc:
            logger.exception("Qwen3-VL-8B 로드 실패: %s", exc)
            raise

    def _load_yolo(self) -> None:
        logger.info("DocLayout-YOLO v2 로드: %s", config.doclayout_yolo_path)
        try:
            from ultralytics import YOLO
            self._gpu0_models["yolo"] = YOLO(config.doclayout_yolo_path)
            logger.info("DocLayout-YOLO v2 로드 완료")
        except Exception as exc:
            logger.warning("DocLayout-YOLO 로드 실패 (보조 모델, 계속 진행): %s", exc)
            self._gpu0_models["yolo"] = None

    def _load_tableformer(self) -> None:
        logger.info("Docling TableFormer 로드: %s", config.docling_tableformer_path)
        try:
            from docling.models.tableformer_model import TableFormerModel
            self._gpu0_models["tableformer"] = TableFormerModel(
                config.docling_tableformer_path, device="cuda:0"
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
                device_map="cuda:1",
                trust_remote_code=True,
            )
            self._gpu1_models["hcxt_tokenizer"] = AutoTokenizer.from_pretrained(
                config.hcxt_model_path,
                trust_remote_code=True,
            )
            logger.info("HyperCLOVA X SEED Think 14B INT4 로드 완료")
        except Exception as exc:
            logger.exception("HyperCLOVA X 14B 로드 실패: %s", exc)
            raise

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
