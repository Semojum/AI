"""고급 추출 — 이름표(㉠)를 동그라미 기호로 적은 자리를 되물어 고치는가."""
from app.ai.parser import opus_fallback as OF


def _els(*contents):
    return [{"type": "formula" if c.startswith("\\") else "text", "content": c}
            for c in contents]


def test_어긋난_쪽을_잡는다():
    assert OF.self_contradicts(_els("㉠에 의하여", r"\int f(x)dx=3 \cdots \bigcirc"))


def test_이름표만_있으면_안_잡는다():
    assert not OF.self_contradicts(_els("㉠에 의하여", r"\int f(x)dx=3 \cdots ㉠"))


def test_이름표가_없으면_안_잡는다():
    # 동그라미가 정말 도형인 쪽은 건드리지 않는다.
    assert not OF.self_contradicts(_els("원의 넓이", r"A \bigcirc B"))


def _fake(monkeypatch, answer, raw="[]"):
    """되묻기 응답을 갈아 끼운다. answer=None 이면 JSON 파싱이 죽은 판을 흉내 낸다."""
    if answer is None:
        monkeypatch.setattr(OF, "_parse", lambda txt: (_ for _ in ()).throw(ValueError("x")))
    else:
        monkeypatch.setattr(OF, "_parse", lambda txt: answer)

    class _R:
        content = [type("B", (), {"type": "text", "text": raw})()]
        usage = None

    class _C:
        def __init__(self, **kw):
            self.messages = type("M", (), {"create": lambda *a, **k: _R()})()

    monkeypatch.setattr("anthropic.Anthropic", _C)
    monkeypatch.setattr(OF.base64, "b64encode", lambda b: b"x")
    monkeypatch.setattr(OF, "open", lambda *a, **k: __import__("io").BytesIO(b"x"), raising=False)


def test_자리마다_다른_이름표를_갈아_끼운다(monkeypatch):
    els = _els("㉠에 의하여", r"a=3 \cdots \bigcirc", r"b=4 \cdots \bigcirc", r"c \cdots ○")
    _fake(monkeypatch, ["㉠", "㉡", "㉢"])
    assert OF.relabel_circles(els, "p.jpg") == 3
    assert els[1]["content"] == r"a=3 \cdots ㉠"
    assert els[2]["content"] == r"b=4 \cdots ㉡"
    assert els[3]["content"] == r"c \cdots ㉢"


def test_한_요소에_두_자리여도_뒤부터_갈아_끼운다(monkeypatch):
    els = _els("㉠에 의하여", r"\bigcirc 와 \bigcirc 를 더하면")
    _fake(monkeypatch, ["㉠", "㉡"])
    assert OF.relabel_circles(els, "p.jpg") == 2
    assert els[1]["content"] == r"㉠ 와 ㉡ 를 더하면"


def test_빈_답은_진짜_도형이라_안_건드린다(monkeypatch):
    els = _els("㉠에 의하여", r"A \bigcirc B")
    _fake(monkeypatch, [""])
    assert OF.relabel_circles(els, "p.jpg") == 0
    assert els[1]["content"] == r"A \bigcirc B"


def test_개수가_안_맞으면_통째로_안_건드린다(monkeypatch):
    els = _els("㉠에 의하여", r"a \cdots \bigcirc", r"b \cdots \bigcirc")
    _fake(monkeypatch, ["㉠"])
    assert OF.relabel_circles(els, "p.jpg") == 0
    assert els[1]["content"] == r"a \cdots \bigcirc"


def test_되묻기가_죽어도_원본이_남는다(monkeypatch):
    els = _els("㉠에 의하여", r"a \cdots \bigcirc")
    monkeypatch.setattr("anthropic.Anthropic", lambda **kw: (_ for _ in ()).throw(RuntimeError("x")))
    assert OF.relabel_circles(els, "p.jpg") == 0
    assert els[1]["content"] == r"a \cdots \bigcirc"


def test_스위치를_끄면_안_부른다(monkeypatch):
    monkeypatch.setattr(OF, "_RELABEL", False)
    els = _els("㉠에 의하여", r"a \cdots \bigcirc")
    assert OF.relabel_circles(els, "p.jpg") == 0


def test_줄바꿈_없는_펜스도_읽는다():
    # ```["㉠"]``` 처럼 한 줄로 오는 답. 종전에는 IndexError 로 통째로 버렸다.
    assert OF._parse('```["㉠", "㉡"]```') == ["㉠", "㉡"]
    assert OF._parse('```json\n["㉠"]\n```') == ["㉠"]
    assert OF._parse('[{"type": "text"}]') == [{"type": "text"}]


def test_JSON_이_아니어도_이름표_개수가_맞으면_쓴다(monkeypatch):
    # 배열이 잘리거나 산문으로 오는 판이 있다. 글자만 훑어 개수가 맞으면 쓴다.
    els = _els("㉠에 의하여", r"a \cdots \bigcirc", r"b \cdots \bigcirc")
    _fake(monkeypatch, None, raw="1번은 ㉠ 이고 2번은 ㉡ 입니다")
    assert OF.relabel_circles(els, "p.jpg") == 2
    assert els[1]["content"] == r"a \cdots ㉠"
    assert els[2]["content"] == r"b \cdots ㉡"


def test_훑은_개수가_어긋나면_안_건드린다(monkeypatch):
    els = _els("㉠에 의하여", r"a \cdots \bigcirc", r"b \cdots \bigcirc")
    _fake(monkeypatch, None, raw="㉠ 하나만 읽힙니다")
    assert OF.relabel_circles(els, "p.jpg") == 0
    assert els[1]["content"] == r"a \cdots \bigcirc"
