"""수식 글꼴 가드가 요소 자리를 제대로 본다(#1047).

한컴 수식 글꼴(EH·ST)은 텍스트층이 글자를 잘못 알려 준다(`log` → `MPH`, `≤` → `\\x83`). 가드는 그 자리에
층 대신 MinerU OCR 을 둔다(`MINERU_MATH_FONT_GUARD`). 종전에는 MinerU 의 0~1000 bbox 를 pt 로 알고 잘라
엉뚱한 자리를 봤고(d8c dev 깨진 글꼴 요소 49개 중 25개만 걸림), 회전 쪽은 표시 좌표로 잘라 늘 빈 글이었다.
층 글과 같은 줄(`_layer_lines`)을 보게 고쳤다. 시험 PDF 에는 한컴 글꼴이 없어 Helvetica 를 수식 글꼴로 친다.
"""
import re

import fitz
import pytest

from app.ai.parser import mineru_runner as mr

W, H = 600, 800


@pytest.fixture(autouse=True)
def _helv_is_math_font(monkeypatch):
    monkeypatch.setattr(mr, "_MATH_FONT_RE", re.compile(r"^Helv"))


def _page(rotation=0):
    doc = fitz.open()
    page = doc.new_page(width=W, height=H)
    page.insert_text((400, 600), "MPH", fontname="helv", fontsize=12)     # 수식 글꼴이 그린 `log`
    page.insert_text((60, 100), "보통 글", fontname="korea", fontsize=12)  # 본문 글꼴
    page.set_rotation(rotation)
    return doc, page


def _norm(page, text):
    """그 글이 그려진 자리의 0~1000 bbox. MinerU 처럼 표시(회전 뒤) 좌표로 준다."""
    r = fitz.Rect()
    for q in page.search_for(text):               # 낱말마다 조각으로 돌려준다 — 합쳐서 줄 전체로
        r |= q
    r = r * page.rotation_matrix
    w, h = page.rect.width, page.rect.height
    return [r.x0 / w * 1000, r.y0 / h * 1000, r.x1 / w * 1000, r.y1 / h * 1000]


@pytest.mark.parametrize("rotation", [0, 90, 270])
def test_수식_글꼴_자리를_찾는다(rotation):
    doc, page = _page(rotation)
    assert mr._has_math_font(page, _norm(page, "MPH"))


@pytest.mark.parametrize("rotation", [0, 90])
def test_본문_글꼴_자리는_아니다(rotation):
    doc, page = _page(rotation)
    bb = _norm(page, "보통 글")
    assert mr._native_text_spaced(page, bb)           # 줄은 골랐다 — 글꼴만 본문이다
    assert not mr._has_math_font(page, bb)


def test_빈_자리는_아니다():
    doc, page = _page()
    assert not mr._has_math_font(page, [0, 900, 100, 1000])


def test_0에서_1000_bbox_를_pt_로_잘라_보면_놓친다():
    """종전 판정(`clip=fitz.Rect(bbox)`)이 이 자리를 놓쳤다는 것을 고정한다 — 고침이 되돌아가면 위 시험이 깨진다."""
    doc, page = _page()
    bb = _norm(page, "MPH")
    assert not page.get_text("text", clip=fitz.Rect(bb)).strip()


def test_스위치를_켜면_수식_글꼴_자리는_층_대신_OCR(monkeypatch):
    doc, page = _page()
    monkeypatch.setattr(mr, "_MATH_FONT_GUARD", True)
    # MinerU 글을 층과 같게 줘서 닮음 검사가 아니라 가드만 None 을 내게 한다
    assert mr._native_override(page, _norm(page, "MPH"), "MPH") is None
    assert mr._native_override(page, _norm(page, "보통 글"), "보통 글") == "보통 글"


def test_스위치를_끄면_종전대로_층을_쓴다(monkeypatch):
    doc, page = _page()
    monkeypatch.setattr(mr, "_MATH_FONT_GUARD", False)
    assert mr._native_override(page, _norm(page, "MPH"), "MPH") == "MPH"


def test_스위치를_켜도_MinerU_글이_비면_층을_쓴다(monkeypatch):
    """켠 팔이 글을 통째로 잃지 않게 한다 — 수학 I p0012 상용로그표 설명 문단이 빈 글이 됐다."""
    doc, page = _page()
    monkeypatch.setattr(mr, "_MATH_FONT_GUARD", True)
    assert mr._native_override(page, _norm(page, "MPH"), "") == "MPH"
