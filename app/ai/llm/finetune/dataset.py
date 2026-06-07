"""파인튜닝 데이터셋 빌드 (T5-4).

학습 프롬프트는 **추론과 동일한 opt 프롬프트 템플릿을 재사용**한다 — 학습/추론 분포 일치.
(opt 모듈의 _PROMPT* 문자열을 그대로 가져오므로, 프롬프트를 고치면 학습 데이터도 자동 반영.)

SFT 형식: HCLOVA X chat 템플릿과 동일한 messages 쌍
  [{"role":"user","content":프롬프트}, {"role":"assistant","content":목표}]
"""

from __future__ import annotations

import os
import random
from pathlib import Path

from app.ai.llm.finetune.data_format import TrainingExample, from_jsonl

# 유형 → (프롬프트 템플릿, 입력 필드명). 템플릿은 opt 모듈에서 지연 로드(추론과 단일 출처).
_REGISTRY_CACHE: dict[str, tuple[str, str]] = {}


def _registry() -> dict[str, tuple[str, str]]:
    """유형 → (template, field). opt 모듈의 프롬프트 상수를 재사용(지연 import)."""
    if _REGISTRY_CACHE:
        return _REGISTRY_CACHE
    from app.ai.llm import (
        cartoon_opt,
        chart_graph_opt,
        formula_opt,
        image_opt,
        table_opt,
        text_opt,
    )
    _REGISTRY_CACHE.update({
        "text":        (text_opt._PROMPT_QUALITY, "text"),
        "formula":     (formula_opt._PROMPT, "latex"),
        "table":       (table_opt._PROMPT_TABLE_GRID, "table_text"),
        "image":       (image_opt._PROMPT, "caption"),
        "cartoon":     (cartoon_opt._PROMPT, "caption"),
        "chart_graph": (chart_graph_opt._PROMPT, "caption"),
    })
    return _REGISTRY_CACHE


def build_prompt(ex: TrainingExample) -> str:
    """예시 → 추론과 동일한 프롬프트 문자열."""
    template, field = _registry()[ex.element_type]
    return template.format(**{field: ex.input_text})


def build_chat_pair(ex: TrainingExample) -> dict:
    """예시 → SFT messages 쌍 (HCLOVA X chat 템플릿용)."""
    return {
        "messages": [
            {"role": "user", "content": build_prompt(ex)},
            {"role": "assistant", "content": ex.target_text},
        ]
    }


def load_sft_dataset(path: str | Path) -> list[dict]:
    """JSONL 학습 파일 → SFT chat 쌍 목록."""
    return [build_chat_pair(ex) for ex in from_jsonl(path)]


def set_seed(seed: int = 42) -> None:
    """재현성 고정 — stdlib random + (있으면) numpy·torch. GPU 없이도 동작."""
    os.environ["PYTHONHASHSEED"] = str(seed)
    random.seed(seed)
    try:
        import numpy as np
        np.random.seed(seed)
    except ImportError:
        pass
    try:
        import torch
        torch.manual_seed(seed)
        if torch.cuda.is_available():
            torch.cuda.manual_seed_all(seed)
    except ImportError:
        pass
