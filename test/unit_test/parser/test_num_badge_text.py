"""텍스트층이 번호뿐인 배지 조각을 추출 단계에서 가른다(#1056 · T45 · 원장 C-70).

단원 · 소단원 번호 배지(`05` · `5` · `2부`)를 MinerU 가 그림으로 잘라 오면 캡셔너가 `그림: 05` 로 써서 점자로
새거나(표지가 안 날 때), 표지로 '생략' 이 되어 제목 앞 번호가 빠졌다. 판정은 캡션이 아니라 그 자리 텍스트층이다.
"""
import json

import fitz
import pytest

from app.ai.builder import result_builder as rb
from app.ai.parser import mineru_runner as mr

W, H = 600, 800
BADGE = [95, 480, 135, 505]         # "01" 배지(0~1000)
TITLE = [138, 480, 420, 505]        # 같은 줄 바로 오른쪽 제목 "뉴 미디어의 특성"


def _doc():
    doc = fitz.open()
    page = doc.new_page(width=W, height=H)
    page.insert_text((60, 400), "01", fontname="helv", fontsize=11)
    page.insert_text((84, 400), "뉴 미디어의 특성", fontname="korea", fontsize=11)
    page.insert_text((60, 600), "2부", fontname="korea", fontsize=11)
    page.insert_text((60, 700), "05 매체 언어", fontname="korea", fontsize=11)
    page.insert_text((60, 650), "3 강", fontname="korea", fontsize=11)
    page.insert_text((300, 200), "1", fontname="helv", fontsize=9)      # 가계도 안 개체 번호 둘
    page.insert_text((300, 215), "2", fontname="helv", fontsize=9)
    return doc


@pytest.mark.parametrize("bbox, want", [
    (BADGE, "01"),
    ([95, 730, 135, 755], "2부"),
    ([95, 855, 400, 880], None),             # 번호 + 글
    ([95, 480, 420, 505], None),             # 번호와 제목을 같이 덮는 자리
    ([0, 0, 1000, 600], None),               # 지면 2% 넘는 큰 조각(층에 번호뿐이어도)
    ([95, 790, 150, 820], "3강"),             # 번호와 `강` 사이 띄움
    ([480, 225, 540, 280], None),            # 그림 안 번호 둘(`1`·`2` 를 `12` 로 붙이지 않는다)
], ids=["번호", "N부", "번호+글", "제목까지", "큰 조각", "N 강", "그림 안 번호 둘"])
def test_층이_번호뿐인_작은_조각만_배지다(bbox, want):
    assert mr._num_badge_text(_doc()[0], bbox) == want


def _el(eid, bbox, content="", heading=None):
    return {"element_id": eid, "bbox": bbox, "content": content, "heading_level": heading}


def test_옆_제목에_번호가_없으면_앞에_붙인다():
    els = [_el("b", BADGE), _el("t", TITLE, "뉴 미디어의 특성", 2)]
    mr._seat_num_badges(els, {"b": "01"})
    assert els[1]["content"] == "01 뉴 미디어의 특성"


@pytest.mark.parametrize("host", [
    _el("t", TITLE, "01 뉴 미디어의 특성", 2),                       # 이미 번호가 있다
    _el("t", TITLE, "날아가는 반응을 하는 것은 자극에 대한 반응의 예", None),   # 본문 문장(제목 아님)
    _el("t", [300, 480, 700, 505], "뉴 미디어의 특성", 2),            # 멀리 떨어진 글
    _el("t", [138, 480, 420, 492], "유학과 불교", 2),                 # 배지가 제목보다 훨씬 크다(단원 표지)
], ids=["번호 있음", "본문", "멀리", "큰 배지"])
def test_그_밖에는_제목을_건드리지_않는다(host):
    before = host["content"]
    mr._seat_num_badges([_el("b", BADGE), host], {"b": "01"})
    assert host["content"] == before


def _raw(tmp_path):
    """MinerU 원출력 흉내: 번호 배지를 그림으로 자른 조각과 같은 줄 제목."""
    raw = tmp_path / "raw"
    (raw / "images").mkdir(parents=True)
    fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 20, 20), 0).save(str(raw / "images" / "badge.jpg"))
    (raw / "p_content_list.json").write_text(json.dumps([
        {"type": "image", "img_path": "images/badge.jpg", "bbox": BADGE},
        {"type": "text", "text": "뉴 미디어의 특성", "bbox": TITLE, "text_level": 2},
    ], ensure_ascii=False), encoding="utf-8")
    return raw


@pytest.mark.parametrize("switch", ["", "0"], ids=["기본", "끔=종전"])
def test_run_은_배지에_표지를_달고_제목에_번호를_붙인다(tmp_path, monkeypatch, switch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("NUM_BADGE_TEXT", switch) if switch else monkeypatch.delenv("NUM_BADGE_TEXT", raising=False)
    _doc().save(str(tmp_path / "p.pdf"))
    els = mr.run(str(tmp_path / "p.pdf"), 1, "job", "TEXT_NATIVE", mineru_cache_dir=str(_raw(tmp_path)))
    badge = next(e for e in els if e["bbox"] == BADGE)
    title = next(e for e in els if e["bbox"] == TITLE)
    assert badge["type"] == "image"                               # 요소는 남는다(#1043)
    if switch:
        assert "DECOR_TEXTLAYER" not in badge["flags"] and not title["content"].startswith("01")
    else:
        assert "DECOR_TEXTLAYER" in badge["flags"] and title["content"].startswith("01 ")


def test_표지_달린_배지는_캡셔너를_안_부르고_표기_없이_뺀다(tmp_path, monkeypatch):
    """지침 6.1 (3)② · (4): 장식용 시각 자료는 생략하고 생략 여부를 알리지 않는다. 캡션을 끈 실행도 같다."""
    monkeypatch.delenv("DISABLE_LLM_FALLBACK", raising=False)
    monkeypatch.setattr(rb, "caption", lambda *a, **k: pytest.fail("캡셔너를 불렀다"))
    monkeypatch.setattr(rb, "classify_with_confidence", lambda *a, **k: pytest.fail("분류기를 불렀다"))
    fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 20, 20), 0).save(str(tmp_path / "badge.jpg"))
    el = {"element_id": "b", "type": "image", "flags": ["DECOR_TEXTLAYER"], "image_path": str(tmp_path / "badge.jpg")}
    for nocap in ("", "1"):
        monkeypatch.setenv("SEMOJUM_NO_CAPTION", nocap)
        assert rb._do_caption(dict(el)) == ("", "image", False, None, "", True)   # 끝 True = 장식(build 가 뺀다)
