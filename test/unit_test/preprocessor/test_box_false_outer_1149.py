"""가짜 바깥 상자(#1149 · 원장 C-158) — 곁단 바탕 사각형은 글상자가 아니다(표를 품은 문항 틀은 A/B 1차에서 빼 보고 되돌렸다)."""
from app.ai.preprocessor.pdf_analyzer import drop_sidebar_columns


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
