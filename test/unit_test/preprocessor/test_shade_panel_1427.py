"""#1427 글상자 안 음영 패널은 속글상자(2단계)로 감싼다.

묵자 세계사 본문 114쪽 `자료 플러스 · 백인의 짐`: 획으로 그린 바깥 상자 안에 회색으로만 칠한 패널(시 인용)이 있다.
gold 는 바깥 1단계 상자 안에서 시 부분만 2단계 속글상자(`⠖⠒…⠲` · `⠓⠒…⠚`)로 감싼다.
「점자 도서 제작 지침」 1장 2절 5. 1)(재추출 388~389행) 음영 글상자도 글상자 · 2)(3)(396~397행) 속글상자 테두리 ·
3장 3) 지문 (4)(3094~3095행) 지문 안의 또 다른 글상자는 속글상자.
"""
import fitz

from app.ai.braille.translator import translate_tagged_text
from app.ai.preprocessor.pdf_analyzer import box_rects, shade_panels, tag_boxed_elements

OUTER = fitz.Rect(148, 203, 521, 338)
INNER = fitz.Rect(157, 198, 513, 256)          # 바깥 상자 윗변보다 5pt 위에서 시작한다(실물은 6pt 안팎)
GRAY = (0.92, 0.92, 0.93)


def _page(inner=INNER, fill=GRAY):
    doc = fitz.open()
    pg = doc.new_page(width=584, height=737)
    pg.draw_rect(OUTER, color=(0.5, 0.3, 0.6), width=1)
    pg.draw_rect(inner, color=None, fill=fill)
    pg.insert_text((170, 230), "poem line one", fontsize=10)
    pg.insert_text((170, 300), "commentary", fontsize=10)
    return doc, pg


def test_바깥_상자_안의_음영_패널을_잡고_부모로_자른다():
    doc, pg = _page()
    got = shade_panels(pg, box_rects(pg))
    assert len(got) == 1 and got[0] in OUTER and got[0].y0 == OUTER.y0


def test_흰_채움_좌우_여백_없음_상자_밖은_안_잡는다():
    for inner, fill in ((INNER, (1.0, 1.0, 1.0)),                        # 흰 마스크
                        (fitz.Rect(148, 210, 521, 256), GRAY),           # 여백 0 = 부모 바탕 칠
                        (fitz.Rect(157, 400, 513, 450), GRAY)):          # 획 상자 밖
        doc, pg = _page(inner, fill)
        assert shade_panels(pg, box_rects(pg)) == []


OUT_N = [253, 275, 892, 458]                    # 0~1000 정규화(경계 bbox 와 같은 좌표)
PANEL_N = [269, 275, 878, 347]


def _els(*kinds):
    spec = {"poem": [272, 280, 871, 322], "comment": [262, 352, 881, 449], "title": [267, 255, 423, 270]}
    return [{"type": "table" if k == "table" else ("title" if k == "title" else "text"),
             "bbox": spec["poem" if k == "table" else k],
             "content": "<table></table>" if k == "table" else k} for k in kinds]


def test_속글상자_태그가_바깥_안쪽에_들고_안쪽부터_닫힌다():
    els = _els("poem", "comment")
    assert tag_boxed_elements(els, [OUT_N, PANEL_N], panels={tuple(PANEL_N)}) == 2
    assert els[0]["content"] == "<!상자><!/상자>\n<!상자2><!/상자2>\npoem\n<!상자끝2><!/상자끝2>"
    assert els[1]["content"] == "comment\n<!상자끝><!/상자끝>"
    lines = translate_tagged_text(els[0]["content"]).split("\n")
    assert lines[1] == "⠖" + "⠒" * 30 + "⠲" and lines[-1] == "⠓" + "⠒" * 30 + "⠚"


def test_패널은_제목을_올리지_않는다():
    """패널 윗변에 걸친 짧은 줄을 패널 테두리 제목으로 올리면 바깥 상자 본문 줄이 사라진다."""
    outer, panel = [253, 275, 892, 600], [269, 400, 878, 500]
    els = [{"type": "text", "bbox": [272, 300, 871, 340], "content": "intro"},
           {"type": "text", "bbox": [300, 392, 420, 407], "content": "label"},
           {"type": "text", "bbox": [272, 420, 871, 480], "content": "quote"},
           {"type": "text", "bbox": [262, 520, 881, 580], "content": "comment"}]
    tag_boxed_elements(els, [outer, panel], panels={tuple(panel)})
    assert els[1]["content"] == "label" and els[2]["content"] == "<!상자2><!/상자2>\nquote\n<!상자끝2><!/상자끝2>"


def test_패널_안에_표가_들면_감싸지_않는다():
    els = _els("table", "comment")
    els.insert(0, {"type": "text", "bbox": [272, 330, 871, 345], "content": "caption"})
    tag_boxed_elements(els, [OUT_N, PANEL_N], panels={tuple(PANEL_N)})
    assert not any("상자2" in e["content"] for e in els)
