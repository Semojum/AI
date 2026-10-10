"""묵자 창 글(첫 줄에 `<!2칸>`)을 다시 점역해도 항목 · 선택지 줄 들여쓰기가 태그 없는 글과 같다.

`pipeline._print_contents` 는 묵자 창 글 첫 줄에 들여쓰기 태그를 붙이고, 그 글을 되돌려 점역하면 같은 점자가
나온다고 둔다. 아니었다. 줄머리를 보는 판정 둘이 태그 붙은 첫 줄을 못 알아봤다.
  · `layout_braille._mark_item_lines`: 첫 항목이 항목 머리로 안 잡혀 첫 줄이 0칸(1. … 2. …), 묶은 둘째 줄이 0칸(① ② ③ / ④ ⑤).
  · `translator._QNUM_RE`: 요소 첫머리 문항 번호에 마침표가 안 붙음("3\n[26008-0003]" → `⠼⠉` , 서버는 `⠼⠉⠲`).
mode b 와 앱 사이드카가 이 글을 다시 점역한다. 하네스 ⑥(2027 dev · val 1,746쪽 · 글 요소 39,564): 다시 점역이 서버
점자와 다른 요소 761 중 755 가 이 꼴(항목 715 · 문항 번호 40). 나머지 6 은 수식 쪽 문맥 근사다.
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


@pytest.mark.parametrize("body", ["3\n[26008-0003]", "3\n다음은 세포 분열에 대한 설명이다."])
def test_첫_줄_들여쓰기_태그가_있어도_문항_번호_마침표가_같다(body):
    plain = _cells(body, "text")
    assert plain.startswith("⠀⠀⠼⠉⠲")                                 # 문항 번호 뒤 마침표(translator._QNUM_RE)
    assert _cells("<!2칸>" + body, "text") == plain


def test_한_줄_글은_종전과_같다():
    assert _cells("<!2칸>가나다라 마바사", "text") == _cells("가나다라 마바사", "text")
