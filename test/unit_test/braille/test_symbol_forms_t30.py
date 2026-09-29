"""T30 — 기호표에 없어 조용히 사라지던 기호 중 점형이 있거나 gold 가 짚는 것(원장 R-86)."""
from app.ai.braille.translator import dropped_symbols, translate_body


def _b(text: str) -> str:
    return translate_body(text)[0][0]


def test_괄호_한글은_괄호와_낱자():
    # 생명과학 dv-001 p0032 gold `㈀+㈁>6` = ⠦⠄⠿⠁⠠⠴⠢⠦⠄⠿⠒⠠⠴⠢⠢⠼⠋
    assert "⠦⠄⠿⠁⠠⠴⠢⠦⠄⠿⠒⠠⠴⠢⠢⠼⠋" in _b("되어 ㈀+㈁>6의 조건")
    assert _b("㈎ ㈏") == _b("(가) (나)")


def test_연속_하트는_숨김표():
    # 화법과 작문 vl-005 p0201 gold `♡♡ 고등학교` = ⠸⠔⠔⠇
    assert "⠸⠔⠔⠇⠀⠈⠥⠊⠪⠶⠚⠁⠈⠬" in _b("저희는 ♡♡ 고등학교")


def test_홑_하트는_점역자_주():
    assert _b("가족사랑♡").endswith("⠠⠄⠚⠓⠪⠠⠄")      # 점역자 주표로 묶은 "하트"
    assert not dropped_symbols("가족사랑♡ ㈀ ♡♡")


def test_가리킴표는_아직_경고로_남긴다():
    assert dropped_symbols("☞ 메뉴판(클릭)") == {"☞": 1}
