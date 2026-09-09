"""고급 점역 crop 모드 — 깨진 요소만 잘라 배치로 되묻는가. 실측 근거는 `crop_reask` 도크스트링."""
import json

import numpy as np
import pytest

from app.ai.parser import crop_reask as C


# ── 신호: 켜진 자리가 실제로 깨진 것이어야 한다(전수 정밀 실측의 실물 꼴) ──────────
@pytest.mark.parametrize("content, sig", [
    ("$\\lim h(t) = 2^{\\circ}$ 且 $\\lim = 1$", "hanja"),          # p1#4 且
    ("⑦에 의하여 2≤f(3)≤f(5)≤5이고", "circ7+"),                     # p4#7 ㉠→⑦
    ("Ⓥ \\text {에 의하여 } f(1)+f(3)", "circLet"),                   # p4#8 ㉣→Ⓥ
    ("조건 (나)에 의하여 … ⊙", "oddglyph"),                             # p3#56
    ("g(x) = a ^ {\\circ} \\text {이고,}", "circ-sup"),                # p3#25
    ("\\circ \\text {이므로} \\tan(\\angle AB_1H_1)", "circ-bare"),    # p5#29
    ("①에 의하여 $f(2)=5$ 의 1가지이다.", "circ1-5+josa"),             # p4#14 ㉢→①
    ("정수인 것을 알 수 있다. ④", "circ1-5-end"),                      # p6#56 배지 개념→④
    ("기준으로 경우를 나DMIN 가능한 값", "latin-glue"),                  # p4#40
    ("꺼낸 1개의 공이 힜 공일 때", "ksx-rare"),                          # p2#0 흰→힜
    ("실수 k의 최, $f'(\\sqrt{2})$ 이므로", "trunc-comma"),              # p1#36 최솟값→최,
    ("P(0 \\leq Y \\leq 5a) = p - q\\sqrt{2} \\text {일}", "text-tail-1syl"),  # p3#13
    ("\\frac {4C_{3}}{4C_{3}=4C_{1}=4}", "frac-den"),                  # p1#68 주석이 분모로
    ("\\int f dx \\xrightarrow [x=1 \\text{일 때}]{\\text{치환}}", "arrow/underset"),  # p6#39
])
def test_깨진_실물마다_신호가_켜진다(content, sig):
    assert sig in C.broken_signals(content)


@pytest.mark.parametrize("content", [
    "즉, 카드 값, 때, 다음과 같다.",                          # 낱 음절+쉼표라도 낱말이면 잘림이 아니다
    "① 3  ② 4  ③ 5  ④ 6  ⑤ 7",                              # 선택지 번호
    "$f(x) = \\frac{1}{2}x^{2}$ 이므로 $x$축과 만난다.",       # 멀쩡한 본문 수식
    "\\frac {\\overline{AH_1}}{\\overline{B_1H_1}} = 4",       # 분모가 멀쩡한 분수
    "확률변수 X의 확률밀도함수 f(x)의 그래프는 그림과 같다.",
])
def test_멀쩡한_요소에는_안_켜진다(content):
    assert C.broken_signals(content) == []


# ── 표적: 요소에 붙은 빈 구역은 그 요소 상자에 합친다 ───────────────────────────
def _el(content, bbox, typ="text"):
    return {"type": typ, "content": content, "bbox": bbox}


def test_바로_아래_빈_구역은_요소_크롭에_합친다():
    # MinerU 가 네 줄을 한 요소로 뭉치고 bbox 는 첫 줄만 잡은 꼴(p1#23 실측)
    els = [_el("따라서 함수가 극숫값을 가지고 且", [80, 400, 330, 412])]
    t = C.crop_targets(els, [[76, 414, 330, 426], [75, 428, 313, 440]])
    assert t == [(0, [75, 400, 330, 440])]          # 사슬로 두 줄 다 붙는다


def test_안_붙은_빈_구역은_따로_남고_가장자리_탭은_버린다():
    els = [_el("멀쩡한 줄", [80, 100, 330, 112])]
    t = C.crop_targets(els, [[500, 600, 800, 612], [933, 385, 1000, 406]])
    assert t == [(None, [500, 600, 800, 612])]


def test_그림_요소는_안_자른다():
    els = [_el("且 그림", [0, 0, 500, 500], typ="image")]
    assert C.crop_targets(els, []) == []


# ── 갈아 끼우기 관문 ─────────────────────────────────────────────────────────
def test_원문자를_지키는_정규화():
    """`\\W` 가 ㉠ 은 지우고 ⑦ 은 남겨 길이 관문이 어긋나던 자리(p6#4 실측)."""
    assert len(C._norm("㉠, ㉡에 의해")) == len(C._norm("⑦, ⑨에 의해"))


def test_수식_유형에_맞춘다():
    assert C._fit_math("$a=b$", "formula") == "a=b"
    assert C._fit_math("\\frac{1}{2}=x", "text") == "$\\frac{1}{2}=x$"
    assert C._fit_math("값은 $a$이다.", "text") == "값은 $a$이다."


def test_점선_리더를_걷는다():
    assert C._clean("정답 ① *독립시행의 확률 ⋯⋯⋯⋯ [정답률 42%]") == "정답 ① *독립시행의 확률 [정답률 42%]"
    assert C._clean("23 정답 ③ ------------ [정답률 92%]") == "23 정답 ③ [정답률 92%]"


