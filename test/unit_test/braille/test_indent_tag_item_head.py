"""묵자 창 글(첫 줄에 `<!2칸>`)을 다시 점역해도 항목 · 선택지 줄 들여쓰기가 태그 없는 글과 같다.

`pipeline._print_contents` 는 묵자 창 글 첫 줄에 들여쓰기 태그를 붙이고, 그 글을 되돌려 점역하면 같은 들여쓰기가
나온다고 둔다. 여러 줄 항목 · 선택지에서는 아니었다. `_mark_item_lines` 가 태그 붙은 첫 줄을 항목 머리로 못 알아봐
첫 줄이 0칸이 되거나(1. … 2. …) 묶은 둘째 줄이 0칸이 됐다(① ② ③ / ④ ⑤). mode b 와 앱 사이드카가 이 글을 다시 점역한다.
하네스 ⑥(2027 dev · val 한 묶음): 다시 점역이 서버 점자와 다른 요소 265 / 13,302, 전부 이 꼴.
"""
import uuid
from types import SimpleNamespace

import pytest

from app.ai.braille.layout_braille import flatten_elements
from app.ai.braille.text_braille import TextBraille
from app.schemas.content import LLMOutput


def _cells(text: str, etype: str) -> str:
    """사이드카 `translate` 와 같은 경로(`_translate_one` → `flatten_elements`, 앞뒤 빈 줄 뺌)."""
    bo = TextBraille()._translate_one(LLMOutput(element_id=uuid.uuid4(), corrected_text=text, routing_tier="ZERO"))
    el = SimpleNamespace(element_id=bo.element_id, type=etype, reading_order=0, heading_level=0)
    fe = flatten_elements([bo], SimpleNamespace(elements=[el]))[bo.element_id]
    return fe.text[len(fe.prefix):len(fe.text) - len(fe.suffix)]


@pytest.mark.parametrize("etype", ["text", "list_item"])
@pytest.mark.parametrize("body", [
    "1. 생체 모방\n2. 귀납적\n3. ◯\n4. ×",
    "① ㄱ\n② ㄷ\n③ ㄱ, ㄴ\n④ ㄴ, ㄷ\n⑤ ㄱ, ㄴ, ㄷ",
    "ㄱ. 세포막을 통과한다.\nㄴ. 효소가 관여한다.\nㄷ. 에너지가 방출된다.",
])
def test_첫_줄_들여쓰기_태그가_있어도_항목_줄_들여쓰기가_같다(body, etype):
    plain = _cells(body, etype)
    assert all(ln.startswith("⠀⠀") for ln in plain.split("\n"))     # 항목마다 3칸에서(지침 2장 3절 5)
    assert _cells("<!2칸>" + body, etype) == plain


def test_한_줄_글은_종전과_같다():
    assert _cells("<!2칸>가나다라 마바사", "text") == _cells("가나다라 마바사", "text")
