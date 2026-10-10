"""#1280 빠진 기호 알림(R17)은 우리가 표 묵자 초안에 두른 테두리 표지(┌ ├ └ 한 글자 줄)를 세지 않는다.

표지를 '빠진 기호'로 세어 2027 dev · val 1,746쪽 중 571쪽에 R17 이 붙고 265쪽이 그것 하나로 NEEDS_REVIEW 였다.
"""
from app.ai.braille.table_braille import _PRINT_BOX_BOTTOM, _PRINT_BOX_TOP, _PRINT_RULE
from app.ai.braille.translator import dropped_symbols


def test_표_묵자_초안의_테두리_표지_줄은_안_센다():
    draft = "\n".join([_PRINT_BOX_TOP, "구분: 내용", _PRINT_RULE, "가: 나", _PRINT_BOX_BOTTOM])
    assert dropped_symbols(draft) == {}


def test_표지_줄_안의_진짜_빠진_기호는_센다():
    draft = "\n".join([_PRINT_BOX_TOP, "평점: ★★★", _PRINT_BOX_BOTTOM])
    assert dropped_symbols(draft) == {"★": 3}


def test_글_가운데_낀_테두리_글자는_센다():
    """지면 글자로 온 `┌` 는 표지 줄이 아니다 — 종전대로 센다(점형이 없으면 빠진 기호다)."""
    assert dropped_symbols("가┌나")["┌"] == 1
