"""T25 — 이름 가림 ◯◯·▲▲ 가 통째로 사라지던 것(제57항 숨김표).

Q12(2026-08-22 대표 재결재)가 ◯→○·▲→△ 를 승인했지만 #239 는 줄머리 ◯◯ 와 연속 ▲▲ 를
"근거를 못 짚었다"며 뺐다. 아래 gold 가 그 근거다. 종전에는 braillify 가 거부해 지워졌다.
"""
from app.ai.braille.translator import translate_body


def _b(text: str) -> str:
    return translate_body(text)[0][0]


def test_줄머리_이름_가림_동그라미():
    # 사회문화 dv-013 p173 gold `◯◯국의` = ⠸⠴⠴⠇⠈⠍⠁⠺
    assert _b("◯◯국의 계층은").startswith("⠸⠴⠴⠇⠈⠍⠁⠺")


def test_채운_세모_연속은_세모_숨김표():
    # 언어와 매체 dv-004 p177 gold `▲▲일보` = ⠸⠬⠬⠇⠕⠂⠘⠥
    assert _b("▲▲일보") == "⠸⠬⠬⠇⠕⠂⠘⠥"
    assert "⠸⠬⠬⠇" in _b("문장 속 ▲▲ 신문")


def test_줄머리_이름_가림_뒤_한_칸():
    # #1307 동아시아사 vl-012 p0137 gold `◯◯ 씨는` = ⠸⠴⠴⠇⠀⠠⠠⠕⠉⠵ · 제57항 예문 `김○○ 씨`
    assert _b("◯◯ 씨는 호찌민시").startswith("⠸⠴⠴⠇⠀⠠⠠⠕⠉⠵")


def test_종전_자리는_그대로():
    assert _b("▲ 배합공정").startswith("⠸⠲⠀")          # 줄머리 홑 ▲ 는 글머리(#239)
    assert "⠸⠴⠴⠇" not in _b("◯◯ 12")                 # 줄머리 ◯◯ 뒤가 한글이 아니면 그대로
    assert "⠸⠴⠴⠇" in _b("문장 속 ◯◯국")               # 문중 ◯◯ 는 종전대로
