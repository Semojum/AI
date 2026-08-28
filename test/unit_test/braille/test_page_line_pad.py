"""페이지행은 **점자 빈칸(U+2800)**으로 채운다 (2026-08-28).

종전 `_compose_page_line` 만 ASCII 공백(U+0020)으로 32칸을 채웠다. 그 줄 때문에
점자 파일에 ASCII 가 섞여, 셀을 세는 소비자가 다르게 읽고 앞 빈칸 통계도 어긋났다
(생명과학 한 권 실측: ASCII 29칸 26줄 · 28칸 4줄 · 2칸 282줄).
"""
from app.ai.braille.layout_braille import LayoutBraille


def _line(footer="", orig="", page=109):
    return LayoutBraille()._compose_page_line(footer, orig, page)


def test_ASCII_공백이_섞이지_않는다():
    assert " " not in _line()
    assert " " not in _line(footer="⠈⠍⠨⠥", orig="⠼⠁")


def test_길이는_32칸_그대로():
    assert len(_line()) == 32
    assert len(_line(footer="⠈⠍⠨⠥", orig="⠼⠁")) == 32


def test_점자_페이지번호는_오른쪽_끝에_붙는다():
    l = _line(page=109)
    assert l.rstrip("⠀").endswith("⠼⠁⠚⠊")
    assert l.startswith("⠀")
