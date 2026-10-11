"""요소마다 따로 뽑힌 선택지 ①~⑤ 를 한 요소로 잇는다(원장 C-166).

수학Ⅰ 은 MinerU 가 선택지마다 요소를 따로 낸다. 합침(`layout_braille._combine_choice_lines`)은 한 요소 안 줄만 묶어
그 책에서 안 걸렸다. 좌표는 009 body p0005 경계 파일 꼴(0~1000 정규화). gold 는 `⠼⠂⠀⠼⠉⠻⠼⠉⠀⠀⠼⠆⠀⠜⠼⠉⠀⠀⠼⠒⠀⠼⠁` 로 3-2.
"""
from uuid import uuid4

from app.core.pipeline import _parse_txt_result


def _el(content, y):
    return {"id": str(uuid4()), "type": "text", "content": content, "bbox": [120, y, 300, y + 15]}


def _parse(els):
    ex = {"meta": {"extraction_method": "OCR", "bbox_space": "norm1000",
                   "image_width": 1240, "image_height": 1754}, "elements": els}
    lay, em, _ = _parse_txt_result(ex, "p")
    return [(b, em[b.element_id].corrected_text) for b in sorted(lay.elements, key=lambda b: b.reading_order)]


CHOICES = ["<!상자><!/상자>\n① $\\sqrt[3]{3}$", "② $\\sqrt{3}$", "③ 1", "④ 3", "⑤ 9\n<!상자끝><!/상자끝>"]


def test_따로_뽑힌_선택지_다섯을_한_요소로_잇는다():
    out = _parse([_el("다음 중 옳은 것은?", 100)] + [_el(c, 130 + 20 * i) for i, c in enumerate(CHOICES)])
    assert len(out) == 2
    b, text = out[1]
    assert text == "\n".join(CHOICES)                      # 상자 태그 줄까지 차례대로
    assert b.bbox[3] - b.bbox[1] >= (20 * 4 + 15) * 1.7        # 사각형이 다섯을 덮는다(픽셀 배율 1754/1000)


def test_넷이면_잇고_셋이면_두지_않는다():
    four = _parse([_el(c, 130 + 20 * i) for i, c in enumerate(["① 1", "② 2", "③ 3", "④ 4"])])
    assert len(four) == 1 and four[0][1] == "① 1\n② 2\n③ 3\n④ 4"
    three = _parse([_el(c, 130 + 20 * i) for i, c in enumerate(["① 1", "② 2", "③ 3"])])
    assert len(three) == 3


def test_차례가_끊기거나_두_줄_요소면_두지_않는다():
    gap = _parse([_el(c, 130 + 20 * i) for i, c in enumerate(["① 1", "② 2", "④ 4", "⑤ 5", "③ 3"])])
    assert len(gap) == 5
    two_line = _parse([_el(c, 130 + 20 * i) for i, c in enumerate(["① 1\n해설 줄", "② 2", "③ 3", "④ 4", "⑤ 5"])])
    assert len(two_line) == 5


def test_긴_선택지는_잇지_않는다():
    """긴 선택지는 이어도 한 줄로 안 묶인다(요소 id 만 사라진다). 언매 본책 p0173 꼴."""
    long = ["① ‘시청자 1’은 바흐 음악에 대한 설명이 정확한 내용인지를 점검하고 있다.", "② 2", "③ 3", "④ 4", "⑤ 5"]
    assert len(_parse([_el(c, 130 + 20 * i) for i, c in enumerate(long)])) == 5


def test_줄_끝에_붙은_상자_태그는_제_줄로():
    """붙은 채 이으면 원문 줄과 점자 줄(테두리가 제 줄)이 1:1 이 아니게 돼 ② ~ ⑤ 들여쓰기가 빠진다."""
    out = _parse([_el(c, 130 + 20 * i) for i, c in enumerate(["① 1", "② 2", "③ 3", "④ 4", "⑤ 5 <!상자끝><!/상자끝>"])])
    assert out[0][1] == "① 1\n② 2\n③ 3\n④ 4\n⑤ 5\n<!상자끝><!/상자끝>"
    already = _parse([_el(c, 130 + 20 * i) for i, c in enumerate(CHOICES)])   # 이미 제 줄이면 빈 줄을 안 만든다
    assert already[0][1] == "\n".join(CHOICES)


def test_끄기(monkeypatch):
    monkeypatch.setenv("CHOICE_ELEMENT_JOIN", "0")
    assert len(_parse([_el(c, 130 + 20 * i) for i, c in enumerate(CHOICES)])) == 5
