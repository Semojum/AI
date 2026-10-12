"""줄머리 괄호 번호 머리(`(1)` · `(i)` · `(가)` · `⑴`) 뒤 탭 · 여러 칸은 한 칸이다(#1338, 원장 C-169).

묵자 탭 · 여러 칸은 항목 구분 두 칸이 아니라 머리 뒤 띄움이다 — 「점자 도서 제작 지침」 [예 2-32](재추출 1449행)
`(가) 제1조` = `8'$,0`.n#a.u`. 머리 바로 뒤가 수식이면 수학 제11항(재추출 3234행)대로 두 칸 그대로다(gold 는 한 칸,
원장 C-169 자문).
"""
import pytest

from app.ai.braille import inline_math
from app.ai.braille.translator import translate_tagged_text


@pytest.fixture()
def math_page():
    tok = inline_math.MATH_PAGE.set(True)
    yield
    inline_math.MATH_PAGE.reset(tok)


def test_머리_뒤_수식은_제11항대로_두_칸(math_page):
    """규정(수학 제11항) 대로 둔다. gold 수학Ⅰ ans p0043 10행은 한 칸(`⠦⠄⠼⠁⠠⠴⠀⠁⠰⠼⠉…`) — 원장 C-169 자문."""
    assert translate_tagged_text("(1) $a_{3}+a_{7}=10$,").startswith("⠦⠄⠼⠁⠠⠴⠀⠀⠁⠰⠼⠉")


def test_머리_뒤_탭은_한_칸():
    assert translate_tagged_text("(1)\t형태소") == translate_tagged_text("(1) 형태소")
    assert translate_tagged_text("(가)  제1조") == translate_tagged_text("(가) 제1조")


def test_머리_바로_뒤_글은_그대로():
    """줄머리 주어(`(가)는 …`)에는 빈칸을 넣지 않는다."""
    out = translate_tagged_text("(가)는 다음과 같다.")
    assert out.startswith("⠦⠄⠫⠠⠴⠉⠵")


def test_줄_가운데_두_칸은_항목_구분이라_그대로():
    assert "⠀⠀⠦⠄⠼⠃⠠⠴" in translate_tagged_text("가나  (2) 다라")


def test_머리_뒤_탭_다음_수식도_두_칸(math_page):
    assert translate_tagged_text("(1)\t$a_{3}+a_{7}=10$,") == translate_tagged_text("(1) $a_{3}+a_{7}=10$,")
