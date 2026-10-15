"""#1429 2단 판 사료 상자를 못 찾던 문제.

양쪽 맞춤 글 블록이 테두리를 몇 pt 넘으면(세계사 본문 123쪽: 블록 x1 289 · 테두리 286.2) '감싼 글 없음'으로
상자를 통째로 버렸다. 높이 40pt 이상이면 4pt 까지 넘어도 감싼 글로 본다.
쪽 위 머리띠(21~29pt)와 다른 상자 안의 그림 이름표 틀(생명과학 본문 62쪽)은 상자가 아니다.
"""
import fitz

from app.ai.preprocessor.pdf_analyzer import box_rects

INK = (0.2, 0.4, 0.6)


def _page():
    doc = fitz.open()
    return doc, doc.new_page(width=584, height=737)


def _rects(pg):
    return [[round(v) for v in r] for r in box_rects(pg)]


def _overhang(pg, x0, top, x1, bottom, over):
    """오른쪽 변(x1)을 `over` pt 넘는 한 줄 글을 품은 상자를 그린다."""
    pg.draw_rect(fitz.Rect(x0, top, x1, bottom), color=INK, width=0.3)
    s = "justified text line"
    w = fitz.get_text_length(s, fontsize=10)
    pg.insert_text((x1 + over - w, (top + bottom) / 2), s, fontsize=10)


def test_글_블록이_테두리를_조금_넘어도_상자다():
    doc, pg = _page()
    _overhang(pg, 100, 200, 300, 300, 3)
    assert _rects(pg) == [[100, 200, 300, 300]]


def test_낮은_머리띠와_크게_넘는_글은_상자가_아니다():
    for top, bottom, over in ((30, 55, 1), (200, 300, 8)):
        doc, pg = _page()
        _overhang(pg, 100, top, 300, bottom, over)
        assert _rects(pg) == [], (top, bottom, over)


def test_다른_상자_안의_글_삐짐_틀은_버린다():
    doc, pg = _page()
    pg.draw_rect(fitz.Rect(80, 150, 500, 500), color=INK, width=1)
    pg.insert_text((100, 180), "outer box text", fontsize=10)
    _overhang(pg, 100, 300, 300, 400, 3)
    assert _rects(pg) == [[80, 150, 500, 500]]
