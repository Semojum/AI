"""음절 단위 줄바꿈 — 끊기 후보가 음절 안(음운 경계)에 서지 않는다.

「점자 도서 제작 지침」 1장 1절 1. 1) 한글은 음절 단위 줄바꿈이 원칙이다.
「한국 점자 규정」 제14항: 나·다·마·바·자·카·타·파·하 에 모음이 붙어 나오면 약자를 쓰지 않는다.
그래서 `나이` = ⠉⠣⠕ 인데, 접두 `나` 만 점역하면 약자 ⠉ 가 나와 접두 일치로 통과했고
⠉|⠣ (ㄴ과 ㅏ 사이)에 끊기 후보가 섰다. 줄머리에 온 ⠣ 는 `아` 로 읽힌다.
실물: 세계사 val p134 `대한 자‖아유롭고`, 언어 val p091 `흐름을 파‖아악하기`.
"""
import pytest

from app.ai.braille.translator import translate_with_breaks


def _cuts(text: str) -> list[tuple[str, str]]:
    lines, breaks = translate_with_breaks(text)
    b = lines[0]
    return [(b[:o], b[o:]) for o in breaks[0]]


@pytest.mark.parametrize("word", ["나이", "다음", "하얀", "파악", "자유", "마을", "바위", "나의"])
def test_약자_초성과_모음_사이에서_안_끊는다(word):
    for left, right in _cuts(word):
        assert not (left[-1] in "⠉⠊⠑⠘⠨⠋⠓⠙⠚" and right[0] == "⠣"), (word, left, right)


def test_하여는_앞_음절_경계에서만_끊는다():
    cuts = _cuts("이용하여")
    assert all(not (l.endswith("⠚") and r.startswith("⠣")) for l, r in cuts)
    assert ("⠕⠬⠶", "⠚⠣⠱") in cuts           # 이용|하여


def test_보통_음절_경계는_그대로다():
    assert ("⠉", "⠐⠣") in _cuts("나라")      # 나|라
    assert ("⠫", "⠮") in _cuts("가을")        # 가|을
    assert ("⠸⠎", "⠕") in _cuts("것이")      # 것|이


@pytest.mark.parametrize("text, mark", [("된다.", "⠲"), ("군사·정치", "⠐⠆"),
                                        ("그런가?", "⠦"), ("사과, 배", "⠐⠀")])
def test_닫는_문장부호_앞에서_안_끊는다(text, mark):
    lines, breaks = translate_with_breaks(text)
    b = lines[0]
    assert mark in b
    assert all(not b[o:].startswith(mark) for o in breaks[0]), (text, breaks[0])


def test_태그_뒤_약자도_음절_안에서_안_끊는다():
    # 세계사 val p141: `<!드러냄>지도자<!/드러냄>의` — 끊는 자리 바로 앞이 태그라 한글 판정이
    # 빠져 ⠨|⠣⠺ (ㅈ|ㅏ의) 에 후보가 섰다.
    lines, breaks = translate_with_breaks("위대한 <!드러냄>지도자<!/드러냄>의 결정")
    b = lines[0]
    assert all(not (b[o - 1] == "⠨" and b[o] == "⠣") for o in breaks[0])


def test_수식_줄은_종전대로_끊을_곳이_있다():
    # 한글 뒤에서만 막는다 — 수식 줄에서 막으면 강제분리가 늘었다(수학2 val p051).
    lines, breaks = translate_with_breaks("따라서 {f(x)g(x)}'=f'(x)g(x)+f(x)g'(x)이다.")
    assert len(breaks[0]) >= 3