def test_이웃이_가진_줄은_걷고_나머지를_갈아_끼운다():
    els = [_el("(iv) f(1)=4, f(7)=7인 경우", [0, 0, 9, 9]),
           _el("i) f(3), f(5)를 결정하는 경우의 수\n⑦에 의하여 4≤f(3)≤f(5)≤7이고", [0, 10, 9, 19])]
    n = C._apply(els, [(1, [0, 10, 9, 19])],
                 ["(iv) f(1)=4, f(7)=7인 경우\ni) f(3), f(5)를 결정하는 경우의 수\n㉠에 의하여 4≤f(3)≤f(5)≤7이고"])
    assert n == 1
    assert els[1]["content"] == "i) f(3), f(5)를 결정하는 경우의 수\n㉠에 의하여 4≤f(3)≤f(5)≤7이고"
    assert els[0]["content"].startswith("(iv)")


def test_글자가_너무_줄면_손대지_않는다():
    els = [_el("가나다라마바사아자차카타파하 且 거너더러머버서", [0, 0, 9, 9])]
    assert C._apply(els, [(0, [0, 0, 9, 9])], ["가나다"]) == 0
    assert "且" in els[0]["content"]


def test_빈_구역은_새_요소로_세우되_이웃이_가진_말이면_안_세운다():
    els = [_el("앞 줄", [100, 100, 400, 112]), _el("뒷 줄", [100, 140, 400, 152])]
    n = C._apply(els, [(None, [100, 114, 400, 126]), (None, [100, 128, 400, 138])],
                 ["3의 배수가 되어야 하므로", "뒷 줄"])
    assert n == 1 and len(els) == 3
    assert els[1]["content"] == "3의 배수가 되어야 하므로" and els[1]["flags"] == ["ADVANCED_RECOVERED"]
    assert [e.get("reading_order") for e in els] == [0, 1, 2]


# ── 되묻기 한 바퀴(가짜 클라이언트) ─────────────────────────────────────────
def _page(tmp_path):
    import cv2
    img = np.full((300, 400, 3), 255, np.uint8)
    cv2.putText(img, "ABC", (40, 60), cv2.FONT_HERSHEY_SIMPLEX, 1.2, (0, 0, 0), 2)
    p = tmp_path / "p.jpg"
    cv2.imwrite(str(p), img)
    return str(p)


def _fake(monkeypatch, answer):
    class _R:
        content = [type("B", (), {"type": "text", "text": json.dumps(answer, ensure_ascii=False)})()]
        usage = None

    class _C:
        def __init__(self, **kw):
            self.messages = type("M", (), {"create": lambda *a, **k: _R()})()
    monkeypatch.setattr("anthropic.Anthropic", _C)
    monkeypatch.setenv("ADVANCED_EXTRACT_RELABEL", "0")


def test_깨진_요소만_묻고_그_글자만_바꾼다(tmp_path, monkeypatch):
    els = [_el("멀쩡한 줄", [100, 100, 900, 130]),
           _el("$= 2^{\\circ}$ 且 $x=1$", [100, 150, 900, 180]),
           _el("확률 X", [100, 200, 900, 230], typ="formula")]
    _fake(monkeypatch, ["$=2$이므로 $x=1$"])
    assert C.reask_crops(els, _page(tmp_path)) == 1
    assert els[1]["content"] == "$=2$이므로 $x=1$"
    assert els[0]["content"] == "멀쩡한 줄" and els[2]["content"] == "확률 X"
    assert els[1]["bbox"] == [100, 150, 900, 180]          # 좌표는 MinerU 것


def test_되물을_것이_없으면_안_부른다(tmp_path, monkeypatch):
    monkeypatch.setattr("anthropic.Anthropic", lambda **kw: (_ for _ in ()).throw(AssertionError("불렀다")))
    monkeypatch.setattr(C, "_page_gaps_for_test", None, raising=False)
    monkeypatch.setattr("app.core.pipeline._page_gaps", lambda *a: [])
    assert C.reask_crops([_el("멀쩡한 줄", [100, 100, 900, 130])], _page(tmp_path)) == 0


def test_개수가_안_맞으면_통째로_안_건드린다(tmp_path, monkeypatch):
    els = [_el("⑦에 의하여", [100, 100, 900, 130]), _el("⑧에 의하여", [100, 150, 900, 180])]
    _fake(monkeypatch, ["㉠에 의하여"])
    monkeypatch.setattr("app.core.pipeline._page_gaps", lambda *a: [])
    assert C.reask_crops(els, _page(tmp_path)) is None
    assert els[0]["content"] == "⑦에 의하여"


def test_되묻기가_죽으면_None_을_돌려_호출부가_알린다(tmp_path, monkeypatch):
    monkeypatch.setattr("anthropic.Anthropic", lambda **kw: (_ for _ in ()).throw(RuntimeError("x")))
    monkeypatch.setattr("app.core.pipeline._page_gaps", lambda *a: [])
    els = [_el("⑦에 의하여", [100, 100, 900, 130])]
    assert C.reask_crops(els, _page(tmp_path)) is None
