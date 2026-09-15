"""낱말 안 아포스트로피는 점자 셀 ⠄ 다 — 제61항 · 원장 R-26 (#513).

「한국 점자 규정」 제61항이 아포스트로피(’)를 `'`(⠄) 한 칸으로 정한다. 그런데
`eng_braille.translate_word` 에는 ASCII 작은따옴표가 표에 없어 `ALPHABET.get(c, c)` 를
그대로 빠져나갔다 — **점자 출력에 점자가 아닌 글자가 실렸다**(`don't` → ⠙⠕⠝'⠞).

★ 이 파일이 지키는 것은 **두 경로가 같다**는 것이다. 본문 경로(`translator`)는 라틴 런을
  아포스트로피에서 끊고 `_span_gap` 이 ⠄ 를 내므로 이미 옳게 나왔다. 곧 이 수정은
  본문 출력을 바꾸는 게 아니라 **혼자 다르던 helper 를 본문에 맞추는 것**이다.
  두 경로가 갈리면 `braille_back._english_line` 의 왕복 대조(정방향으로 되짚어 셀이
  같은지 보는 증거)가 아포스트로피가 든 영어 줄에서 **절대 성립하지 않는다.**

역방향의 같은 구멍은 #510 에서 이미 닫혔다(PR #511). 이건 정방향 몫이다.
"""
import pytest

from app.ai.braille.eng_braille import translate, translate_word
from app.ai.braille.translator import translate_body


@pytest.mark.parametrize("word", [
    "don't", "It's", "we've", "patient's", "I'll", "they're",
    "world's", "can't", "isn't", "you're", "O'Brien",
])
def test_낱말_안_아포스트로피는_본문_경로와_같게_나간다(word):
    assert translate_word(word) == "\n".join(translate_body(word)[0])


@pytest.mark.parametrize("word", ["don't", "It's", "we've", "patient's"])
def test_점자_출력에_ASCII_가_안_남는다(word):
    out = translate_word(word)
    assert all("⠀" <= c <= "⣿" for c in out), f"점자 아닌 글자가 남았다: {out!r}"


def test_홀로_선_작은따옴표는_안_건드린다():
    """제49항 작은따옴표는 별개다 — 양옆이 로마자일 때만 제61항 아포스트로피로 본다."""
    assert translate("'hello'") == "'⠓⠑⠇⠇⠕'"
