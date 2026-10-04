"""#1078 — MinerU 가 지어낸 글(원본 텍스트층에 없는 한자 · 로마자 낱말 · 되풀이)을 층 글로 바꾸거나 R4 로 표시한다.

2027 dev·val 1,746쪽 중 96쪽에 환각이 있었고(temp/n84, 눈검사 10/10), 그 쓰레기가 닮음을 끌어내려 멀쩡한 층이
닮음 문턱(0.45)에 막혔다. LaTeX 없는 요소는 문턱 없이 층 글로, LaTeX 있는 요소와 못 덮은 요소는 표시만 한다.
"""
import fitz

from app.ai.parser import mineru_runner as M

W, H = 600, 800
CHOICE = [90, 225, 400, 260]       # "② ㄱ, ㄹ" 줄(0~1000)
COS = [90, 350, 700, 385]          # "cos A=cos 90°=0이므로" 줄


def _page():
    doc = fitz.open()
    page = doc.new_page(width=W, height=H)
    page.insert_text((60, 200), "② ㄱ, ㄹ", fontname="korea", fontsize=11)
    page.insert_text((60, 300), "cos A=cos 90°=0이므로", fontname="korea", fontsize=11)
    page.insert_text((60, 500), "사람이 음식을 필요로 하는 것은 인종과 아무런 상관이 없다.", fontname="korea", fontsize=11)
    page.insert_text((60, 600), "교초(交) 발행", fontname="korea", fontsize=11)
    page.insert_text((60, 700), "commu-", fontname="helv", fontsize=11)
    page.insert_text((60, 714), "nication", fontname="helv", fontsize=11)
    return doc, page


def _layer(page):
    return lambda: M._page_layer_norm(page)


def test_한자로_지어낸_보기를_층_글로_바꾼다(monkeypatch):
    doc, page = _page()
    layer_text = M._native_text_spaced(page, CHOICE)              # "② ㄱ,  ㄹ"(합성 글꼴 띄움 그대로)
    assert "ㄱ" in layer_text and M._native_or_flag(page, CHOICE, "② 丿，己", _layer(page)) == (layer_text, False)
    monkeypatch.setattr(M, "_HALLUC_RULE", False)                  # 종전: 닮음 0.25 라 문턱에 막혔다
    assert M._native_or_flag(page, CHOICE, "② 丿，己", _layer(page)) == ("② 丿，己", False)


def test_LaTeX_든_요소는_덮지_않고_표시한다():
    """수학은 층이 첨자 · 분수를 평평하게 적는다. 덮으면 MinerU 가 바르게 읽은 구조를 잃는다(수학 I p0054 꼴)."""
    doc, page = _page()
    mineru = "$\\cos A = \\cos 90^{\\circ} = 0$ 且旦豆 $a^{2} = b^{2} + c^{2} - 2bc \\cos A$"
    assert M._native_or_flag(page, COS, mineru, _layer(page)) == (mineru, True)


def test_다른_자리_진짜_글을_붙인_요소는_덮지_않고_표시한다():
    """생활과 윤리 p0164 꼴: 선택지 줄에 쪽의 다른 문단을 붙였다. 덮으면 그 문단이 사라진다."""
    doc, page = _page()
    mineru = "② 丿，己 사람이 음식을 필요로 하는 것은 인종과 아무런 상관이 없다."
    assert M._native_or_flag(page, CHOICE, mineru, _layer(page)) == (mineru, True)


def test_구조_글꼴이_든_자리는_덮지_않는다(monkeypatch):
    monkeypatch.setattr(M, "_native_text_pair", lambda *_a, **_k: ("② ㄱ, ㄹ", "② ㄱ, ㄹ"))
    monkeypatch.setattr(M, "_has_struct_font", lambda *_a, **_k: True)
    assert M._native_override(None, CHOICE, "② 丿，己", "②ㄱ,ㄹ") is None


def test_층에_있는_한자는_신호가_아니고_층에_없는_되풀이는_신호다():
    doc, page = _page()
    lay = M._page_layer_norm(page)
    assert M._halluc_signs("교초(交) 발행", lay) == []
    signs = M._halluc_signs("함수 y=2^x의 최,  최,  최,  최,  최,  최,", lay)
    assert len(signs) == 1 and signs[0].startswith("최,  최,")


def test_LaTeX_명령_이름은_로마자_신호가_아니다():
    assert M._halluc_signs("$\\overline{\\mathrm{CH}} = b \\sin A$", "") == []
    assert M._halluc_signs("→ 갈 Lung", "갈퉁") == ["Lung"]


def test_후보가_없으면_쪽_층을_만들지_않는다():
    def boom():
        raise AssertionError("쪽 층을 만들었다")
    assert M._halluc_signs("평범한 본문 글 ① ② ③", boom) == []


def test_영어_줄끝_하이픈을_이은_낱말은_층에_있다():
    doc, page = _page()
    assert M._halluc_signs("communication", M._page_layer_norm(page)) == []


def test_표지는_R4_검토로_간다():
    from app.ai.quality.quality_checker import _FLAG_TO_REVIEW
    assert _FLAG_TO_REVIEW["HALLUCINATION_SUSPECT"][0] == "R4"
