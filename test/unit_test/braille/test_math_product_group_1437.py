"""분수 분자 · 분모, 지수, 아래첨자의 곱은 묶음 괄호로 묶고 함수값 하나는 안 묶는다(#1437, 원장 M-13).

기대값은 「한국 점자 규정」 수학 점자 원문 예문(braille-source/text/한국 점자 규정_재추출.txt 행 번호)의 BRF 를
그대로 점자로 바꾼 것이다. 예문이 없는 꼴은 2027 수학Ⅰ gold(dev EBS-E26-009) 실물 점형을 쪽과 함께 적는다.
종전에는 기본 BRAILLE_STYLE=book 에서 곱 판정을 껐다(구판 gold 근거). 2027 gold 는 규정대로 곱을 묶는다.
"""
import pytest

from app.ai.braille.kor_math_rules import convert_latex
from app.utils.braille_ascii import ascii_to_unicode


def _b(brf: str) -> str:
    return ascii_to_unicode(brf)


@pytest.mark.parametrize("latex,brf", [
    (r"\frac{1}{ab}", "(ab)/#a"),            # 제6항 2호 · 제7항 3호(3115 · 3160행)
    (r"\frac{1}{x+y}", "(x5y)/#a"),          # 제7항 3호(3156행)
    (r"x+\frac{1}{y}", "x5y/#a"),            # 제7항 3호(3152행) — 분모 하나만 분수
    (r"\sqrt{2}", ">#b"),                    # 제22항(3605행)
    (r"\sqrt{xy}", ">(xy)"),                 # 제22항 [붙임 2](3618행)
    (r"\sqrt[mn]{y}", "(mn)]y"),             # 제22항 [붙임 2](3620행)
    (r"x^{7+9}", "x^(#g5#i)"),               # 제18항 [붙임](3542행)
    (r"a^{3m+2n}", "a^(#cm5#bn)"),           # 제18항 [붙임](3544행)
    (r"3^{\frac{1}{4}}", "#c^(#d/#a)"),      # 제18항(3559행)
    (r"x_{\frac{1}{6}}", "x;(#f/#a)"),       # 제19항 [붙임](3577행)
    (r"x_{0.5}", "x;#j4e"),                  # 제19항 [붙임](3579행) — 소수 하나는 안 묶는다
    (r"a_{n+3}", "a;(n5#c)"),                # 제19항 [붙임](3581행)
    (r"a_{m+n}", "a;(m5n)"),                 # 제19항 [붙임](3583행)
    (r"S_{2a}", ',s;(#b"a)'),                # 제19항 [붙임](3585행) — 곱 아래첨자
    (r"\frac{\Delta y}{\Delta x}", ",.dx/,.dy"),                     # 제52항(3938행) — 증분 Δx 는 하나
    (r"\sigma(\hat{p})=\sqrt{V(\hat{p})}", ".S8p@@5033>,V8p@@50"),   # 제64항(4262행) — 근호 안 대문자 함수값
])
def test_규정_예문(latex, brf):
    assert convert_latex(latex) == _b(brf)


@pytest.mark.parametrize("latex,brf", [
    (r"\frac{2\sqrt{6}}{5}", "#e/(#b>#f)"),                       # 수 × 근호 분자 — 해설 16쪽
    (r"\frac{a}{2\sin\alpha}", "(#b6s.a)/a"),                     # 수 × 함수 분모 — 해설 33쪽
    (r"\frac{n(n+1)}{2}", "#b/(n8n5#a0)"),                        # 글자 × 괄호 = 곱 — 본문 86 · 87쪽
    (r"a_{2n}", "a;(#bn)"),                                       # 곱 아래첨자 — 해설 44 · 본문 80 · 93쪽
    (r"2^{-(-2)}", "#b^(989#b0)"),                                # 부호 + 괄호 지수 — 해설 14쪽
])
def test_곱은_묶는다_2027_gold(latex, brf):
    assert convert_latex(latex) == _b(brf)


