r"""`\text{한글}` 이 든 LaTeX 은 통째로 한 수식 구간이다.

`inline_math._ATOM` 에 한글이 없어서 `\text{득표율}` 이 `\text{` 와 `득표율}` 로 갈렸다.
그러면 수식이 조각나 닫는 중괄호와 `\%` 가 그대로 점역되고 `\times` 가 한글 약자 '연'으로
나간다 — 실측 `득표율} (\%  concc  득표수  유효 투표수  연100`.
"""
from app.ai.braille import inline_math as IM
from app.ai.braille.translator import translate_plain
from app.utils.braille_back import decode

L = r"\text{득표율} (\%) = \frac{\text{득표수}}{\text{유효 투표수}} \times 100"


def test_한글이_든_수식이_한_구간으로_잡힌다():
    w = IM.wrap(L)
    assert w.count("<!수식>") == 1 and w.count("<!/수식>") == 1


def test_곱셈이_약자로_안_샌다():
    d = decode(translate_plain(L))
    assert "×" in d and "연" not in d


def test_닫는_중괄호가_안_샌다():
    d = decode(translate_plain(L))
    assert "}" not in d and "\\" not in d


def test_한글_없는_수식의_변수가_한글로_안_샌다():
    # 종전에는 `y` 가 한글 약자 '왼'으로 나갔다(`왼=b옉`).
    d = decode(translate_plain(r"y = \frac{a}{b}"))
    assert d.startswith("y") and "왼" not in d


def test_평범한_한글_본문은_안_건드린다():
    # ⚠ 어말 마침표가 `∌`로 새는 것은 **이 변경과 무관한 기존 결함**이다(별건).
    #   여기서는 본문이 수식으로 잘못 잡히지 않는지만 본다.
    from app.ai.braille import inline_math as IM
    assert "<!수식>" not in IM.wrap("득표율을 계산해 보자.")
