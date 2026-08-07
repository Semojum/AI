"""괘선 없는 '표'는 표가 아니다 — mineru_runner._h_rules / _table_to_columns (QA 9번).

MinerU 표 모델은 2단 조판 시험지처럼 글이 격자로 늘어선 쪽을 통째로 <table>로 싼다
(대표 QA 실측: 수능 수학 문제지 2쪽 — 쪽 본문 전체가 표 한 덩이, 문항 하나가 셀 하나).
가르는 신호는 가로 괘선이다: dev-2027 실표 104개는 전부 2개 이상, 거짓 표는 0개.
"""
import sys
from pathlib import Path

import fitz
import pytest

sys.path.insert(0, str(Path(__file__).parents[3]))

from app.ai.parser import mineru_runner as MR  # noqa: E402

W, H = 600.0, 800.0
BODY = [100, 200, 900, 900]        # 0~1000 정규화 — 쪽 본문 전체


def _page(draw):
    doc = fitz.open()
    page = doc.new_page(width=W, height=H)
    draw(page)
    return doc, page


def _rect(bbox):
    return fitz.Rect(bbox[0] / 1000 * W, bbox[1] / 1000 * H,
                     bbox[2] / 1000 * W, bbox[3] / 1000 * H)


def test_two_column_text_has_no_horizontal_rules():
    """2단 구분선 하나만 있는 본문 = 가로 괘선 0 → 표가 아니다."""
    r = _rect(BODY)
    doc, page = _page(lambda p: p.draw_line(
        fitz.Point((r.x0 + r.x1) / 2, r.y0), fitz.Point((r.x0 + r.x1) / 2, r.y1)))
    assert MR._h_rules(page, BODY) == 0
    doc.close()


def test_ruled_table_is_kept():
    """가로 괘선이 그어진 표는 그대로 표로 둔다."""
    r = _rect(BODY)
    def draw(p):
        for i in range(4):
            y = r.y0 + (r.height / 3) * i
            p.draw_line(fitz.Point(r.x0, y), fitz.Point(r.x1, y))
    doc, page = _page(draw)
    assert MR._h_rules(page, BODY) >= MR._RULE_MIN_H
    doc.close()


def test_short_underlines_are_not_rules():
    """표 폭의 절반도 안 되는 밑줄 토막은 괘선으로 세지 않는다."""
    r = _rect(BODY)
    def draw(p):
        for i in range(6):
            y = r.y0 + 20 * i
            p.draw_line(fitz.Point(r.x0, y), fitz.Point(r.x0 + r.width * 0.2, y))
    doc, page = _page(draw)
    assert MR._h_rules(page, BODY) == 0
    doc.close()


def test_page_without_vectors_is_undecidable():
    """스캔본처럼 벡터 선이 없는 쪽은 판단하지 않는다(None) — 표를 함부로 내리지 않는다."""
    doc, page = _page(lambda p: None)
    assert MR._h_rules(page, BODY) is None
    doc.close()


def test_raster_covered_area_is_undecidable():
    """표를 그림으로 붙인 쪽 — 괘선이 화소 안에 있어 벡터로는 못 센다(언어 p223 실측)."""
    r = _rect(BODY)
    png = fitz.Pixmap(fitz.csGRAY, fitz.IRect(0, 0, 8, 8), 0)
    def draw(p):
        p.draw_line(fitz.Point(0, 0), fitz.Point(0, p.rect.y1))   # 쪽 어딘가에 벡터 선은 있다
        p.insert_image(r, pixmap=png)
    doc, page = _page(draw)
    assert MR._h_rules(page, BODY) is None
    doc.close()


def test_fragmented_rule_counts_once():
    """셀마다 끊어 그린 괘선은 y가 같으면 한 줄로 합산한다."""
    r = _rect(BODY)
    def draw(p):
        for i in range(3):
            y = r.y0 + (r.height / 2) * i
            for k in range(4):       # 한 줄을 네 토막으로
                x0 = r.x0 + r.width / 4 * k
                p.draw_line(fitz.Point(x0, y), fitz.Point(x0 + r.width / 4, y))
    doc, page = _page(draw)
    assert MR._h_rules(page, BODY) == 3
    doc.close()


_LONG_A = "1. 함수 f(x)에 대하여 극한값을 구하는 문제이며 선택지는 다섯 개다. [2점]"
_LONG_B = "2. 수열의 합을 구하는 문제이며 조건이 두 줄에 걸쳐 제시된다. [3점]"
_LONG_C = "3. 포물선의 초점과 준선 사이의 거리를 묻는 문제로 배점은 세 점이다."
_LONG_D = "4. 실수 전체의 집합에서 연속일 때 상수 a의 값을 묻는 문제다. [3점]"


@pytest.mark.parametrize("html,expect", [
    # 셀이 긴 글 = 다단 조판. 1행이 [1번, 3번]이라 행으로 읽으면 1·3·2·4가 된다
    (f'<table><tr><td colspan="2">5지선다형</td></tr>'
     f'<tr><td>{_LONG_A}</td><td>{_LONG_C}</td></tr>'
     f'<tr><td>{_LONG_B}</td><td>{_LONG_D}</td></tr></table>',
     f"5지선다형\n{_LONG_A}\n{_LONG_B}\n{_LONG_C}\n{_LONG_D}"),
    # 한 행 두 단(23·24번)
    (f'<table><tr><td>{_LONG_C}</td><td>{_LONG_D}</td></tr></table>',
     f"{_LONG_C}\n{_LONG_D}"),
    # 셀이 짧으면 선택지 표 — 행이 인쇄 줄이므로 행 순서로 두 칸씩 띄어 잇는다
    ('<table><tr><td>①</td><td>뜯기</td><td>치기</td></tr>'
     '<tr><td>②</td><td>치기</td><td>켜기</td></tr></table>',
     "①  뜯기  치기\n②  치기  켜기"),
    # 한 단짜리(시 인용 상자)는 그대로 줄줄이
    ('<table><tr><td>산 너머 남촌에는</td></tr><tr><td>배나무 있고</td></tr></table>',
     "산 너머 남촌에는\n배나무 있고"),
])
def test_table_to_text_picks_reading_direction(html, expect):
    assert MR._table_to_text(html) == expect
