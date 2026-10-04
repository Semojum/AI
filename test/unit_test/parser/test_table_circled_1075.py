"""#1075 — 표 셀 원문자를 층 원문자로 되돌린다. MinerU 는 표를 그림으로 보고 읽어 ㉠ 을 `\\textcircled{7}` · ⑦ 로 깨뜨린다."""
from __future__ import annotations

from app.ai.parser import mineru_runner as M


def _layer(monkeypatch, text: str) -> None:
    monkeypatch.setattr(M, "_native_text_pair", lambda *_a, **_k: (text, text))


def test_원문자_자리를_읽는_차례로_층_글자로_되돌린다(monkeypatch):
    _layer(monkeypatch, "㉠(2) ㉡ ㉢/2")
    html = "<tr><td> $⑦(2)$ </td><td>$\\textcircled{7}$</td><td>$\\frac{\\textcircled{1}}{2}$</td></tr>"
    assert M._restore_table_circled(None, [0, 0, 1, 1], html) == \
        "<tr><td> ㉠(2) </td><td>㉡</td><td>$\\frac{㉢}{2}$</td></tr>"      # 명령 없는 수식 구간은 글로 푼다


def test_개수가_다르면_손대지_않는다(monkeypatch):
    """전부-아니면-전무 — 층 원문자와 셀 토큰 수가 다르면 짝이 틀렸을 수 있다."""
    _layer(monkeypatch, "㉠ ㉡ ㉢")
    html = "<tr><td>$\\textcircled{7}$</td><td>$⑫$</td></tr>"
    assert M._restore_table_circled(None, [0, 0, 1, 1], html) == html


def test_이미_맞으면_그대로(monkeypatch):
    _layer(monkeypatch, "① ②")
    html = "<tr><td>①</td><td>$②+1$</td></tr>"
    assert M._restore_table_circled(None, [0, 0, 1, 1], html) == html


def test_원문자_자리가_없으면_층을_안_읽는다(monkeypatch):
    def boom(*_a, **_k):
        raise AssertionError("층을 읽으면 안 된다")
    monkeypatch.setattr(M, "_native_text_pair", boom)
    assert M._restore_table_circled(None, [0, 0, 1, 1], "<td>가</td>") == "<td>가</td>"


def test_수식_구분자는_셀_안에서_짝지어_푼다():
    """정규식으로 풀면 앞 구간(명령 있음)이 안 맞을 때 수식 밖 글을 수식으로 잡아 `$` 를 깨뜨린다."""
    assert M._unwrap_circled_math(" $\\frac{a}{b}$ 이고 ㉠ 은 $x$ ") == " $\\frac{a}{b}$ 이고 ㉠ 은 $x$ "
    assert M._unwrap_circled_math(" $㉠(O형)$ 과 $\\alpha$") == " ㉠(O형) 과 $\\alpha$"
    assert M._unwrap_circled_math("$㉠ 홀수") == "$㉠ 홀수"


def test_읽는_차례가_어긋나_층에_없는_셀이_되면_표째_그대로(monkeypatch):
    """두 줄로 접힌 셀 때문에 층 차례가 ㉡ · ㉠ 이면 짝이 뒤바뀐다 — 층에 `㉡(O형)` 이 없으니 손대지 않는다."""
    _layer(monkeypatch, "㉡(B형) ㉠(O형)")
    html = "<tr><td>$⑦(O형)$</td><td>$⑤(B형)$</td></tr>"
    assert M._restore_table_circled(None, [0, 0, 1, 1], html) == html


def test_두_줄로_접힌_셀은_원문자와_뒤_글자로_확인한다(monkeypatch):
    """층에선 `ⓐ(응집됨)` 다음 줄에 `(응집소 α)` 가 따로 온다 — 셀 글 전체는 층에 없어도 `ⓐ(응` 은 있다."""
    _layer(monkeypatch, "ⓐ(응집됨) ⓑ(응집\n(응집소 α) 안 됨)")
    html = "<tr><td>$⑨$(응집됨)(응집소 α)</td><td>$⑩$(응집 안 됨)</td></tr>"
    assert M._restore_table_circled(None, [0, 0, 1, 1], html) == "<tr><td>ⓐ(응집됨)(응집소 α)</td><td>ⓑ(응집 안 됨)</td></tr>"
