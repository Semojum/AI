"""초안 묵자의 들여쓰기 태그 처리 (F10, 대표 지적).

대표: "시각 요소 설명에는 `<!2칸>` 이 제대로 반영되는데 밑에 추천 텍스트나 default 로
보이던 텍스트들엔 다 그런 태깅이 없다."

`_draft_print_text` 가 모든 내부 태그를 지우는데 `<!2칸>` 도 같이 걸렸다. 그런데 그
함수의 계약은 "줄바꿈·공백은 **배치**이므로 보존한다" 이고 **들여쓰기가 바로 그 배치**다.
지우지 말고 실제 공백으로 바꾼다.
"""
from app.core.pipeline import _draft_print_text


def test_indent_tags_become_real_spaces():
    got = _draft_print_text("<!0칸>해모수\n<!2칸>주몽\n<!4칸>유리")
    assert got == "해모수\n  주몽\n    유리", repr(got)


def test_first_line_indent_survives():
    """`.strip()` 을 그대로 쓰면 첫 줄 들여쓰기를 먹는다 — 한 번 밟았다."""
    assert _draft_print_text("<!2칸>가나다") == "  가나다"


def test_other_tags_are_still_removed():
    """점역기 표식은 사람이 읽을 글자가 아니다 — 종전대로 지운다."""
    assert _draft_print_text("<!주>그림 생략: 참호전<!/주>") == "그림 생략: 참호전"
    assert _draft_print_text("<!2칸>가나다 <!강조>라마<!/강조>") == "  가나다 라마"


def test_plain_text_is_untouched():
    assert _draft_print_text("태그 없는 글") == "태그 없는 글"
