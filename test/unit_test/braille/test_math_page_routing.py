"""수식 지면의 평문 식(`p-q` · `(x, y)`)을 수식으로 보낸다 — T16 · 원장 R-85.

같은 꼴이 과목에 따라 gold 가 반대라(수학 009 `p-q의 값` = `  p9q  w` 수식 · 사회 013 `t+10년` = 글 ·
생명 001 `(Q, n)` = 글) 피연산자 모양이 아니라 **수식 지면 신호**(한컴 수식 글꼴 비율)로 켠다.
기대값은 2027 gold 원문에서 옮겼다(생산 코드로 만들지 않음).
"""
from __future__ import annotations

import asyncio

import pytest

from app.ai.braille import inline_math
from app.ai.braille.translator import translate_body


def _body(text: str) -> str:
    return "".join(translate_body(text)[0])


@pytest.fixture
def math_page():
    tok = inline_math.MATH_PAGE.set(True)
    yield
    inline_math.MATH_PAGE.reset(tok)


def test_수식_지면_뺄셈식은_수식(math_page) -> None:
    # 009 body p0018 gold `,ir"  p9q  w` — 제11항 두 칸 · 뺄셈 ⠔
    assert "⠐⠀⠀⠏⠔⠟⠀⠀⠺" in _body("할 때, p-q의 값은?")


@pytest.mark.parametrize("src", ["점 (4, 3)을 지나므로", "점 (1,0)을 지난다", "점 (8, -1)에서"])
def test_수식_지면_수_순서쌍도_수식(math_page, src: str) -> None:
    # 009 gold 수 순서쌍은 수식 꼴(`8#a" #j0` = ⠦⠼⠁⠐⠀⠼⠚⠴) 50 · 글 꼴(⠦⠄…⠂…⠠⠴) 0
    out = _body(src)
    assert "⠦⠄" not in out and "⠠⠴" not in out


def test_수식_지면_순서쌍은_수식(math_page) -> None:
    # 009 body p0038 gold `,p8x" y0` — 수식 괄호 ⠦…⠴ · 수식 쉼표 ⠐ · 로마자표·1종 지시자 없음
    assert "⠀⠀⠦⠭⠐⠀⠽⠴⠀⠀" in _body("점 (x, y)에서")


@pytest.mark.parametrize("src,want", [
    ("m, n은 자연수", "⠴⠍⠂⠀⠰⠝"),     # 쉼표 나열은 수식 지면에서도 글 — 009 body p0006 gold
    ("3-4쪽", "⠼⠉⠤⠼⠙"),              # 로마자 없는 수 범위는 안 건드린다
])
def test_수식_지면에서도_글로_두는_자리(math_page, src: str, want: str) -> None:
    assert want in _body(src)


@pytest.mark.parametrize("src,want", [
    ("t+10년과 t년", "⠴⠞⠲⠢⠼⠁⠚"),     # 013 사회 — 글(gold `0t4 5 #aj`)
    ("p-q의 값은?", "⠴⠏⠤⠰⠟⠲"),       # 신호가 없으면 종전 그대로
])
def test_수식_지면이_아니면_종전대로(src: str, want: str) -> None:
    assert want in _body(src)


def test_점역_풀_스레드에도_쪽_문맥이_간다(math_page) -> None:
    # run_in_executor 는 contextvars 를 안 넘긴다 — run_braille 가 복사해 넘기는지(T16 함정).
    from app.core.limits import run_braille

    async def go() -> bool:
        return await run_braille(inline_math.MATH_PAGE.get)

    assert asyncio.run(go()) is True
