"""#1055 — 한컴 분수 글꼴(EHboNA · EHboNB)의 작은 수 분수 `;분모 분자;` 를 분수로 푼다.

기대값 출처: 정답 도서 생명과학 Ⅰ 해설 p0033 gold — `확률은 ;4!;이다` 자리 ⠼⠙⠌⠼⠁(4 분의 1) ·
`;2!;` 자리 ⠼⠃⠌⠼⠁(2 분의 1) · `;4#;` 자리 ⠼⠙⠌⠼⠉(4 분의 3). 「한국 점자 규정」 수학 분수는 분모를 먼저 적는다.
"""
from __future__ import annotations

from app.ai.preprocessor import pdf_analyzer as P


def _line(*spans: tuple[str, str]) -> dict:
    """(글꼴, 글) 스팬들 → rawdict 한 줄. 글자는 10pt 간격으로 붙여 놓는다(띄어쓰기 복원이 안 끼게)."""
    out, x = [], 0.0
    for font, text in spans:
        chars = []
        for c in text:
            chars.append({"c": c, "bbox": (x, 0.0, x + 9.0, 10.0)})
            x += 10.0
        out.append({"size": 9.4, "font": font, "chars": chars})
    return {"spans": out}


def test_분모_숫자_분자_시프트기호를_분수로_푼다():
    text, font = list("확률은;4#;이다"), [False] * 3 + [True] * 4 + [False] * 2
    subs = P._fraction_subs(text, font)
    assert subs[3] == "$\\frac{3}{4}$" and all(subs[i] == "" for i in (4, 5, 6))
    assert P._fraction_subs(list(";12!@;"), [True] * 6)[0] == "$\\frac{12}{12}$"
    assert P._fraction_subs(list(";1)6;"), [True] * 5)[0] == "$\\frac{0}{16}$"     # 분모 자리 사이에 낀 분자


def test_줄_글에서_분수만_바뀌고_둘레는_그대로다():
    line = _line(("Haansoft-Batang", "확률은"), ("EHboNB-Italic", ";2!;"), ("Haansoft-Batang", "이다."))
    assert P._line_text_with_word_gaps(line) == "확률은$\\frac{1}{2}$이다."


def test_분수_글꼴이_아니거나_다른_글자가_섞이면_안_푼다():
    assert P._line_text_with_word_gaps(_line(("Haansoft-Batang", "a;2!;b"))) == "a;2!;b"     # 본문 글꼴
    assert P._fraction_subs(list(";2Ò;"), [True] * 4) == {}                                  # π 분자(Ò)는 아직 안 푼다
    assert P._fraction_subs(list(";2;"), [True] * 3) == {}                                   # 분자 없음
    assert P._fraction_subs(list(";!;"), [True] * 3) == {}                                   # 분모 없음


def test_스위치를_끄면_종전대로(monkeypatch):
    monkeypatch.setattr(P, "_FRACTION_ON", False)
    line = _line(("Haansoft-Batang", "확률은"), ("EHboNB-Italic", ";2!;"), ("Haansoft-Batang", "이다."))
    assert P._line_text_with_word_gaps(line) == "확률은;2!;이다."
