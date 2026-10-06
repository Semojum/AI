"""가짜 바깥 상자(#1149 · 원장 C-158) — 곁단 바탕 사각형과 표를 품은 문항 틀은 글상자가 아니다."""
from app.ai.preprocessor.pdf_analyzer import drop_question_frames, drop_sidebar_columns


def test_곁단_바탕은_빼고_본문_쪽_긴_상자는_남긴다(monkeypatch):
    monkeypatch.delenv("BOX_FALSE_OUTER", raising=False)
    left, right = [80, 100, 240, 930], [770, 100, 935, 930]       # 지면 높이 0.83 · 폭 0.16(사회 네 권 곁단)
    main_tall = [110, 80, 930, 900]                                 # 본문 쪽 긴 상자(폭 0.82, 수학 Ⅰ 꼴)
    small = [100, 100, 240, 300]                                    # 곁단 안 작은 상자(개념 체크)
    assert drop_sidebar_columns([left, right, main_tall, small], 1000.0, 1000.0) == [main_tall, small]


def test_곁단_바탕은_픽셀_좌표에서도_지면_비로_본다():
    w, h = 1190.0, 1501.0
    left = [95, 150, 285, 1395]                                     # 폭 0.16 · 높이 0.83
    assert drop_sidebar_columns([left], w, h) == []


def test_끈_스위치는_곁단_바탕을_남긴다(monkeypatch):
    monkeypatch.setenv("BOX_FALSE_OUTER", "0")
    left = [80, 100, 240, 930]
    assert drop_sidebar_columns([left], 1000.0, 1000.0) == [left]


def _el(text, bb, typ="text"):
    return {"type": typ, "content": text, "bbox": bb}


def test_표를_품은_문항_틀은_뺀다(monkeypatch):
    """생활과 윤리 body p0029 꼴: 발문과 칼럼 표를 함께 두른 틀. gold 는 발문을 상자 밖에 둔다."""
    monkeypatch.delenv("BOX_FALSE_OUTER", raising=False)
    frame = [50, 50, 950, 950]
    els = [_el("10 다음 신문 칼럼의 입장으로 적절하지 않은 것은?", [100, 100, 900, 150]),
           _el("<table><tr><td>칼럼</td></tr></table>", [100, 200, 900, 600], "table"),
           _el("① 신경 윤리학은 …", [100, 650, 900, 690])]
    assert drop_question_frames(els, [frame]) == []
    monkeypatch.setenv("BOX_FALSE_OUTER", "0")
    assert drop_question_frames(els, [frame]) == [frame]


def test_표가_없는_문항_틀은_종전대로_남긴다(monkeypatch):
    monkeypatch.delenv("BOX_FALSE_OUTER", raising=False)
    frame = [50, 50, 950, 950]                                      # 수학 Ⅰ 꼴(원장 C-157)
    els = [_el("함수 f(x)의 최댓값은?", [100, 100, 900, 300]),
           _el("① 1  ② 2  ③ 3  ④ 4  ⑤ 5", [100, 600, 900, 640])]
    assert drop_question_frames(els, [frame]) == [frame]
