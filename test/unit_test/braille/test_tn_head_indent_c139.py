"""점역자 주표 ⠠⠄ 로 여는 줄은 3칸에서 시작한다(원장 C-139 채택값, 앞 빈칸 2).

짝 없는 캡션 요소(`caption`)는 첫 줄 들여쓰기가 0이라 둘째 줄 `【점역자주】그림 생략【점역자주】` 이 줄머리에 붙어 나갔다.
gold 세계사 본책 p0124 31행 = `⠀⠀⠠⠄⠈⠪⠐⠕⠢⠀⠠⠗⠶⠐⠜⠁⠠⠄`. gold 주표 머리줄 앞 빈칸 2칸 921 · 4칸 97 · 0칸 1(dev · val).
"""
from uuid import uuid4

from app.ai.braille.layout_braille import LayoutBraille
from app.schemas.content import BrailleOutput

TITLE = "⠼⠁⠊⠠⠝⠈⠕⠀⠚⠍⠘⠒⠺⠀⠇⠶⠚⠧⠶"
NOTE = "⠠⠄⠈⠪⠐⠕⠢⠀⠠⠗⠶⠐⠜⠁⠠⠄"


def test_캡션_둘째_줄의_주표는_3칸에서():
    bo = BrailleOutput(element_id=uuid4(), braille_lines=[TITLE, NOTE],
                       corrected_text="19세기 후반의 상황\n<!주>그림 생략<!/주>")
    _, indents = LayoutBraille()._indent_lines(bo, "caption", 0)
    assert indents == [0, 2]


def test_주표로_여는_줄이_아니면_그대로():
    bo = BrailleOutput(element_id=uuid4(), braille_lines=[TITLE, TITLE], corrected_text="가\n나")
    _, indents = LayoutBraille()._indent_lines(bo, "caption", 0)
    assert indents == [0, 0]


def test_쪽_조판도_같은_칸():
    """화면(통 문자열 `_indent_lines`)과 다운로드(쪽 조판 `_format_element`)가 같은 칸이어야 한다."""
    bo = BrailleOutput(element_id=uuid4(), braille_lines=[TITLE, NOTE],
                       corrected_text="19세기 후반의 상황\n<!주>그림 생략<!/주>")
    out, _ = LayoutBraille()._format_element(bo, "caption", 0)
    assert out[1] == "⠀⠀" + NOTE


def test_줄별_들여쓰기가_0이어도_주표_줄은_3칸에서():
    """시각 요소 생략 초안(`line_indents` 가 0)의 `【점역자주】그림 생략【점역자주】` 도 같은 꼴."""
    bo = BrailleOutput(element_id=uuid4(), braille_lines=[NOTE], corrected_text="<!주>그림 생략<!/주>", line_indents=[0])
    _, indents = LayoutBraille()._indent_lines(bo, "image", 0)
    assert indents == [2]
    out, _ = LayoutBraille()._format_element(bo, "image", 0)
    assert out[0] == "⠀⠀" + NOTE


def test_주표_줄이_첫_줄이어도_3칸에서():
    bo = BrailleOutput(element_id=uuid4(), braille_lines=[NOTE], corrected_text="<!주>그림 생략<!/주>")
    _, indents = LayoutBraille()._indent_lines(bo, "caption", 0)
    assert indents == [2]
