"""드러냄표·밑줄(제56항)과 표의 빈칸(제73항) 역점역.

· 드러냄표·밑줄 → `,-` … `-'` (⠠⠤ … ⠤⠄) — 굵은 글자체표와 같은 갈래다.
· 표의 빈칸     → `==` (⠿⠿)

역맵에 없어 `옳지 -않은-' 것은?`(수능 부정 문항)과 `V  V  옹옹`(5×4 표)이 나갔다.
"""
import pytest

from app.ai.braille.translator import translate_plain
from app.utils.braille_back import decode


def test_드러냄표를_벗긴다():
    assert decode("⠨⠹⠨⠞⠚⠨⠕⠀⠠⠤⠣⠒⠴⠵⠤⠄⠀⠸⠎⠵⠦") == "적절하지 않은 것은?"


def test_드러냄표가_줄을_넘어도_벗긴다():
    """짝 10,705건 중 3,234건이 줄바꿈을 낀다 — 줄을 쪼개기 전에 벗겨야 한다."""
    got = decode("⠠⠤⠫⠈⠌\n⠊⠥⠤⠄⠐⠮")
    assert got == "가계\n도를"
    assert "-" not in got


def test_표를_벗겨도_뒤_셀이_앞_음절로_안_먹힌다():
    """표는 토큰 경계이기도 하다 — 그냥 지우면 `아시아(세계` 가 `아시앝'세계` 로 깨진다."""
    raw = "⠀⠀⠼⠁⠲⠀⠠⠤⠣⠠⠕⠣⠤⠄⠦⠄⠠⠝⠈⠌⠝⠠⠎⠀⠫⠨⠶⠀⠋⠵"
    assert decode(raw) == "  1. 아시아(세계에서 가장 큰"


def test_짝_없는_드러냄표는_안_건드린다():
    """⠠⠤ 는 「수학 점자」 제23항 2호 밑줄·UEB 줄표로도 쓰인다 — 닫는 표가 없다."""
    assert decode("⠠⠭⠠⠤") == "속-"


@pytest.mark.parametrize("text", ["고복지-저부담", "(가)와 (나)", "밑줄-강조"])
def test_붙임표_비회귀(text):
    assert decode(translate_plain(text)) == text


def test_표의_빈칸은_아무것도_안_낸다():
    """묵자 쪽은 그냥 빈 칸이다(네모 빈칸 ▯ 와 다르다)."""
    assert decode("⠚⠗⠶⠚⠂⠀⠠⠍⠀⠕⠌⠊⠲⠀⠀⠴⠠⠧⠲⠀⠀⠿⠿").rstrip() == "행할 수 있다.  V"


def test_약자_옹은_안_깨진다():
    """⠿ 는 약자 '옹'이자 온표다 — 양옆이 경계인 ⠿⠿ 만 빈칸으로 본다."""
    assert decode("⠿⠣⠂⠕") == "옹알이"
    assert decode("⠿⠁⠲") == "ㄱ."          # 제9항 온표 + 자음 낱자
