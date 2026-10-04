"""제목 든 글상자 테두리 · 극한 기호 lim 역점역 (#1100).

- 「점자 자료 제작 지침」 예 2-5(_text 619~622행): 제목 든 위 테두리 `=gggg`^u@o`ggg…=`.
  gold 에는 제목 앞 채움이 3칸인 책도 있다(31줄).
- 「수학 점자」 제51항(재추출 3908~3916행): `lim x→∞ f(x)` = `LIM;X`3o`=`F8X0`.
"""
import pytest

from app.utils.braille_ascii import ascii_to_unicode
from app.utils.braille_back import decode


def _brf(s: str) -> str:
    return ascii_to_unicode(s.lower(), backtick="space")


@pytest.mark.parametrize("brf", ["=gggg`^u@o`gggggggggggggggggggg=", "=ggg`^u@o`gggggggggggggggggggg="])
def test_제목_든_위_테두리(brf):
    assert decode(_brf(brf)) == "【글상자 보기】"


def test_제목_없는_짧은_런은_테두리가_아니다():
    assert "글상자" not in decode(_brf("=ggg="))


@pytest.mark.parametrize("brf,want", [
    ("LIM;X`3o`=`F8X0", "∞"),       # 3916행
    ("LIM;X`3o`B`G8X0", "→ b"),     # 3912행
])
def test_극한(brf, want):
    out = decode(_brf(brf))
    assert out.startswith("lim") and want in out
