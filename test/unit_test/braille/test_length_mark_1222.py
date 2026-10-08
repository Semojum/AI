"""긴소리표 ː (규정 제63항, #1222).

규정 원문 `braille-source/text/규정_텍스트.txt` 2572행 "제63항 긴소리표(ː)는 ,'으로 적고, 앞뒤를 붙여 쓴다.",
2577~2578행 예 `밤ː나무` → `^5,'cem`. gold 는 묵자에 가는 띄움(U+2009)이 낀 자리도 붙여 적는다:
`corpus/pages/braille/EBS-E26-004` ans/p0011 15행(`[야ː행썽]`) · body/p0012 47행(`눈ː〔雪〕`).
층 관문은 ː 하나로 층을 버리지 않는다. 다른 깨진 글자가 같이 있으면 종전대로 버린다.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parents[3]))

from app.ai.braille.translator import translate_tagged_text  # noqa: E402
from app.ai.preprocessor.pdf_analyzer import mangled_glyph_chars  # noqa: E402


@pytest.fixture(autouse=True)
def _on(monkeypatch):
    monkeypatch.delenv("LAYER_LENGTH_MARK", raising=False)


def test_규정_예_밤나무():
    assert translate_tagged_text("밤ː나무") == "⠘⠢⠠⠄⠉⠑⠍"            # 규정 BRF `^5,'cem`


@pytest.mark.parametrize("src, gold", [
    ("[야 ː행썽]", "⠦⠆⠜⠠⠄⠚⠗⠶⠠⠠⠻⠰⠴"),      # gold 언매 ans p0011 15행
    ("눈ː 〔雪〕", "⠉⠛⠠⠄⠦⠆⠠⠞⠰⠴"),          # gold 언매 body p0012 47행
])
def test_묵자의_가는_띄움을_걷고_붙여_쓴다(src, gold):
    assert translate_tagged_text(src) == gold


def test_관문은_긴소리표_하나로_층을_버리지_않는다():
    assert not mangled_glyph_chars("‘많아[마ː나]’")[0]
    assert mangled_glyph_chars(" [사ː니]")[0] == {"": 1}


def test_끄면_종전대로(monkeypatch):
    monkeypatch.setenv("LAYER_LENGTH_MARK", "0")
    assert mangled_glyph_chars("[마ː나]")[0] == {"ː": 1}
    assert "⠀" in translate_tagged_text("[야 ː행썽]")
