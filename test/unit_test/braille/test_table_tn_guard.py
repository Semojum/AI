"""표 점역사주 파서 가드 — 모델이 변환 대신 '상의'를 답해도 인쇄물로 나가지 않는다.

2026-08-22 eval 실측: 균일 재점역 산출물 7쪽에 표 요소 대신 "표 점역 방식 제안 …
다음 두 가지 방식을 제안합니다 …"가 **11,993셀** 실렸다(한 쪽 2,507셀).
원인은 초안 줄을 못 찾으면 **응답 전체를 그대로 돌려주던 것**이고, 못 찾은 이유는
모델이 `[점역사주:` 처럼 콜론을 붙였기 때문이다.
"""
import pytest

# `table_opt` 는 `model_manager` 를 거쳐 torch 를 문다(단위 테스트가 그 네임스페이스를
# patch 해야 해서 지연 임포트로 못 바꾼다). CI 의 test-fast 는 requirements.txt 만 깔아
# torch 가 없으므로 **수집 단계에서 이 파일 하나 때문에 점역 게이트 1,057건이 통째로
# 죽는다**(2026-08-24 PR #233 실패). 무거운 의존성이 없으면 이 파일만 건너뛴다 —
# test-full 이 그대로 돌려 주므로 검사에서 빠지는 것은 아니다.
# ★ importorskip 을 쓰지 않는 것은 pytest 판에 따라 ImportError 를 안 잡기 때문이다.
try:
    import torch  # noqa: F401
except Exception:  # noqa: BLE001 — 무엇이 없든 건너뛴다
    pytest.skip("test-fast 환경에는 torch 가 없다 (test-full 이 돌린다)",
                allow_module_level=True)

from app.ai.llm.table_opt import _parse_tn_from_response as parse  # noqa: E402

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


# ── 구조 표지 줄은 초안이 아니다 (2026-09-08 대표 실행 실물) ──────────────────
# 대표가 배포판으로 실제 문서를 돌리니 표 자리에 `<!주>표 끝.<!/주>` 한 줄만 나왔다.
# 원인은 "[점역사주 표 시작]"·"[점역사주: 표 끝]" 같은 **구조 표지**까지 초안 줄로 세서
# `선택: 2` 가 방식2가 아니라 방식1의 '표 끝' 표지를 가리킨 것이다.
_TWO_WAYS = """# 표 점역 방식 제안
## 방식 1: 항목별 나열형
[점역사주: 이하 표를 각 항목별로 풀어 씀]
요오드 반응: 옅은 갈색
[점역사주: 표 끝]
## 방식 2: 서술형 문장 변환
[점역사주: 이하 표 내용을 문장으로 서술함]
[점역사주: 표 끝]
선택: {n}"""


@pytest.mark.parametrize("n,expect", [
    (1, "이하 표를 각 항목별로 풀어 씀"),
    (2, "이하 표 내용을 문장으로 서술함"),
])
def test_marker_lines_do_not_shift_selection(n, expect):
    """표지를 빼면 `선택: N` 과 방식 번호가 다시 맞는다."""
    assert parse(_TWO_WAYS.format(n=n)) == expect


def test_marker_only_response_is_not_content():
    """표지밖에 없으면 '표 끝'을 내용인 척 내보내지 않는다."""
    assert parse("[점역사주 표 시작]\n[점역사주 표 끝]\n선택: 2") == FAIL


def test_trailing_marker_in_the_same_line_is_cut():
    """주와 표지를 한 줄에 붙여 내도 표지는 인쇄물에 안 나간다 (2026-09-08 실물)."""
    r = "[점역사주: 이 표는 세 가지 반응과 그 결과 색을 나타냄. [점역사주 끝]\n선택: 1"
    assert parse(r) == "이 표는 세 가지 반응과 그 결과 색을 나타냄."


def test_bare_marker_words_at_both_edges_are_cut():
    """대괄호 없이 양끝에만 붙는 표지도 뗀다 (2026-09-08 STANDARD 실물)."""
    r = ("[점역사주: 표시작, 구분×음료A×음료B의 3항목 4행 표임. 음료B: 24, 0, 0임. 표끝\n"
         "선택: 1")
    assert parse(r) == "구분×음료A×음료B의 3항목 4행 표임. 음료B: 24, 0, 0임."


def test_the_word_end_inside_a_sentence_survives():
    """본문 중간·다른 뜻의 '끝'은 안 건드린다."""
    assert parse("[점역사주: 표의 끝 부분에 합계가 있음.\n선택: 1") == "표의 끝 부분에 합계가 있음."


def test_leftover_open_marker_word_is_cut():
    """`[점역사주 시작]` 에서 앞 표지만 떨어져 `시작]` 이 남던 자리 (2026-09-08 실물)."""
    assert parse("[점역사주 시작] 아래는 표입니다.\n선택: 1") == "아래는 표입니다."
