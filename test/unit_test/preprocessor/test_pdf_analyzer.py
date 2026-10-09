import sys
from pathlib import Path

import fitz
import pytest

sys.path.insert(0, str(Path(__file__).parents[3]))

from app.ai.preprocessor.pdf_analyzer import analyze_pdf
from app.schemas.layout import DocumentMeta


@pytest.fixture(scope="module")
def sample_pdf(tmp_path_factory) -> Path:
    """세 쪽 합성 PDF. 1쪽 글 + 그림(쪽 넓이 8%), 2쪽 글 + 선으로 그은 표, 3쪽 글만.

    예전에는 바깥 자료 열 쪽 묶음(`test/samples/test.pdf`)의 1쪽을 읽었다(#1257). 그 쪽은
    글자층이 있고 그림 하나가 쪽 넓이의 3.01%(그림 문턱 3% 를 겨우 넘음)였고 1×2 표도 있었다.
    여기서는 STANDARD 로 가는 두 길(그림 · 표)을 쪽 하나씩으로 나눠 본다. 마지막 쪽을 글만
    두는 것은, 0쪽이 첫 쪽 말고 다른 쪽(doc[-1] 등)으로 가면 결과가 달라지게 하려는 것이다.
    """
    doc = fitz.open()
    page = doc.new_page()                                        # A4 595×842pt
    page.insert_text((72, 72), "Picture page abc 123")
    pix = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 64, 64), False)
    pix.clear_with(200)
    page.insert_image(fitz.Rect(72, 100, 272, 300), pixmap=pix)  # 200×200pt
    page = doc.new_page()
    page.insert_text((72, 72), "Table page abc 123")
    ys, xs = (100, 140, 180, 220), (72, 172, 272, 372)
    for y in ys:
        page.draw_line(fitz.Point(xs[0], y), fitz.Point(xs[-1], y))
    for x in xs:
        page.draw_line(fitz.Point(x, ys[0]), fitz.Point(x, ys[-1]))
    for i, y in enumerate(ys[:-1]):
        for j, x in enumerate(xs[:-1]):
            page.insert_text((x + 8, y + 24), f"cell {i}{j}")
    page = doc.new_page()
    page.insert_text((72, 72), "Text only page, no picture and no table. abc 123")
    path = tmp_path_factory.mktemp("pdf") / "sample.pdf"
    doc.save(path)
    doc.close()
    return path


def test_sample_pages_make_the_conditions(sample_pdf):
    """아래 시험의 전제: 세 쪽 모두 글자층이 있고, 1쪽만 그림(3% 넘음) · 2쪽만 표가 있다."""
    doc = fitz.open(sample_pdf)
    p1, p2, p3 = doc
    area = p1.rect.width * p1.rect.height
    assert all(p.get_text().strip() for p in doc)
    boxes = [i["bbox"] for i in p1.get_image_info()]
    assert len(boxes) == 1
    x0, y0, x1, y1 = boxes[0]
    assert (x1 - x0) * (y1 - y0) > 0.03 * area
    assert not p1.find_tables().tables
    assert p2.find_tables().tables and not p2.get_image_info()
    assert not p3.find_tables().tables and not p3.get_image_info()
    doc.close()


def test_returns_tuple(sample_pdf):
    result = analyze_pdf(str(sample_pdf), 1)
    assert isinstance(result, tuple) and len(result) == 2
    doc_meta, page_text = result
    assert isinstance(doc_meta, DocumentMeta)
    assert isinstance(page_text, str)


@pytest.mark.parametrize("page_no", [1, 2], ids=["그림", "표"])
def test_visual_page_routes_standard(sample_pdf, page_no):
    # 글자층이 있어도 그림(쪽 3% 넘게)이나 선 있는 표가 있으면 MinerU(STANDARD).
    doc_meta, _ = analyze_pdf(str(sample_pdf), page_no)
    assert doc_meta.routing_tier == "STANDARD", f"이미지·표 포함 페이지는 STANDARD, 실제: {doc_meta.routing_tier}"


def test_pure_text_routes_zero():
    # 그림·표 없는 순수 텍스트 페이지만 ZERO(빠른 직접추출).
    import fitz
    d = fitz.open()
    d.new_page().insert_text((72, 72), "순수 텍스트만 있는 페이지입니다 그림도 표도 없습니다 abc 123")
    meta, text = analyze_pdf(d.tobytes(), 1)
    d.close()
    assert meta.routing_tier == "ZERO" and len(text) > 0


def test_accepts_bytes(sample_pdf):
    meta_b, text_b = analyze_pdf(sample_pdf.read_bytes(), 1)
    meta_p, text_p = analyze_pdf(str(sample_pdf), 1)
    assert isinstance(meta_b, DocumentMeta)
    assert (meta_b.routing_tier, text_b) == (meta_p.routing_tier, text_p)


def test_zero_indexed_page_correction(sample_pdf):
    doc_meta_1indexed, text_1 = analyze_pdf(str(sample_pdf), 1)
    doc_meta_0indexed, text_0 = analyze_pdf(str(sample_pdf), 0)
    assert doc_meta_1indexed.routing_tier == doc_meta_0indexed.routing_tier
    assert text_1 == text_0
    # 마지막 쪽은 결과가 달라야 위 비교가 '0쪽 → 마지막 쪽(doc[-1])' 같은 어긋남을 잡는다.
    assert analyze_pdf(str(sample_pdf), 3)[0].routing_tier != doc_meta_1indexed.routing_tier


def test_table_grid_rules_are_not_underlines():
    """표·상자의 가로 구분선을 밑줄로 보면 안 된다 (F04, 대표 지적).

    대표는 "제목행이라서가 아니라 굵은 글씨라서 붙인 것 아닌가" 하셨는데 실물은 그것도
    아니었다 — **표의 열 구분선**이 밑줄로 잡히고 있었다. 가르는 신호는 같은 x-분할이
    여러 y 에서 되풀이되는 것(격자)이다. 진짜 밑줄은 줄마다 분할이 다르다.
    """
    import fitz

    from app.ai.preprocessor.pdf_analyzer import underline_rects

    doc = fitz.open()
    page = doc.new_page(width=600, height=800)
    # 표 격자 — 같은 x 분할이 세 y 에서 되풀이된다
    for y in (200, 240, 300):
        for x0, x1 in ((80, 140), (140, 300), (300, 460)):
            page.draw_line(fitz.Point(x0, y), fitz.Point(x1, y), width=0.4)
    # 진짜 밑줄 — 한 줄에만, 분할도 다르다
    page.draw_line(fitz.Point(90, 500), fitz.Point(150, 500), width=0.4)
    page.draw_line(fitz.Point(200, 500), fitz.Point(233, 500), width=0.4)
    ys = {round(r.y0) for r in underline_rects(page)}
    assert 200 not in ys and 240 not in ys and 300 not in ys, ys   # 격자는 빠진다
    assert 500 in ys, ys                                          # 진짜 밑줄은 남는다
    doc.close()
