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



# 표를 품은 문항 틀(#1149 남은 몫) — 안쪽 사각형이 없어도 5지선다(①~⑤ · ⑥ 없음)나 맨 위 문항 머리가 있으면 뺀다.
def _tb(bb):
    return {"type": "table", "content": "<table><tr><td>[시청자 게시판]</td></tr></table>", "bbox": bb}


def _표와_5지선다():
    return [_tb([100, 60, 900, 500])] + [_el(f"{c} ‘시청자 {i}’는 …", [100, 520 + 60 * i, 900, 560 + 60 * i])
                                         for i, c in enumerate("①②③④⑤")]


def test_표와_5지선다를_품은_틀은_뺀다():
    frame = [50, 50, 950, 950]                                          # 언어와 매체 p0113 꼴
    assert drop_question_frames(_표와_5지선다(), [frame]) == []


def test_표와_번호_여섯_줄을_품은_자료_상자는_남긴다():
    frame = [50, 50, 950, 950]                                          # 생명과학 p0021 탐구 과정 · 수학 Ⅰ p0004 성질 목록 꼴
    els = [_tb([100, 60, 900, 300])] + [_el(f"{c} 과정", [100, 320 + 60 * i, 900, 360 + 60 * i]) for i, c in enumerate("①②③④⑤⑥")]
    assert drop_question_frames(els, [frame]) == [frame]


def test_맨_위가_문항_코드인_표_품은_틀은_뺀다():
    frame = [50, 50, 950, 950]                                          # 생활과 윤리 p0029 꼴
    els = [_el("[26015-0034]", [100, 60, 300, 90]),
           _el("10 다음 신문 칼럼의 입장으로 적절하지 않은 것은?", [100, 100, 900, 140]),
           _tb([100, 160, 900, 900])]
    assert drop_question_frames(els, [frame]) == []


def test_맨_위가_문항_머리가_아니면_표_품은_틀은_남긴다():
    frame = [50, 50, 950, 950]                                          # 화법과 작문 p0094 '보기' 꼴: 속 설문이 '…은?' 이어도
    els = [_el("보기\nㄱ. 통계 자료", [100, 60, 900, 100]),
           _el("ㄴ. 관광객 설문 자료\n질문 1. ○○ 관광 지구를 방문한 목적은?", [100, 110, 900, 150]),
           _tb([100, 160, 900, 900])]
    assert drop_question_frames(els, [frame]) == [frame]


def test_표_품은_틀_빼기를_끄면_남긴다(monkeypatch):
    monkeypatch.setenv("BOX_Q_FRAME_TABLE", "0")
    frame = [50, 50, 950, 950]
    assert drop_question_frames(_표와_5지선다(), [frame]) == [frame]