@pytest.mark.parametrize("latex,brf", [
    (r"\frac{\sqrt{3}}{2}", "#b/>#c"),                            # 근호 하나
    (r"\frac{\sin θ}{\cos θ}", "6c.?/6s.?"),                     # 그리스 글자 인자(formula_opt 정규화 뒤 꼴) — 해설 16 · 18쪽
    (r"\frac{f(x)}{g(x)}", "g8x0/f8x0"),                          # 함수값 f(x) — 7-22 기각 사유
    (r"\frac{n(A_{4})}{n(A_{8})}", "n8,a;#h0/n8,a;#d0"),          # 원소 개수 n(A) — 해설 7쪽
    (r"\frac{2}{(2k+1)^{2}}", "8#bk5#a0^#b/#b"),                  # 괄호의 거듭제곱 — 해설 5쪽
    (r"\frac{\overline{OD}}{\sin\frac{\pi}{6}}", "6s(#f/.p)/@c,,od"),  # sin 인수만 묶음 — 해설 36쪽
    (r"\sqrt[3]{n^{\sqrt{2}-1}}", "#c]n^(>#b9#a)"),               # 근호 안 거듭제곱 하나 — 해설 3쪽
])
def test_함수값_하나는_안_묶는다_2027_gold(latex, brf):
    assert convert_latex(latex) == _b(brf)


@pytest.mark.parametrize("latex,brf", [
    (r"\frac{d x_{1}}{d t}", "dt/dx;#a"),       # 미분소 dx₁ — 제53항(3956행 dx/dy) · 제52항(3940행 x;#a)
    (r"\frac{1}{Q (x)}", ",q8x0/#a"),          # 대문자 함수값 — 제64항(4262행)과 같은 꼴
    (r"\frac{(x-1)Q(x)}{2}", "#b/(8x9#a0,q8x0)"),  # 괄호 × 함수값은 곱 — 제7항 3호(3149행)
])
def test_수학II_꼴(latex, brf):
    """수학 II(구판 묵자 162쪽) 발화를 눈으로 보다 찾은 꼴 — dev 에 없던 것이라 규칙이 dev 에 맞춰졌는지 가른다."""
    assert convert_latex(latex) == _b(brf)


@pytest.mark.parametrize("latex", [
    r"\lim_{x \longrightarrow \infty} f(x)",              # 3단계 `_LIM_RE` 가 \longrightarrow 를 못 잡는다
    r"\operatorname* { l i m } _ { x  1 - } g ( x )",     # MinerU 가 화살표를 잃은 꼴
])
def test_lim_범위는_안_묶는다(latex):
    """제51항(3908 · 3918행 `LIM;X`3o`=`F8X0`) lim 범위는 ⠰ 뒤에 묶지 않는다."""
    assert _b("(") not in convert_latex(latex)


def test_varDelta_증분은_안_묶는다():
    """제52항(3938행) 변화율 `,.dx/,.dy` 는 안 묶는다 — MinerU 가 `\\varDelta` 로 낸 꼴(수학 II 본문 88쪽)."""
    assert _b("(") not in convert_latex(r"\frac{\varDelta S}{\varDelta t}")


def test_지수가_로그_하나면_안_묶는다():
    """`2^{log₂(y/3)}` — 분수표가 진수 묶음 안에 있다(해설 5쪽 `#b^_,2(#c/y`)."""
    assert convert_latex(r"2^{\log_{2}\frac{y}{3}}").startswith(_b("#b^_,2(#c/y"))


def test_로그_밑은_곱이어도_안_묶는다():
    """로그 [붙임 1](3820행)은 밑이 분수 · 소수일 때만 묶는다."""
    assert _b("(") not in convert_latex(r"\log_{2a} x")


def test_지수_곱은_묶는다():
    """제18항 [붙임](3540행) '지수가 분수, 곱, 다항식 등일 때에는 묶음 괄호로' — 예문 a^(#cm5#bn) 의 곱 갈래."""
    assert convert_latex(r"x^{2n}") == _b("x^(#bn)")
