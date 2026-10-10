"""#1271 쪽 그림(`get_drawings`)은 쪽 객체마다 한 번만 읽는다.

`mineru_runner._native_text_pair` 가 블록마다 `underline_rects` · `text_fractions` 를 불러, 그림 경로가 많은 쪽은
한 번에 1~3초인 `get_drawings()` 를 블록 수 × 2 만큼 되풀이했다(수학Ⅱ 풀이 p0030 92번 · 사회문화 p0147 60번).
쪽 예산 180초를 넘겨 C7 로 쪽이 통째로 막혔다.
"""
import fitz

from app.ai.preprocessor import pdf_analyzer as pa


def _page():
    doc = fitz.open()
    page = doc.new_page()
    for i in range(6):
        page.draw_line((50, 120 + i * 20), (200, 120 + i * 20))
    page.insert_text((50, 115), "abc")
    return doc, page


def test_블록마다_불러도_그림은_한_번만_읽는다(monkeypatch):
    doc, page = _page()
    calls = []
    orig = page.get_drawings
    monkeypatch.setattr(page, "get_drawings", lambda *a, **k: calls.append(1) or orig(*a, **k))
    for _ in range(10):                       # 블록 열 개
        pa.underline_rects(page)
        pa.text_fractions(page)
    assert len(calls) == 1


def test_담아_둔_값은_새로_센_값과_같다():
    doc, page = _page()
    fresh_doc, fresh = _page()
    assert pa.underline_rects(page) == pa.underline_rects(page) == pa._underline_rects(fresh, True)
    assert pa.text_fractions(page) == pa._text_fractions(fresh)
