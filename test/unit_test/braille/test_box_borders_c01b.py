"""글상자 테두리(BBPG-1.2.5 · 원장 C-01b) — 검출·태깅·조판.

배경: 지문·보기·설명 박스는 묵자에서 벡터 사각형으로 그려져 있어 텍스트 추출만으로는
안 보인다. 정답 도서는 dev-2027 900쪽에서 테두리를 1,783번 쓰는데 우리는 0번이었다
(gold 셀의 5.2%). 여기서 검증하는 것:
  1) `tag_boxed_elements` — 사각형이 감싼 텍스트 요소에만 태그가 붙는가
  2) 표·그림을 품은 사각형은 건드리지 않는가 (그쪽 체인이 제 테두리를 그린다)
  3) 조판 — 테두리는 32칸 그대로, 들여쓰기는 **테두리 안 첫 줄**로 간다
"""
from __future__ import annotations

from uuid import uuid4

import pytest

from app.ai.braille.layout_braille import LayoutBraille, _COLS, _is_border_line
from app.ai.braille.text_braille import TextBraille
from app.ai.preprocessor.pdf_analyzer import tag_boxed_elements
from app.schemas.content import LLMOutput
from app.schemas.layout import BBoxItem, LayoutResult

BOX = [0, 0, 100, 100]


def _el(i, typ="text", bbox=(10, 10, 90, 20), content="본문"):
    return {"id": str(uuid4()), "order": i, "type": typ,
            "content": content, "bbox": list(bbox)}


class TestTagging:
    def test_감싼_요소만_태깅(self):
        els = [_el(1, bbox=(10, 10, 90, 20)),          # 상자 안
               _el(2, bbox=(10, 30, 90, 40)),          # 상자 안
               _el(3, bbox=(10, 200, 90, 210))]        # 상자 밖
        assert tag_boxed_elements(els, [BOX]) == 1
        assert els[0]["content"].startswith("<!테두리_위>")
        assert els[1]["content"].endswith("<!테두리_아래><!/테두리_아래>")
        assert "테두리" not in els[2]["content"]

    def test_표를_품은_상자는_건드리지_않는다(self):
        """표 격자는 제 테두리를 스스로 그린다(원장 C-01a) — 두 번 그리면 안 된다."""
        els = [_el(1), _el(2, typ="table", bbox=(10, 30, 90, 40))]
        assert tag_boxed_elements(els, [BOX]) == 0
        assert all("테두리" not in e["content"] for e in els)

    def test_읽기순서가_끊기면_건너뛴다(self):
        """태그는 첫 요소 앞·마지막 요소 뒤에 붙는다. 중간에 상자 밖 요소가 끼면
        그것까지 테두리 안으로 들어간다(실측 사회문화 p80: 지문 상자가 선택지를 감쌌다)."""
        els = [_el(1, bbox=(10, 10, 90, 20)),          # 상자 안
               _el(2, bbox=(10, 200, 90, 210)),        # 상자 밖 ← 사이에 낀다
               _el(3, bbox=(10, 30, 90, 40))]          # 상자 안
        assert tag_boxed_elements(els, [BOX]) == 0
        assert all("테두리" not in e["content"] for e in els)

    def test_한_요소는_한_상자에만(self):
        """중첩 상자는 큰 쪽이 이긴다 — 안쪽 상자가 같은 요소를 또 감싸면 안 된다."""
        els = [_el(1, bbox=(10, 10, 90, 20))]
        assert tag_boxed_elements(els, [BOX, [5, 5, 95, 95]]) == 1
        assert els[0]["content"].count("<!테두리_위>") == 1

    def test_사각형_없으면_무변경(self):
        els = [_el(1)]
        assert tag_boxed_elements(els, []) == 0
        assert els[0]["content"] == "본문"


class TestLayout:
    @pytest.fixture()
    def boxed(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        eid = uuid4()
        src = ("<!테두리_위><!/테두리_위>\n"
               "사회·문화 현상을 연구하는 이 방법은 기존의 연구 방법과는 다른 특성을 지닌다.\n"
               "<!테두리_아래><!/테두리_아래>")
        opt = LLMOutput(element_id=eid, corrected_text=src, render_mode="text_only",
                        routing_tier="ZERO", processing_time_ms=0)
        bo = TextBraille().translate([opt])[0]
        lr = LayoutResult(page_id="p1", page_no=1, items=[
            BBoxItem(element_id=eid, type="text", bbox=(0, 0, 10, 10), reading_order=1)])
        LayoutBraille().layout([bo], 1, "boxc01b", layout_result=lr)
        return bo

    def test_테두리가_위아래로_남는다(self, boxed):
        borders = [ln for ln in boxed.braille_lines if _is_border_line(ln)]
        assert len(borders) == 2
        assert borders[0].startswith("⠿⠛") and borders[1].startswith("⠿⠶")
        assert all(len(b) == _COLS for b in borders)

    def test_들여쓰기가_테두리_안_첫_줄로_간다(self, boxed):
        """테두리 줄을 들이면 35칸이 되어 쪼개진다. 그렇다고 요소 전체 들여쓰기를 버리면
        상자 안 문단이 0칸에서 시작해 gold와 어긋난다(gold는 문단 3칸에서 시작)."""
        lines = boxed.braille_lines
        first_content = next(i for i, ln in enumerate(lines)
                             if ln.strip() and not _is_border_line(ln))
        assert lines[first_content].startswith("  ")
        assert not lines[first_content][2].isspace()
        assert all(not ln.startswith(" ") for ln in lines if _is_border_line(ln))
