"""T26 — 검은 렌즈괄호 【】 가 점역에서 통째로 사라지던 것(제49항 대괄호).

braillify 가 받지 않아 _safe_to_unicode 가 조용히 지웠다. 2027 gold 는 대괄호로 적는다:
화법과 작문 vl-005 p149 `【4문단 초고】` = ⠦⠆⠼⠙⠀⠑⠛⠊⠒⠀⠰⠥⠈⠥⠰⠴.
"""
from app.ai.braille.translator import translate_body


def _b(text: str) -> str:
    return translate_body(text)[0][0]


def test_렌즈괄호는_대괄호():
    assert _b("【4문단 초고】") == "⠦⠆⠼⠙⠀⠑⠛⠊⠒⠀⠰⠥⠈⠥⠰⠴"
    assert _b("【학생의 글】에").startswith("⠦⠆")


def test_리터럴_점역자주는_그대로_주표():
    assert _b("【점역자주】그림 생략【점역자주】") == _b("[점역자주]그림 생략[점역자주]")
    assert _b("【점역자주】그림 생략【점역자주】").startswith("⠠⠄")
