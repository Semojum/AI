"""그림으로 잘린 정답 표기 `답 ⑤` 를 글로 돌린다(#1045 · 원장 C-70 후속 3).

2027 국어 정답편은 문항 머리 옆 `답 ⑤` 를 gold 가 제 줄에 적는데, MinerU 가 그림으로 잘라 오면
캡션이 `그림: 답 ⑤` 가 되고 가드4 의 `답` 무늬가 장식으로 버렸다. 판정은 캡션이 아니라
**그 자리 텍스트층**으로 한다.
"""
import json

import fitz
import pytest

from app.ai.parser import mineru_runner as mr

W, H = 600, 800
MARK = [495, 480, 560, 508]        # "답 ⑤" 가 그려진 자리(0~1000)
HEAD = [95, 480, 260, 508]         # 같은 줄 왼쪽의 문항 제목
LONG = [495, 730, 700, 758]        # "답 ⑤ 해설" — 표기 한 줄뿐이 아니다


def _doc():
    doc = fitz.open()
    page = doc.new_page(width=W, height=H)
    page.insert_text((300, 400), "답 ⑤", fontname="korea", fontsize=11)
    page.insert_text((60, 400), "04 부정 표현", fontname="korea", fontsize=11)
    page.insert_text((300, 600), "답 ⑤ 해설", fontname="korea", fontsize=11)
    return doc


def test_lone_answer_mark_reads_as_text():
    assert mr._answer_mark_text(_doc()[0], MARK) == "답 ⑤"


@pytest.mark.parametrize("bbox", [HEAD, LONG, [100, 100, 300, 200]], ids=["제목", "표기+글", "빈 자리"])
def test_anything_else_is_not_an_answer_mark(bbox):
    assert mr._answer_mark_text(_doc()[0], bbox) is None


def _raw(tmp_path):
    """MinerU 원출력 흉내: 정답 표기를 그림으로 자른 조각이 **먼저** 나오고 그 줄의 문항 제목이 뒤에 온다."""
    raw = tmp_path / "raw"
    (raw / "images").mkdir(parents=True)
    fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 40, 20), 0).save(str(raw / "images" / "mark.jpg"))
    (raw / "p_content_list.json").write_text(json.dumps([
        {"type": "image", "img_path": "images/mark.jpg", "bbox": MARK},
        {"type": "text", "text": "04 부정 표현", "bbox": HEAD, "text_level": 1},
    ], ensure_ascii=False), encoding="utf-8")
    return raw


@pytest.mark.parametrize("switch, want", [("", ("text", "답 ⑤")), ("0", ("image", "이미지 캡셔닝 대기"))],
                         ids=["기본", "끔=종전"])
def test_run_turns_the_cropped_mark_into_text(tmp_path, monkeypatch, switch, want):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("ANSWER_MARK_TEXT", switch) if switch else monkeypatch.delenv("ANSWER_MARK_TEXT", raising=False)
    _doc().save(str(tmp_path / "p.pdf"))
    els = mr.run(str(tmp_path / "p.pdf"), 1, "job", "TEXT_NATIVE", mineru_cache_dir=str(_raw(tmp_path)))
    mark = next(e for e in els if e["bbox"] == MARK)
    assert (mark["type"], mark["content"]) == want
    if not switch:                  # gold 자리 = 같은 줄 문항 제목 바로 뒤
        assert [e["bbox"] for e in els] == [HEAD, MARK]
        assert [e["reading_order"] for e in els] == [1, 2]


def _el(eid, bbox):
    return {"element_id": eid, "bbox": list(bbox), "reading_order": 0}


def test_multiline_neighbour_is_not_a_seat():
    """같은 높이에 옆 단 문단(여러 줄)만 있으면 옮기지 않는다 — 옆 단으로 건너가면 안 된다."""
    els = [_el("m", MARK), _el("p", [95, 400, 480, 600])]
    mr._seat_answer_marks(els, {"m"})
    assert [e["element_id"] for e in els] == ["m", "p"]
