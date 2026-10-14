"""#1352 ① — MinerU 가 수식 뒤 조사 '이'를 `\\circ |` 로 읽은 자리를 R4(환각 의심)로 표시한다.

점역하면 합성 기호 ∘(「수학 점자」 제15항 5호 ⠸⠴)가 찍히고 조사가 빠진다. 글 요소의 `$…$` 는 글 검사가 LaTeX 명령을
걷어 내 못 봤고(생명과학 해설 7요소), 수식 요소는 한자가 같이 나온 것만 걸렸다. 쪽 층에 ∘ 가 있으면 진짜 합성이라 뺀다.
층은 `_page_layer_norm` 이 내는 꼴(NFKC · 빈칸 없음 · 소문자)로 준다.
"""
import fitz

from app.ai.parser import mineru_runner as M

LINE = [90, 225, 700, 260]


def _page(text: str):
    doc = fitz.open()
    page = doc.new_page(width=600, height=800)
    page.insert_text((60, 200), text, fontname="korea", fontsize=11)
    return doc, page


def test_수식의_circ_막대는_신호다():
    layer = M._halluc_norm("따라서 d4이다")
    assert M._halluc_struct_signs(r"d_{4} \circ | \tau |", "formula", layer) == ["\\circ|"]


def test_층에_합성_기호가_있으면_신호가_아니다():
    layer = M._halluc_norm("(f∘g)(x) = |x|")
    assert M._halluc_struct_signs(r"f \circ |x|", "formula", layer) == []


def test_한자와_같이_나오면_둘_다_적는다():
    layer = M._halluc_norm("a 이므로")
    assert M._halluc_struct_signs(r"a \circ | \text{旦}", "formula", layer) == ["旦", "\\circ|"]


def test_글_요소의_수식_구간도_표시한다(monkeypatch):
    doc, page = _page("따라서 d4이다.")
    mineru = r"따라서 $d_{4} \circ | \tau |$."
    assert M._native_or_flag(page, LINE, mineru, lambda: M._page_layer_norm(page)) == (mineru, True)
    monkeypatch.setattr(M, "_HALLUC_RULE", False)                  # 종전: 글 검사가 LaTeX 명령을 걷어 신호가 없었다
    assert M._native_or_flag(page, LINE, mineru, lambda: M._page_layer_norm(page))[1] is False
