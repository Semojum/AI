"""파인튜닝 학습 스크립트 스켈레톤 (T5-4).

★ 코드 골격만 — 실제 학습은 인프라 담당과 협의 후 진행한다.
   GPU·VRAM·데이터 규모·하이퍼파라미터가 확정되지 않았으므로 학습 루프는 NotImplementedError로
   막아 두고, 데이터 로드·시드 고정·LoRA/Trainer 설정 '자리'만 채워 둔다.

무거운 의존성(torch·transformers·peft·trl)은 함수 안에서 지연 import — 이 모듈을 import해도
GPU 라이브러리가 없으면 부담이 없다(단위 테스트·CI GPU-free).

예) python -m app.ai.llm.finetune.train --data data/sft_train.jsonl --out runs/braille-lora
"""

from __future__ import annotations

import argparse
import logging
from dataclasses import dataclass, field
from pathlib import Path

from app.ai.llm.finetune.dataset import load_sft_dataset, set_seed

logger = logging.getLogger(__name__)

# 베이스 모델 — model_manager와 동일 체크포인트로 맞춘다(추론/학습 일치). 실값은 인프라와 확정.
DEFAULT_BASE_MODEL = "naver-hyperclovax/HyperCLOVAX-SEED-Think-14B"


@dataclass
class LoRAConfig:
    """LoRA/어댑터 설정 자리. target_modules는 모델 구조 확인 후 확정."""
    r: int = 16
    alpha: int = 32
    dropout: float = 0.05
    target_modules: tuple[str, ...] = ("q_proj", "k_proj", "v_proj", "o_proj")
    bias: str = "none"
    task_type: str = "CAUSAL_LM"


@dataclass
class TrainConfig:
    """학습 설정 자리. 실제 값(에폭·lr·배치)은 인프라 담당과 협의."""
    data_path: str
    output_dir: str
    base_model: str = DEFAULT_BASE_MODEL
    epochs: int = 3
    learning_rate: float = 2e-4
    batch_size: int = 1
    grad_accum: int = 16
    max_seq_len: int = 2048
    seed: int = 42
    bf16: bool = True
    lora: LoRAConfig = field(default_factory=LoRAConfig)


def _build_argparser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="점역 최적화 LoRA SFT (스켈레톤)")
    p.add_argument("--data", required=True, help="학습 JSONL (TrainingExample)")
    p.add_argument("--out", required=True, help="어댑터 출력 디렉토리")
    p.add_argument("--base-model", default=DEFAULT_BASE_MODEL)
    p.add_argument("--epochs", type=int, default=3)
    p.add_argument("--lr", type=float, default=2e-4)
    p.add_argument("--batch-size", type=int, default=1)
    p.add_argument("--seed", type=int, default=42)
    return p


def run(cfg: TrainConfig) -> None:
    """학습 진입점 스켈레톤. 데이터 로드·시드까지 수행하고 실제 학습은 막아 둔다."""
    set_seed(cfg.seed)

    data_path = Path(cfg.data_path)
    if not data_path.exists():
        raise FileNotFoundError(f"학습 데이터 없음: {data_path}")
    sft_pairs = load_sft_dataset(data_path)
    logger.info("SFT 예시 %d건 로드 (%s)", len(sft_pairs), data_path)
    if not sft_pairs:
        raise ValueError("학습 데이터가 비어 있음 — 점역사 정답 예시를 먼저 수집하세요.")

    # ── 이하 자리만(인프라 협의 후 구현) ──────────────────────────────────
    # import torch
    # from transformers import AutoModelForCausalLM, AutoTokenizer
    # from peft import LoraConfig, get_peft_model
    # from trl import SFTTrainer, SFTConfig
    # from datasets import Dataset
    #
    # tokenizer = AutoTokenizer.from_pretrained(cfg.base_model)
    # model = AutoModelForCausalLM.from_pretrained(cfg.base_model, torch_dtype=torch.bfloat16)
    # model = get_peft_model(model, LoraConfig(
    #     r=cfg.lora.r, lora_alpha=cfg.lora.alpha, lora_dropout=cfg.lora.dropout,
    #     target_modules=list(cfg.lora.target_modules), bias=cfg.lora.bias,
    #     task_type=cfg.lora.task_type,
    # ))
    # ds = Dataset.from_list(sft_pairs)   # build_chat_pair → tokenizer.apply_chat_template
    # trainer = SFTTrainer(model=model, train_dataset=ds, args=SFTConfig(
    #     output_dir=cfg.output_dir, num_train_epochs=cfg.epochs,
    #     learning_rate=cfg.learning_rate, per_device_train_batch_size=cfg.batch_size,
    #     gradient_accumulation_steps=cfg.grad_accum, bf16=cfg.bf16, seed=cfg.seed,
    # ))
    # trainer.train()
    # trainer.save_model(cfg.output_dir)
    raise NotImplementedError(
        "학습 루프는 스켈레톤입니다(T5-4). GPU·하이퍼파라미터·데이터 규모를 "
        "인프라 담당과 확정한 뒤 위 주석 블록을 구현하세요."
    )


def main(argv: list[str] | None = None) -> None:
    logging.basicConfig(level=logging.INFO)
    args = _build_argparser().parse_args(argv)
    cfg = TrainConfig(
        data_path=args.data, output_dir=args.out, base_model=args.base_model,
        epochs=args.epochs, learning_rate=args.lr, batch_size=args.batch_size, seed=args.seed,
    )
    run(cfg)


if __name__ == "__main__":
    main()
