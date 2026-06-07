"""PART *-2 점역 최적화 LLM 파인튜닝 스켈레톤 (T5-4).

HyperCLOVA X 점역 최적화 태스크(입력 OCR/캡션 → 목표 점역사주)용 파인튜닝 골격.
**코드 골격만** 제공한다 — 실제 학습(GPU·하이퍼파라미터·데이터 규모)은 인프라 담당과 협의.

- `data_format` : 학습 예시 스키마(TrainingExample) + JSONL 입출력
- `dataset`     : 프롬프트 빌드(추론과 동일 템플릿 재사용) + SFT chat 쌍 + 시드 고정
- `train`       : LoRA SFT 학습 스크립트 스켈레톤 (자리만, NotImplementedError)

데이터셋 수집 경로·라이선스는 README.md 참조.
"""

from app.ai.llm.finetune.data_format import (
    ELEMENT_TYPES,
    TrainingExample,
    from_jsonl,
    to_jsonl,
)

__all__ = ["ELEMENT_TYPES", "TrainingExample", "from_jsonl", "to_jsonl"]
