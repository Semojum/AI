"""글로 된 분수(#1183) — 분수선 위 · 아래 글을 `$\\frac{\\text{분자}}{\\text{분모}}$` 로 묶어 수식 점역기가 분모 ⠌ 분자로 적게 한다.

「한국 점자 규정」 제47항(재추출본 2078행): 분수는 분모, 분수표 ⠌, 분자 순. 종전에는 층 글이 분자 · 분모를 그냥 이어
적었다(생명과학 보기 `지점 d₁의 혈압 / 지점 d₂의 혈압`).
"""
import fitz

from app.ai.parser import mineru_runner as mr
from app.ai.preprocessor.pdf_analyzer import text_fractions

def _page():
    doc = fitz.open()
    pg = doc.new_page(width=600, height=800)
    kw = dict(fontsize=12, fontname="korea")            # PyMuPDF 내장 CJK 글꼴(CI 에도 있다)
    pg.insert_text((100, 300), "ㄷ.", **kw)
    pg.insert_text((130, 290), "이산화 탄소", **kw)        # 분자(130~202)
    pg.draw_line((128, 293), (204, 293))                  # 분수선
    pg.insert_text((154, 306), "산소", **kw)               # 분모: 선 바로 아래(0.5pt) · 분자 범위 안 가운데(154~178)
    pg.insert_text((212, 300), "는 1보다 크다.", **kw)
    return doc, pg


def test_분수선_위아래_한글을_분수로_잡는다():
    doc, pg = _page()
    fr = text_fractions(pg)
    assert len(fr) == 1 and len(fr[0][1]) == 5 and len(fr[0][2]) == 2     # 분수선 · 이산화탄소 · 산소


def test_층_글이_분수_꼴이_된다(monkeypatch):
    monkeypatch.delenv("TEXT_FRACTION", raising=False)
    doc, pg = _page()
    fixed = mr._native_text_pair(pg, [0, 0, 1000, 1000])[1]
    assert "$\\frac{\\text{이산화 탄소}}{\\text{산소}}$" in fixed
    assert fixed.count("산소") == 1 and fixed.count("이산화") == 1           # 글을 잃거나 겹쳐 쓰지 않는다
    assert fixed.index("ㄷ.") < fixed.index("\\frac") < fixed.index("는 1")   # 문장 자리에 선다


def test_끈_스위치는_종전처럼_잇는다(monkeypatch):
    monkeypatch.setenv("TEXT_FRACTION", "0")
    doc, pg = _page()
    fixed = mr._native_text_pair(pg, [0, 0, 1000, 1000])[1]
    assert "\\frac" not in fixed and "산소" in fixed and "이산화" in fixed


def test_넣을_줄이_동점이면_앞_줄이다():
    """본문 글자가 없는 분수는 분자 줄 · 분모 줄이 동점이다. 종전엔 줄 id(메모리 주소)로 갈려 실행마다 넣는 줄이 바뀌었다.

    id 가 작은 객체에 앞 줄(분자)을 담아, id 로 고르면 뒤 줄을 고르게 만든다.
    """
    doc = fitz.open()
    pg = doc.new_page(width=600, height=800)
    kw = dict(fontsize=12, fontname="korea")
    pg.insert_text((130, 290), "이산화 탄소", **kw)
    pg.draw_line((128, 293), (204, 293))
    pg.insert_text((154, 306), "산소", **kw)
    (lb0, ln0), (lb1, ln1) = list(mr._layer_lines(pg, [0, 0, 1000, 1000]))
    lo, hi = sorted((dict(), dict()), key=id)
    lo.update(ln0)
    hi.update(ln1)
    out = mr._text_fraction_subs([(lb0, lo), (lb1, hi)], pg.rotation_matrix, text_fractions(pg), None)
    assert any("\\frac" in v for v in out[id(lo)].values())
    assert not any(out[id(hi)].values())
