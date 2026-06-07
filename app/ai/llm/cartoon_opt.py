"""PART 8-2 — 만화/그림 점역 최적화 (HyperCLOVA X SEED Think 14B INT4, GPU 1).

GPT-4o 캡션 (말풍선·컷 순서) → HyperCLOVA X → 점역사주 TN 최적화 (3안 생성).
공통 흐름은 base_opt.VisualDraftOpt — 여기서는 만화에 최적화된 프롬프트만 정의한다.
"""

from __future__ import annotations

from app.ai.llm.base_opt import VisualDraftOpt
from app.core.model_manager import model_manager  # noqa: F401 (단위 테스트가 이 네임스페이스를 patch)

# 답변을 `[방식1] [점역사주] 만화: `로 프리필해 포맷+유형(만화)을 강제 → Think 모델의 추론 람블
# 건너뛰고 3안 생성(Stage5 실험에서 채택). 프롬프트는 간결하게.
_PREFILL = "[방식1] [점역사주] 만화: "

_PROMPT = """당신은 시각장애 학생용 점자 교과서 점역 전문가입니다.
다음 만화를 점역자 주로 **서로 다른 3가지 방식**으로 작성하세요.
[방식1] 장면+대사 통합: 장면 배경과 대사를 읽는 순서대로
[방식2] 대사 중심: "인물명: 대사" 위주, 장면 설명 최소화
[방식3] 장면별 개조식: "장면 1." "장면 2." 위계로 정리

규칙: 대사·말풍선 내부 텍스트는 원문 그대로(요약·변형·따옴표 금지), 화자 불명은 "말풍선: 내용",
행동·표정은 (객관 묘사), 감정 주관 해석 금지, 인물은 이름·성별 없으면 성별 구분 금지,
원본에 없는 인물명·대화 추가 금지.
각 줄 형식: 예) [방식1] [점역사주] 만화: 1장면. …  — [점역사주] 뒤에 '만화:'과 설명을 적고, 방식 이름은 본문에 쓰지 말 것.
다른 말 없이 정확히 3줄만.

만화: {caption}"""

# 초안 3안 방식 (stage4_complex.md 'T4-2 공통 규약' — 만화=구성 방식)
_CARTOON_METHODS = [
    ("narrative", "장면+대사 통합"),
    ("narrative", "대사 중심"),
    ("narrative", "장면별 개조식"),
]


class CartoonOpt(VisualDraftOpt):
    """ExtractedContent 목록 → LLMOutput 목록 (만화). 3안 생성."""

    PROMPT = _PROMPT
    PREFILL = _PREFILL
    METHODS = _CARTOON_METHODS
    RULE_ID = "BBPG-3.2.1"          # 시각자료 일반 사항
    EMPTY_MSG = "[처리 불가: 만화 캡션 없음]"
    DEFAULT_LABEL = "장면+대사 통합"
    KIND = "만화"
    STANDARD_TIMEOUT = 15.0
    QUALITY_TIMEOUT = 60.0
    FALLBACK_MAX_TOKENS = 300
