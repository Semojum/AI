"""표 점역사주 파서 가드 — 모델이 변환 대신 '상의'를 답해도 인쇄물로 나가지 않는다.

2026-08-22 eval 실측: 균일 재점역 산출물 7쪽에 표 요소 대신 "표 점역 방식 제안 …
다음 두 가지 방식을 제안합니다 …"가 **11,993셀** 실렸다(한 쪽 2,507셀).
원인은 초안 줄을 못 찾으면 **응답 전체를 그대로 돌려주던 것**이고, 못 찾은 이유는
모델이 `[점역사주:` 처럼 콜론을 붙였기 때문이다.
"""
from app.ai.llm.table_opt import _parse_tn_from_response as parse

FAIL = "[처리 불가: 표 점역사주 생성 실패]"


def test_normal_draft():
    assert parse("[방식1] [점역사주] 사상가별 직업관 표이다.\n선택: 1") == "사상가별 직업관 표이다."


def test_colon_variant_is_salvaged():
    """실제 원인 — 대괄호 안에 콜론을 붙이면 종전 파서가 못 찾았다."""
    assert parse("[방식1] [점역사주: 연도별 인구 표이다.]\n선택: 1") == "연도별 인구 표이다."


def test_chat_response_keeps_only_the_draft():
    out = parse(
        "# 표 점역 방식 제안\n"
        "점자에서는 표를 줄글로 푸는 것이 일반적이므로, 다음 두 가지 방식을 제안합니다.\n"
        "※※[방식1]※※ [점역사주: 연도별 인구 표이다.]\n선택: 1"
    )
    assert out == "연도별 인구 표이다."
    for meta in ("제안", "일반적이므로", "방식"):
        assert meta not in out


def test_chat_without_draft_is_not_printed():
    """상의만 오면 원문을 흘리지 않는다 — 짧은 실패 표시만 남긴다."""
    assert parse("# 표 점역 방식 제안\n다음 두 가지 방식을 제안합니다. 어떻게 점역할까요?") == FAIL


def test_empty_response():
    assert parse("   ") == FAIL
