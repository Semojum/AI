"""#1303 추출에서 빠진 본문 줄을 그 자리 글 요소에 원본 글자층으로 되살린다 — preprocessor.lost_lines.

합성 쪽(PyMuPDF 한글 글꼴)으로 층 줄을 만들고, 경계 요소 · 손실 목록은 손으로 적는다.
"""
import fitz
import pytest

from app.ai.parser import extraction_losses as EL
from app.ai.preprocessor import lost_lines as LL

ROWS = ["가. 사과는 빨갛고 둥글고 맛있다.", "나. 하늘은 파랗고 넓고 시원하다.", "다. 바다는 깊고 푸르고 넓구나."]   # 줄마다 문장 끝(줄 잇기가 안 잇는다)


def _page(rows, x=60, y=100, gap=20):
    doc = fitz.open()
    page = doc.new_page(width=600, height=800)
    for i, t in enumerate(rows):
        page.insert_text((x, y + gap * i), t, fontname="korea", fontsize=11)
    return page


def _box(page, *idx, pad=4):
    """층 줄(차례 idx)들을 감싸는 0~1000 사각형."""
    bs = [EL._norm(EL._layer_lines(page)[i][0], page) for i in idx]
    return [min(b[0] for b in bs) - pad, min(b[1] for b in bs) - pad, max(b[2] for b in bs) + pad, max(b[3] for b in bs) + pad]


def _loss(page, i, **kw):
    return dict({"class": "unseen", "source": "textlayer", "region": "text",
                 "text": EL._layer_lines(page)[i][1], "bbox": _box(page, i, pad=0)}, **kw)


def test_끼우기_빠진_줄을_앞뒤_줄_사이에_넣는다():
    page = _page(ROWS)
    el = {"id": "a", "type": "text", "content": f"{ROWS[0]}\n{ROWS[2]}", "bbox": _box(page, 0, 1, 2)}
    got = LL.restore_lost_lines([el], [_loss(page, 1)], page, False)
    assert el["content"] == f"{ROWS[0]}\n{ROWS[1]}\n{ROWS[2]}"
    assert got == {EL._layer_lines(page)[1][1]: (ROWS[1], 0)}


def test_채우기_한글이_없는_요소는_그_자리_줄로_채우고_태그는_남긴다():
    page = _page(["② 하늘은 파랗고 넓다 시원하다"])
    el = {"id": "a", "type": "text", "content": "<!2칸>②，", "bbox": _box(page, 0)}
    LL.restore_lost_lines([el], [_loss(page, 0)], page, False)
    assert el["content"] == "<!2칸>② 하늘은 파랗고 넓다 시원하다"


def test_채우기로_지워질_번호가_넣을_글에_없으면_안_채운다():
    """언매 p0122 꼴: 시간 줄 요소 '12:30' 자리에 다른 줄(식당 이름)을 넣으면 시간이 사라진다."""
    page = _page(["하늘은 파랗고 넓다 시원하다"])
    el = {"id": "a", "type": "text", "content": "12:30", "bbox": _box(page, 0)}
    assert LL.restore_lost_lines([el], [_loss(page, 0)], page, False) == {}
    assert el["content"] == "12:30"


def test_층_차례와_요소_글_차례가_어긋나면_안_넣는다():
    page = _page(ROWS)
    el = {"id": "a", "type": "text", "content": f"{ROWS[2]}\n{ROWS[0]}", "bbox": _box(page, 0, 1, 2)}
    assert LL.restore_lost_lines([el], [_loss(page, 1)], page, False) == {}
    assert el["content"] == f"{ROWS[2]}\n{ROWS[0]}"


def test_윗줄_문장을_잇는_줄은_다른_요소에_넣지_않는다():
    """동아시아사 p0020 꼴: 문장 앞머리('…문화를 대표')가 다른 요소에 있으면 뒷줄을 이 요소에 넣지 않는다."""
    page = _page(["달한 양사오 문화를 대표하는 그릇으로", "하늘은 파랗고 넓다 시원하다 그렇다"], gap=16)
    a = {"id": "a", "type": "text", "content": "달한 양사오 문화를 대표하는 그릇으로", "bbox": _box(page, 0)}
    b = {"id": "b", "type": "text", "content": "，", "bbox": _box(page, 1)}
    assert LL.restore_lost_lines([a, b], [_loss(page, 1)], page, False) == {}
    assert b["content"] == "，"


def test_그_자리가_표_요소면_안_넣는다():
    page = _page(["하늘은 파랗고 넓다 시원하다"])
    el = {"id": "a", "type": "table", "content": "<table><tr><td>，</td></tr></table>", "bbox": _box(page, 0)}
    assert LL.restore_lost_lines([el], [_loss(page, 0, region="table")], page, False) == {}


def test_끄면_안_넣는다(monkeypatch):
    page = _page(["② 하늘은 파랗고 넓다 시원하다"])
    el = {"id": "a", "type": "text", "content": "②，", "bbox": _box(page, 0)}
    monkeypatch.setenv("LOST_TEXT_RESTORE", "0")
    assert LL.restore_lost_lines([el], [_loss(page, 0)], page, False) == {}
    assert el["content"] == "②，"


def test_손실_하나는_다_넣거나_하나도_안_넣는다():
    """두 줄 손실의 한 줄은 채울 수 있어도 다른 줄이 표 자리면 둘 다 안 넣는다(요소 글이 그대로다)."""
    page = _page(["② 하늘은 파랗고 넓다 시원하다", "③ 바다는 깊고 푸르다 넓구나 정말"])
    a = {"id": "a", "type": "text", "content": "②", "bbox": _box(page, 0)}
    t = {"id": "t", "type": "table", "content": "<table><tr><td>③</td></tr></table>", "bbox": _box(page, 1)}
    x = {"class": "unseen", "source": "textlayer", "region": "text",
         "text": "\n".join(t_ for _r, t_ in EL._layer_lines(page)), "bbox": _box(page, 0, 1, pad=0)}
    assert LL.restore_lost_lines([a, t], [x], page, False) == {}
    assert a["content"] == "②"


def test_수식_쪽은_안_넣는다():
    page = _page(["② 하늘은 파랗고 넓다 시원하다"])
    el = {"id": "a", "type": "text", "content": "②，", "bbox": _box(page, 0)}
    assert LL.restore_lost_lines([el], [_loss(page, 0)], page, True) == {}
