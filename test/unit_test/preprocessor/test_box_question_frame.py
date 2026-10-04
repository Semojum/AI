"""안쪽 상자를 품은 문항 틀은 글상자가 아니다(#1110) — 자기 몫 글에 발문 · 선택지가 있고 안쪽 상자가 있는 사각형만 뺀다."""
from app.ai.preprocessor.pdf_analyzer import drop_question_frames


def _el(text, bb):
    return {"type": "text", "content": text, "bbox": bb}


def test_문항_틀은_빼고_안쪽_자료_상자는_남긴다():
    frame, inner = [50, 50, 950, 950], [100, 200, 900, 500]          # 동아시아사 p0015 꼴: 틀 안에 자료 상자
    els = [_el("(가) 왕조 시기에 있었던 사실로 옳은 것은?", [100, 100, 900, 150]),
           _el("이 유물은 (가) 시기에 사용된 곡식의 양을 측정하는 기구이다.", [150, 250, 850, 450]),
           _el("① 고조선이 멸망하였다.", [100, 600, 900, 640])]
    assert drop_question_frames(els, [frame, inner]) == [inner]


def test_발문이_없는_바깥_상자는_남긴다():
    outer, inner = [50, 50, 950, 950], [100, 300, 900, 600]           # 생명과학 '탐구자료 살펴보기' 꼴: 겹상자
    els = [_el("탐구 활동 1 세포 분열 과정을 관찰한다.", [100, 100, 900, 250]),
           _el("과정 현미경으로 관찰한다.", [150, 350, 850, 550])]
    assert drop_question_frames(els, [outer, inner]) == [outer, inner]


def test_안쪽_상자가_없는_문항_틀은_남긴다():
    frame = [50, 50, 950, 950]                                          # 수학 Ⅰ 꼴: gold 가 문항을 통째로 상자로 적는다(원장 C-157)
    els = [_el("함수 f(x)의 최댓값은?", [100, 100, 900, 300]),
           _el("① 1  ② 2  ③ 3  ④ 4  ⑤ 5", [100, 600, 900, 640])]
    assert drop_question_frames(els, [frame]) == [frame]

