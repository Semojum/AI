"""PART 7-2 — 이미지 점역 최적화 (HyperCLOVA X SEED Think 14B INT4, GPU 1).

GPT-4o 캡션 → HyperCLOVA X → 점역사주 TN 최적화 (3안 생성).
공통 흐름은 base_opt.VisualDraftOpt — 여기서는 이미지에 최적화된 프롬프트만 정의한다.
"""

from __future__ import annotations

from app.ai.llm.base_opt import VisualDraftOpt
from app.core.model_manager import model_manager  # noqa: F401 (단위 테스트가 이 네임스페이스를 patch)

# 답변을 `[방식1] [점역사주] `로 프리필(_PREFILL)해 포맷을 강제 → Think 모델의 장황한 추론을
# 건너뛰고 곧바로 3안을 생성한다(Stage5 실험에서 채택된 방식). 프롬프트는 간결하게 유지.
_PREFILL = "[방식1] [점역사주] "

_PROMPT = """당신은 시각장애 학생용 점자 교과서 점역 전문가입니다.
다음 그림을 점역자 주로 **서로 다른 3가지 방식**으로 작성하세요.
[방식1] 상황 중심: 무엇이 있고 무엇을 하는지(주요 객체·행위)
[방식2] 위치 중심: 구성 요소의 공간 배치·위치 관계
[방식3] 요약: 핵심만 1문장으로 압축

규칙: 객관적 사실만(추측·분위기·작가 의도 금지), 간결하게, "그림은/이미지는"으로 시작 금지,
원본에 없는 수치·고유명사 추가 금지(이미지 내 텍스트·수치는 원문 그대로),
인물은 이름·성별이 없으면 성별 구분 금지(직업 특정 시 '직업·나이·성별' 순).
각 줄 형식: 예) [방식1] [점역사주] 그림: 원 안에 …  — [점역사주] 뒤에 자료유형(사진/그림/삽화/지도/도표/도형)과 설명을 적고, 방식 이름은 본문에 쓰지 말 것.
다른 말 없이 정확히 3줄만.

그림: {caption}"""

# 초안 3안 방식 (stage4_complex.md 'T4-2 공통 규약' — 이미지=설명 초점)
_IMAGE_METHODS = [
    ("narrative", "상황 중심"),
    ("narrative", "위치 중심"),
    ("narrative", "요약"),
]


class ImageOpt(VisualDraftOpt):
    """ExtractedContent 목록 → LLMOutput 목록 (이미지). 3안 생성."""

    PROMPT = _PROMPT
    PREFILL = _PREFILL
    METHODS = _IMAGE_METHODS
    RULE_ID = "BBPG-3.2.1"          # 시각자료 일반 사항
    EMPTY_MSG = "[처리 불가: 이미지 캡션 없음]"
    DEFAULT_LABEL = "상황 중심"
    KIND = "이미지"
    STANDARD_TIMEOUT = 15.0
    QUALITY_TIMEOUT = 60.0          # 3안 생성은 단일 교정보다 오래 걸림(느린 GPU 여유)
    FALLBACK_MAX_TOKENS = 256
    GROUND_NUMBERS = True            # 이미지 내 수치(축값·라벨) 변조 시 R5 (실모델서 3→5 변조 관측)
