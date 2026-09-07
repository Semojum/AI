"""묵자의 연속 빈칸 길이를 점자에 그대로 베끼던 문제 (2026-09-08).

정답 나열 줄 `01 ②   02 ⑤`(묵자 3칸)가 점자에서도 3칸으로 나갔다. 항목 구분은
**두 칸 고정**이다 — 「점자 도서 제작 지침」 3장 3절 4)(3)①(선택지 사이)·6)(1)
(표의 셀 사이). 묵자의 3~8칸은 인쇄 정렬이지 점자 칸수가 아니다.

gold 대조 3건(BRF 원문 그대로, 모두 두 칸):
    corpus/pages/braille/EBS-E26-001/ans/p0048.brf:8   `  #ja #2  #jb #5  #jc #3`
    corpus/pages/braille/EBS-E26-017/ans/p0018.brf:3   `  #A #2  #B #5  #C #5  #D #1`
    corpus/pages/braille/EBS-E26-011/ans/p0002.brf:6   `  #a #bd  #b #5  #c #2  #d #3`

칸수 일치율(1,180쪽) 제11항 대리 74.18% → 83.63%, 전체 99.366% → 99.422%.
CER 은 빈칸을 안 세므로 전후 셀 문자열이 1,180쪽 전부 동일하다(변화 0).
"""
from app.ai.braille.translator import translate_body


def _line(text: str) -> str:
    return "\n".join(translate_body(text)[0])


def _gaps(braille: str) -> list[int]:
    """줄 안쪽 빈칸 런의 길이 목록(줄머리·줄끝 제외)."""
    out, run = [], 0
    for ch in braille.strip("⠀"):
        if ch == "⠀":
            run += 1
        elif run:
            out.append(run)
            run = 0
    return out


def test_answer_row_three_spaces_becomes_two():
    """`01 ②   02 ⑤`(묵자 3칸) → 두 칸. 항목 사이 한 칸은 그대로 한 칸."""
    assert _gaps(_line("01 ②   02 ⑤   03 ③")) == [1, 2, 1, 2, 1]


def test_four_and_more_spaces_also_become_two():
    """묵자 4·8칸도 두 칸이다 — 인쇄 정렬 길이를 옮기지 않는다."""
    assert _gaps(_line("1 ②    2 ⑤")) == [1, 2, 1]
    assert _gaps(_line("가        나")) == [2]


def test_two_spaces_stay_two():
    """이미 두 칸인 자리는 건드리지 않는다."""
    assert _gaps(_line("01 ②  02 ⑤")) == [1, 2, 1]


def test_single_space_untouched():
    """낱말 사이 한 칸은 그대로다 — 이 수정이 닿는 곳이 아니다."""
    assert _gaps(_line("정답 1. 백강 전투")) == [1, 1, 1]
