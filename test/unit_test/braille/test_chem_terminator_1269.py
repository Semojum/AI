"""#1269 첨자 든 화학식 뒤 로마자 종료표 · 빈칸 — 토막이 무엇으로 끝나느냐로 가른다.

「과학 점자」 제7항(재추출본)
  1호(4434행) 원소 기호는 그 앞에 대문자 기호표를 적는다. 예(4435~4436행) `H₂O와` = `0,h;#b,o4v`
      → 원소 기호로 끝나면 종료표를 적는다.
  6호(4463~4464행) 숫자 첨자 뒤에는 「한글 점자」 제68항에 따라 로마자 종료표를 적지 않는다.
      예(4465~4466행) `O₂이다` = `0,o;#boi4` · (4467~4468행) `H₂는` = `0,h;#b`cz`
      → 숫자 첨자로 끝나면 안 적고, 숫자와 헷갈리는 한글(는 = ⠉ = 3)이 붙어 나오면 한 칸 띄운다
        (「한글 점자」 제68항 [붙임 1] 2656행 · 제44항 [다만] 2005~2006행).

★ 반례: 2027 gold 에서 첨자로 끝나는 토막 + 한글 66곳(d8c 1,746쪽)은 종료표가 없다(`O₂와` · `CO₂이다` …).
  "화학식 뒤 한글이면 ⠲" 로 넓히면 이 자리가 깨진다 — 가르는 조건은 첨자 뒤에 원소 기호가 더 붙어 끝나는가다.
"""
import pytest

from app.ai.braille.translator import translate_body
from app.utils.braille_ascii import ascii_to_unicode


def _reg(brf: str) -> str:
    """규정 BRF(백틱 = 빈칸) → 점자. 문단 첫머리 두 칸은 뺐다."""
    return ascii_to_unicode(brf, backtick="space")


def _gold(brf: str) -> str:
    """gold BRF(백틱 = ⠈) → 점자."""
    return ascii_to_unicode(brf, backtick="cell")


@pytest.mark.parametrize("src, brf", [
    # 1호 4435~4438행. 줄바꿈 자리: 1→2 는 띄어쓰기(`및 NaCl`), 2→3 은 낱말 속(`물질이|다`)이라 이어 붙인다.
    ("H₂O와 O₂ 및 NaCl은 흔하지만 중요한 물질이다.", "0,h;#b,o4v`0,o;#b`eo2`0,na,cl4z`jzj.oe3`.m7+j3`e&.o1oi4"),
    ("산소의 분자식은 O₂이다.", "l3,uw`^g.,oaz`0,o;#boi4"),               # 6호 4465~4466행
    ("H₂는 수소를 말한다.", '0,h;#b`cz`,m,u"!`e1j3i4'),                   # 6호 4467~4468행
    ("6탄당은 C₆H₁₂O₆이다.", "#f`h3i7z`0,,,c;#f\"h;#abo;#f,'4oi4"),       # 4409~4411행(구절표 뒤 종료표, 종전대로)
])
def test_규정_예문과_같다(src, brf):
    assert translate_body(src)[0][0] == _reg(brf)


def test_gold_원소_기호로_끝나면_종료표():
    # MS-REF-T26-015 ans p0044 34행 `0,h;#b,o4"u chcr3i4`
    assert translate_body("H₂O로 나타낸다.")[0][0] == _gold('0,h;#b,o4"u chcr3i4')


@pytest.mark.parametrize("src, brf", [
    ("O₂와", "0,o;#bv"),           # EBS-E26-001 ans p0007 44행
    ("CO₂이다", "0,c,o;#boi"),     # EBS-E26-001 ans p0006 158행
    ("O₂의", "0,o;#bw"),           # EBS-E26-001 ans p0008 3행
])
def test_반례_숫자_첨자로_끝나면_종료표가_없다(src, brf):
    assert translate_body(src)[0][0] == _gold(brf)


@pytest.mark.parametrize("src", ["G₁기", "Z₁로부터", "CO₂가", "O₂를", "Na₂CO₃와"])
def test_반례_숫자와_안_헷갈리는_한글은_붙인다(src):
    out = translate_body(src)[0][0]
    assert "⠲" not in out and "⠀" not in out, out


def test_숫자와_헷갈리는_한글은_띄운다():
    # gold 두 곳 모두 띄운다: EBS-E26-001 body p0033 90행 · MS-REF-T26-015 ans p0065 150행 `0,c,o;#b cz`
    assert translate_body("CO₂는")[0][0] == _gold("0,c,o;#b cz")


def test_괄호에_묶이면_종료표가_없다():
    # 제34항(재추출 1709행) — 묶인 로마자는 종료표를 안 적는다. 괄호 안 토막은 종전 경로 그대로다.
    assert "⠲" not in translate_body("물(H₂O)이")[0][0]
