"""파인튜닝 데이터 포맷 (T5-4).

학습 예시 1건 = 한 요소의 (입력 OCR/캡션 → 목표 점역사주/교정 텍스트).
저장 형식은 JSONL(한 줄에 한 예시) — 스트리밍 로드·버전 관리·diff에 유리.

목표(target_text)는 **점역사가 작성·승인한 정답**이어야 한다(모델 출력 자가학습 금지 —
순환 학습 방지, test_guide 순환검증 금지 원칙과 동일 맥락).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Iterable

from pydantic import BaseModel, Field

# 점역 최적화 대상 요소 유형 (opt 모듈과 1:1). text·formula는 교정, 나머지는 점역사주 생성.
ELEMENT_TYPES = ("text", "formula", "table", "image", "cartoon", "chart_graph")


class TrainingExample(BaseModel):
    """파인튜닝 학습 예시 1건 (Pydantic v2)."""

    element_type: str = Field(description="요소 유형 — ELEMENT_TYPES 중 하나")
    input_text: str = Field(description="프롬프트에 들어갈 입력 (OCR 텍스트·GPT-4o 캡션·LaTeX)")
    target_text: str = Field(description="점역사가 작성·승인한 목표 출력 (점역사주 또는 교정 텍스트)")
    source: str = Field(default="", description="출처 메타 (교과서·페이지 등, 라이선스 추적용)")
    tier: str = Field(default="QUALITY", description="수집 티어 (STANDARD/QUALITY/FALLBACK)")

    def model_post_init(self, __context) -> None:  # noqa: D401
        if self.element_type not in ELEMENT_TYPES:
            raise ValueError(
                f"element_type는 {ELEMENT_TYPES} 중 하나여야 함: {self.element_type!r}"
            )


def to_jsonl(examples: Iterable[TrainingExample], path: str | Path) -> int:
    """예시 목록을 JSONL로 저장. 저장한 건수를 반환."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    n = 0
    with path.open("w", encoding="utf-8") as f:
        for ex in examples:
            f.write(json.dumps(ex.model_dump(), ensure_ascii=False) + "\n")
            n += 1
    return n


def from_jsonl(path: str | Path) -> list[TrainingExample]:
    """JSONL → TrainingExample 목록. 빈 줄은 건너뛴다."""
    path = Path(path)
    out: list[TrainingExample] = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            out.append(TrainingExample.model_validate(json.loads(line)))
    return out
