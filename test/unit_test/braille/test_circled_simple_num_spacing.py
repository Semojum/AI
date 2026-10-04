"""선택지 동그라미 숫자 뒤 단순 수 수식은 한 칸 (#1083, 수학 제11항).

규정 BRF 는 「한국 점자 규정」 재추출 행 번호. 백틱은 규정 원문 관례대로 칸 띄우기다.
- 제11항(3234~3236행): 두 칸 대상인 수학적 표기에서 단순 분수와 소수를 뺀다.
- 제64항 예(2585~2586행): `① ㄱ, ㄴ  ② ㄱ, ㄷ` = `#1`=a"`=3``#2`=a"`=9` — 번호 뒤 한 칸, 선택지 사이 두 칸.
"""
import pytest

from app.ai.braille.translator import translate_tagged_text
from app.utils.braille_ascii import ascii_to_unicode


def _brf(s: str) -> str:
    return ascii_to_unicode(s, backtick="space")


@pytest.mark.parametrize("text,brf", [
    (r"① $\frac{1}{2}$ ② $\frac{3}{4}$", "#1 #b/#a  #2 #d/#c"),   # gold 001 p0141 과 같은 꼴
    (r"① $0.5$ ② $-2$", "#1 #j4e  #2 9#b"),                       # 소수 · 음수
])
def test_선택지_뒤_단순_수는_한_칸(text, brf):
    assert translate_tagged_text(text) == _brf(brf)


@pytest.mark.parametrize("text,brf", [
    (r"① $x+1$", "#1  x5#a"),            # 수식은 제11항 두 칸 그대로
    (r"① $\sqrt{2}$", "#1  >#b"),         # 제곱근은 수학적 표기라 두 칸
])
def test_수식과_수학적_표기는_두_칸_그대로(text, brf):
    assert translate_tagged_text(text) == _brf(brf)
