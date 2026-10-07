"""강조 축 C(#1148) — 밑줄 친 글보다 훨씬 넓은 선(표 머리행 구분선 · 상자 아래 테두리 등)은 밑줄이 아니다."""
import fitz

from app.ai.preprocessor.pdf_analyzer import underline_rects


def _page_with_lines():
    doc = fitz.open()
    pg = doc.new_page(width=600, height=800)
    pg.insert_text((100, 100), "short", fontsize=12)
    pg.draw_line((100, 103), (130, 103))         # 진짜 밑줄: 글 폭과 비슷
    pg.insert_text((100, 200), "hdr", fontsize=12)
    pg.draw_line((100, 203), (400, 203))         # 표 머리행 구분선 꼴: 글보다 훨씬 넓다
    return doc, pg


def test_글보다_훨씬_넓은_선은_밑줄이_아니다(monkeypatch):
    monkeypatch.delenv("UL_WIDTH_GUARD", raising=False)
    doc, pg = _page_with_lines()
    assert sorted(round(r.width) for r in underline_rects(pg)) == [30]


def test_끈_스위치는_넓은_선도_남긴다(monkeypatch):
    monkeypatch.setenv("UL_WIDTH_GUARD", "0")
    doc, pg = _page_with_lines()
    assert sorted(round(r.width) for r in underline_rects(pg)) == [30, 300]
