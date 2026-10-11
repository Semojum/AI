"""괄호 숫자 글자 `⑴` ~ `⒇` 로 여는 4단계 제목도 항목 머리라 3칸에서 시작한다(원장 C-84).

사회 네 권은 소항목 머리를 `⑴` 한 글자로 적는다. `_ITEM_HEAD_NUM` 이 `(1)` 꼴만 잡아 5칸(앞 빈칸 4)으로 나갔다.
gold 세계사 본책 p0041 3행 = `⠀⠀⠦⠄⠼⠁⠠⠴⠀⠕⠠⠮⠐⠣⠢⠈⠬⠺⠀⠠⠻⠐⠕⠃`(⑴ 이슬람교의 성립), 37행 ⑵ 도 2칸.
"""
from uuid import uuid4

import pytest

from app.ai.braille.layout_braille import LayoutBraille
from app.schemas.content import BrailleOutput


def _indent(text: str) -> int:
    bo = BrailleOutput(element_id=uuid4(), braille_lines=["⠦⠄⠼⠁⠠⠴⠀⠕⠠⠮⠐⠣⠢⠈⠬⠺"], corrected_text=text)
    return LayoutBraille()._first_indent(bo, "title", True, 4)


@pytest.mark.parametrize("text", ["⑴\t이슬람교의 성립", "⑵ 이슬람 제국의 발전", "⒇ 마지막", "(1) 괄호 꼴"])
def test_괄호_숫자_머리는_3칸에서(text):
    assert _indent(text) == 2


def test_단원_제목은_종전대로_5칸에서():
    assert _indent("이슬람 세계의 형성과 발전") == 4
