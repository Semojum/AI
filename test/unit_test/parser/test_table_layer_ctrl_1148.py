"""표 경로 층 글의 제어 문자 띄움(#1148) — mineru_runner._table_layer.

#1072 는 글 요소 경로에만 걸려, 표 칸 대조 · 글머리 되돌리기가 `•\\x07사람을` 의 `\\x07`(InDesign 표지) 한 글자로
층을 통째로 못 믿었다. 언어와 매체 문법 표에서 실측한 꼴(body p0018 `하나, 돌, 셋` → `둘`)로 고정한다.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parents[3]))

from app.ai.parser import mineru_runner as MR  # noqa: E402

BBOX = [0, 0, 1000, 1000]
LAYER = "•\x07정확한 수: 하나, 둘, 셋, 넷, 다섯\n ‌\x07대략의 수: 한둘, 서넛"
CELL = "<table><tr><td>• 정확한 수: 하나, 돌, 셋, 넷, 다섯 대략의 수: 한둘, 서넛</td></tr></table>"


@pytest.fixture
def pair(monkeypatch):
    monkeypatch.setattr(MR, "_native_text_pair", lambda page, bb, skip_math=False: (LAYER, LAYER))


def test_제어_문자가_든_층으로도_표_칸을_고친다(pair):
    out = MR._correct_table_cells(None, BBOX, CELL)
    assert "하나, 둘, 셋" in out


def test_끄면_종전대로_층을_못_믿어_표를_그대로_둔다(pair, monkeypatch):
    monkeypatch.setenv("TABLE_LAYER_CTRL", "0")
    assert MR._correct_table_cells(None, BBOX, CELL) == CELL


def test_글머리_되돌리기도_제어_문자를_띄움으로_본다(monkeypatch):
    monkeypatch.setattr(MR, "_extract_text_native",
                        lambda page, bb: "•\x07모든 사회는 안정적임\n•\x07모든 사회는 통합된 체계임")
    html = "<table><tr><td>모든 사회는 안정적임모든 사회는 통합된 체계임</td></tr></table>"
    assert MR._restore_table_bullets(None, BBOX, html).count("•") == 2
    monkeypatch.setenv("TABLE_LAYER_CTRL", "0")
    assert MR._restore_table_bullets(None, BBOX, html) == html
