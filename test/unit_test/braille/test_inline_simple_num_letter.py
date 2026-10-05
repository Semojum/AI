"""글 속 단순 수 · 낱자 수식 (#1095 현장 지적 3·4).

- 「수학 점자」 제11항(재추출 3234~3236행): 두 칸 대상인 수학적 표기에서 단순 분수와 소수를 뺀다.
  단순 수는 자리를 가리지 않고 묵자 빈칸대로 한 칸, 조사는 붙는다. 선택지 사이는 두 칸(제64항 예 2585~2586행).
- 「한글 점자」 제32항 예(재추출 1653행): `다음 a, b, c의 값` = `0a1 ;b1 ;c4w`. 글 속 낱자는 로마자, 뒤 조사는 붙인다.
"""
import pytest

from app.ai.braille.translator import translate_tagged_text
from app.utils.braille_ascii import ascii_to_unicode


def test_낱자_나열은_로마자_1653():
    assert ascii_to_unicode("0a1 ;b1 ;c4w") in translate_tagged_text("다음 $a$, $b$, $c$의 값")


def test_낱자_뒤_조사는_원문_빈칸이_있어도_붙인다():
    # gold 수학 Ⅰ(EBS-E26-009) ans p0053 `k의 값이` = `⠴⠅⠲⠺⠀⠫⠃⠄⠕`
    assert translate_tagged_text("자연수 $k$ 의 값이").endswith("⠴⠅⠲⠺⠀⠫⠃⠄⠕")


def test_낱자_뒤_조사_아닌_낱말은_원문_빈칸():
    assert translate_tagged_text("$a$ 이용") == "⠴⠁⠲⠀⠕⠬⠶"


@pytest.mark.parametrize("src", ["$y=$ $x$ 의 그래프", "$\\sqrt[3]{2}$ , $b$ 이므로"])
def test_식의_일부인_낱자는_수식_그대로(src):
    assert "⠴" not in translate_tagged_text(src)


def test_글_속_단순_수_뒤_조사는_붙인다():
    # gold 수학 Ⅰ `모든 자연수 m의 값의 합은 45이다.` → `…⠚⠃⠵⠀⠼⠙⠑⠕⠊⠲`
    assert translate_tagged_text("합은 $45$이다.") == "⠚⠃⠵⠀⠼⠙⠑⠕⠊⠲"


def test_단순_분수도_두_칸_대상이_아니다_3234():
    assert translate_tagged_text("값은 $\\frac{1}{2}$이다.") == "⠫⠃⠄⠵⠀⠼⠃⠌⠼⠁⠕⠊⠲"


def test_선택지_사이는_두_칸_2585():
    # `#1`=a"`=3``#2` — 선택지 번호 뒤 한 칸, 선택지 사이 두 칸
    assert translate_tagged_text("① $3$  ② $5$  ③ $7$") == "⠼⠂⠀⠼⠉⠀⠀⠼⠆⠀⠼⠑⠀⠀⠼⠒⠀⠼⠛"
