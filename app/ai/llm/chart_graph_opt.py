"""PART 9-2 — 차트/그래프 점역 최적화 (HyperCLOVA X SEED Think 14B INT4, GPU 1).

GPT-4o 캡션 (축 레이블·수치·경향) → HyperCLOVA X → 점역사주 TN 최적화 (3안 생성 + 수치 검증).
공통 흐름은 base_opt.VisualDraftOpt — 여기서는 차트에 최적화된 프롬프트 + 수치 그라운딩만 정의한다.
"""

from __future__ import annotations

from app.ai.llm.base_opt import VisualDraftOpt
from app.ai.llm.base_opt import numbers_grounded as _verify_numbers  # noqa: F401 (테스트가 import)
from app.core.model_manager import model_manager  # noqa: F401 (단위 테스트가 이 네임스페이스를 patch)

_PROMPT = """당신은 시각장애 학생용 점자 교과서 점역 전문가입니다.
다음 차트/그래프 설명을 점역자 주로, **서로 다른 3가지 방식**으로 각각 작성하세요.
(점자 자료 제작 지침 §6.4, 점역사 지침: 데이터가 많으면 표 변환이 가장 좋음)

## 3가지 방식 (반드시 표현이 다르게)
[방식1] 표 변환: 데이터를 "항목: 수치" 표 형태로 정리 (데이터 포인트가 많을 때 권장)
[방식2] 수학적 서술: 유형 + x축·y축의 범위·단위 + 주요 추세 1개를 문장으로
[방식3] 개조식 항목별: 항목별 수치를 위계 목록으로

## 공통 규칙
- 각 줄을 "[방식N] [점역사주] 그래프유형: 내용" 형식으로 (유형: 막대/꺾은선/비율/선/그림그래프/수직선 중)
- 수치는 **아라비아 숫자 원문 그대로** (변환·추가·누락 금지), 단위 명시(%, 명, 원, ℃ 등)
- 원본에 없는 수치·고유명사 추가 금지, 색상만 언급하고 수치 생략 금지
- 주요 추세는 가장 중요한 1개만

## 출력 예시
입력: "연도별 발행 권수 막대그래프. 2020년 980권, 2021년 1100권, 2022년 1240권, 2023년 1380권."
[방식1] [점역사주] 막대그래프: 연도별 발행 권수. 2020년: 980권, 2021년: 1100권, 2022년: 1240권, 2023년: 1380권.
[방식2] [점역사주] 막대그래프: 연도별 발행 권수. x축 2020~2023년, y축 권수. 980권에서 1380권으로 증가.
[방식3] [점역사주] 막대그래프: 연도별 발행 권수. - 2020년 980권 - 2021년 1100권 - 2022년 1240권 - 2023년 1380권.

원본 설명:
{caption}

[방식1]/[방식2]/[방식3] 세 줄만 반환하세요. 다른 설명 없이."""

# 초안 3안 방식 (stage4_complex.md 'T4-2 공통 규약' — 차트=표현 형식)
_CHART_METHODS = [
    ("narrative", "표 변환"),
    ("narrative", "수학적 서술"),
    ("narrative", "개조식"),
]


class ChartGraphOpt(VisualDraftOpt):
    """ExtractedContent 목록 → LLMOutput 목록 (차트/그래프). 3안 생성 + 수치 그라운딩(R5)."""

    PROMPT = _PROMPT
    PREFILL = ""                    # 차트는 프리필 없이 3안 생성
    METHODS = _CHART_METHODS
    RULE_ID = "BBPG-3.2.2"          # 시각자료 유형별 점역(차트·그래프)
    EMPTY_MSG = "[처리 불가: 차트 캡션 없음]"
    DEFAULT_LABEL = "수학적 서술"
    KIND = "차트"
    STANDARD_TIMEOUT = 15.0
    QUALITY_TIMEOUT = 30.0
    FALLBACK_MAX_TOKENS = 300
    GROUND_NUMBERS = True            # 수치 누락 초안 → R5 (base_opt 공통 메커니즘)
