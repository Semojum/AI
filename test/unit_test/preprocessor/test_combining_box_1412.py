"""#1412 결합 네모 U+20DE 로 적힌 네모 문자 — 홀로 선 한 글자만 네모 문자 태그로(규정 제64항).

묵자 글자층에서 수학Ⅰ 해설의 정답 표시는 `답⃞ ⑤` 꼴이고 gold 는 `⠸⠦⠊⠃⠴⠇⠀⠼⠢` 다. 네모 글자가 이어진 `정⃞답⃞` 은
장식 배지라 gold 가 네모 없이 `정답` 으로 적는다(원장 C-16-3).
"""
from app.ai.braille.translator import translate_tagged_text
from app.ai.preprocessor.pdf_analyzer import tag_combining_boxes


def _el(content, typ="text"):
    return {"type": typ, "content": content}


def test_홀로_선_결합_네모는_네모_문자_태그가_된다():
    els = [_el("<!2칸>답⃞ ⑤")]
    assert tag_combining_boxes(els) == 1
    assert els[0]["content"] == "<!2칸><!네모글>답<!/네모글> ⑤"


def test_한_낱말을_이룬_결합_네모는_그대로_둔다():
    els = [_el("정⃞답⃞", "title"), _el("본문 정⃞답⃞  1. 가치")]
    assert tag_combining_boxes(els) == 0
    assert els[0]["content"] == "정⃞답⃞"


def test_글_요소_밖은_건드리지_않는다():
    els = [_el("답⃞", "formula"), _el("답⃞", "table")]
    assert tag_combining_boxes(els) == 0


def test_끄면_그대로다(monkeypatch):
    monkeypatch.setenv("BOX_CHAR_COMBINING", "0")
    els = [_el("답⃞ ⑤")]
    assert tag_combining_boxes(els) == 0
    assert els[0]["content"] == "답⃞ ⑤"


def test_점자는_제64항_네모_문자로_나간다():
    els = [_el("답⃞ ⑤"), _el("정⃞답⃞", "title")]
    tag_combining_boxes(els)
    assert translate_tagged_text(els[0]["content"]) == "⠸⠦⠊⠃⠴⠇⠀⠼⠢"
    assert translate_tagged_text(els[1]["content"]) == "⠨⠻⠊⠃"      # 장식 배지는 네모 없이


def test_네모_문자_태그만으로는_R13_이_안_붙는다():
    from app.ai.quality.quality_checker import _r13_reason
    assert _r13_reason("<!네모글>답<!/네모글> ⑤") is None
    assert "레이아웃 태그" in _r13_reason("<!상자>보기<!/상자>\nㄱ. 가")       # 테두리 태그는 그대로
    assert "아라비아 숫자" in _r13_reason("<!네모글>(가)<!/네모글> 12와 34")   # 다른 사유는 그대로
