"""T36 ④ — #957 1종 지시자 ⠰ 가 원소 기호 나열에 붙던 것(과학 점자 제1항 ↔ 원장 C-99)."""
from app.ai.braille.translator import translate_body


def _b(text: str) -> str:
    return translate_body(text)[0][0]


def test_원소_나열에는_1종_지시자가_없다():
    # 재추출 4323행 `Li, Na, K는 알칼리 금속이다.` = `0,li1`,na1`,k4cz…`
    assert _b("Li, Na, K는 알칼리 금속이다.").startswith("⠴⠠⠇⠊⠂⠀⠠⠝⠁⠂⠀⠠⠅⠲⠉⠵")


def test_이름표_나열은_그대로():
    # 두 글자 원소가 없으면 원소 나열로 안 본다 — 2027 gold 는 ⠰ 를 적는다(C-99, 347/347)
    assert "⠴⠁⠂⠀⠰⠃⠂⠀⠰⠉⠲" in _b("다음 a, b, c에 대하여")
    assert "⠴⠠⠃⠂⠀⠰⠠⠉⠲" in _b("개체 B, C는")
    assert "⠴⠠⠊⠂⠀⠰⠠⠧⠂" in _b("시기 I, V, VI의 조건")        # 로마 숫자 나열(gold 001 ans p0031)
