"""표 점역자 주는 점자로 안 나간다 — 4-3(#755) 결론이 딛고 선 사실.

`TABLE_TN_LLM` 기본값을 끔으로 돌린 근거가 "LLM 이 짓는 `tn_text` 가 점자에 안 실린다"
하나다. 그 사실이 깨지면(예: 비정형 단일안 갈래가 다시 열리면) 기본값을 다시 봐야 하므로,
말이 아니라 **돌아가는 검사**로 박아 둔다.

실측 근거(2026-09-08 · dev·val 경계 1,131쪽 전수 · 표 406개): LLM 팔과 규칙 팔의 점자가
406/406 바이트 동일했고, 406/406 이 초안 5안을 가졌다(비정형 단일안 갈래 0건).
"""
from uuid import uuid4

from app.ai.braille.table_braille import TableBraille, build_table_tags
from app.schemas.content import LLMOutput

ROWS = [["구분", "A", "B"], ["1차", "10", "20"], ["2차", "30", "40"]]


def _translate(tn: str) -> LLMOutput:
    opt = LLMOutput(
        element_id=uuid4(),
        corrected_text=build_table_tags(ROWS),
        render_mode="table_grid",
        tn_text=tn,
        routing_tier="STANDARD",
        processing_time_ms=0,
    )
    return TableBraille().translate([opt])[0]


def test_tn_이_달라도_점자는_같다():
    """LLM 문장이 무엇이든 표 점자는 안 바뀐다 — 격자 렌더러가 셀에서 직접 짓는다."""
    a = _translate("<!주>표. 3항목 3행 표임.<!/주>")
    b = _translate("<!주>이 표는 1차와 2차의 값을 비교한 표임.<!/주>")
    assert a.braille_lines == b.braille_lines
    assert [d.braille_lines for d in a.drafts] == [d.braille_lines for d in b.drafts]


def test_격자로_읽히는_표는_초안_5안을_갖는다():
    """초안이 있으면 묵자도 선택 초안을 쓴다(`pipeline._print_src`) — tn 은 화면 밖."""
    assert len(_translate("<!주>표. 3항목 3행 표임.<!/주>").drafts) == 5


def test_tn_글자가_점자에_안_섞인다():
    """tn 에만 있는 낱말('연도별')이 점자 어디에도 안 나온다."""
    from app.ai.braille.translator import translate_tagged_text

    bo = _translate("<!주>연도별 표임.<!/주>")
    needle = translate_tagged_text("연도별")
    assert needle
    assert not any(needle in line for line in bo.braille_lines)
