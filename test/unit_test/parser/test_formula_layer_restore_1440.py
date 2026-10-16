"""줄 수식의 원문자 이름표 · 한글 낱말을 글자층으로 되살린다(#1440) — mineru_runner._restore_formula_layer.

MinerU 수식 OCR 은 `…… ㉠` 를 `⑦` · `\\tag{①}` · `\\text{己}` 로, `이므로` 를 `^{\\circ}\\text{丨旦豆}` 로 읽는다. 층에는 바른 글자가 있다.
시험 입력은 2027 수학Ⅰ 실물 LaTeX 와 그 요소 bbox 안 층 글(평문 · 한컴 글꼴 GID 를 되돌린 것)이다(V2 temp/n368/fixtures_1440.json).
기대 글자는 층(묵자 원본) 글자다.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parents[3]))

from app.ai.parser import mineru_runner as MR  # noqa: E402

BBOX = [0, 0, 1000, 1000]


@pytest.fixture
def layer(monkeypatch):
    """층 글을 (평문, GID 되돌린 글) 로 고정한다(PDF 없이)."""
    monkeypatch.delenv("FORMULA_LAYER_RESTORE", raising=False)

    def _set(plain, fixed=None):
        monkeypatch.setattr(MR, "_native_text_pair",
                            lambda page, bb, skip_math=False, italic=False: (plain, plain if fixed is None else fixed))
    return _set


@pytest.mark.parametrize("latex, plain, fixed, want", [
    # 수학Ⅰ 해설 45쪽 `β−α=γ−β=2 …… ㉠`
    (r"\beta - \alpha = \gamma - \beta = 2 \quad \dots \dots ⑦", "b-a=c-b=2  yy`㉠", "β-α=γ-β=2  …… ㉠",
     r"\beta - \alpha = \gamma - \beta = 2 \quad \dots \dots ㉠"),
    # 같은 쪽 `3β²−4=−1 …… ㉢` — \tag 는 괄호를 쳐서 나가므로 날 원문자로 바꾼다
    (r"3 \beta^ {2} - 4 = - 1 \quad \dots \tag {①}", "3bÛ`-4=-1  yy`㉢", "3β²-4=-1  …… ㉢",
     r"3 \beta^ {2} - 4 = - 1 \quad \dots ㉢"),
    # 해설 22쪽 `x=3π−3α …… ㉣` — 이름표 자리의 한 글자 \text
    (r"x = 3 \pi - 3 \alpha \quad \dots \dots \text {己}", "x=3p-3a  yy`㉣", "x=3π-3α  …… ㉣",
     r"x = 3 \pi - 3 \alpha \quad \dots \dots ㉣"),
    # 해설 45쪽 `㉠에서 r=−3이므로` — 글 첫머리 원문자
    (r"⑦ \text {에서 } r = - 3 \text {이므로}", "㉠에서 r=-3이므로", None, r"㉠ \text {에서 } r = - 3 \text {이므로}"),
])
def test_원문자_이름표를_층_원문자로(layer, latex, plain, fixed, want):
    layer(plain, fixed)
    assert MR._restore_formula_layer(None, BBOX, latex) == want


@pytest.mark.parametrize("latex, plain, fixed, want", [
    # 해설 45쪽 `a₅=81a이므로` — '이' 를 위첨자 ∘ 로, '므로' 를 한자로
    (r"a _ {3} = 9 a, a _ {5} = 8 1 a ^ {\circ} \text {丨旦豆}", "a£=9a, a°=81a이므로", "a₃=9a, a₅=81a이므로",
     r"a _ {3} = 9 a, a _ {5} = 8 1 a \text{이므로}"),
    # 본문 29쪽 `x+3>0이고 x−2>0이므로 x>2 …… ㉡` — ∘ + \text{고} = 이고 · 한자 섞인 \text{旦로} · 이름표 Ⓛ
    (r"x + 3 > 0 ^ {\circ} \text {고} x - 2 > 0 ^ {\circ} \text {旦로} x > 2 \quad \dots \dots Ⓛ",
     "x+3>0이고 x-2>0이므로 x>2  yy`㉡", "x+3>0이고 x-2>0이므로 x>2  …… ㉡",
     r"x + 3 > 0 \text{이고} x - 2 > 0 \text{이므로} x > 2 \quad \dots \dots ㉡"),
    # 해설 3쪽 `=2이므로` — '이' 를 ∘ 로 한 번 더 읽었다(층에 ∘ 없음)
    (r"\text {즉,} 1 0 ^ {\frac {1}{y}} = 2 \circ \text {이므로}", "즉, 10  y=2이므로\n1", None,
     r"\text {즉,} 1 0 ^ {\frac {1}{y}} = 2 \text{이므로}"),
    # 해설 17쪽 `또는`
    (r"\sin x = - \frac {\sqrt {k}}{2} \text {王亡} \sin x = \frac {\sqrt {k}}{2}", "sin`x=- 'k  2  또는 sin`x= 'k\n2", None,
     r"\sin x = - \frac {\sqrt {k}}{2} \text{또는} \sin x = \frac {\sqrt {k}}{2}"),
])
def test_한글_낱말을_층_낱말로(layer, latex, plain, fixed, want):
    layer(plain, fixed)
    assert MR._restore_formula_layer(None, BBOX, latex) == want


def test_층에_도_기호가_있으면_위첨자_원은_둔다(layer):
    """본문 52쪽 `∠A′CB=90°이므로` — 평문 층은 ° 를 ± 로 보이고, GID 를 되돌린 층에 ° 가 있다."""
    latex = r"\angle \mathrm{A} ^ {\prime} \mathrm{CB} = 9 0 ^ {\circ} \text {이므로}"
    layer('∠"\x08$#=90±이므로', "∠A'CB=90°이므로")
    assert MR._restore_formula_layer(None, BBOX, latex) == latex


def test_개수가_안_맞으면_그대로(layer):
    """층 원문자 둘에 이름표 자리 하나 — 짝을 못 지으면 손대지 않는다(표 원문자와 같은 원칙)."""
    latex = r"x = 1 \quad \dots \dots ⑦"
    layer("x=1  yy`㉠ ㉡에서")
    assert MR._restore_formula_layer(None, BBOX, latex) == latex


def test_층_낱말이_남으면_그대로(layer):
    """층에 한글 낱말이 더 있으면(다른 요소 글이 bbox 에 걸림) 한글 자리를 안 바꾼다."""
    latex = r"x = 1 \text {王亡} x = 2"
    layer("따라서 x=1 또는 x=2")
    assert MR._restore_formula_layer(None, BBOX, latex) == latex


def test_스위치로_끈다(layer, monkeypatch):
    layer("b-a=c-b=2  yy`㉠")
    monkeypatch.setenv("FORMULA_LAYER_RESTORE", "0")
    latex = r"\beta - \alpha = 2 \quad \dots \dots ⑦"
    assert MR._restore_formula_layer(None, BBOX, latex) == latex


def test_되살린_원문자가_점자로_찍힌다():
    """「한국 점자 규정」 ㉠ = `7=a7`(재추출 2573~2574행) — 되살린 글자가 점역기를 지나 그 점형이 되는지 본다."""
    from app.ai.braille.kor_math_rules import convert_latex
    from app.utils.braille_ascii import ascii_to_unicode
    assert convert_latex(r"x = 1 \quad \dots \dots ㉠").endswith(ascii_to_unicode("7=a7"))


def test_이름표_자리_밖의_한_글자_text_는_원문자로_안_센다(layer):
    """`\\text{,}` 같은 한 글자 글은 줄임표 뒤가 아니면 원문자 자리가 아니다 — 세면 개수가 어긋나 이름표를 못 고친다."""
    layer("x=1, y=2  yy`㉠")
    assert (MR._restore_formula_layer(None, BBOX, r"x = 1 \text {,} y = 2 \quad \dots \dots ⑦")
            == r"x = 1 \text {,} y = 2 \quad \dots \dots ㉠")


def test_원문자_자리는_한글_자리로_안_센다(layer):
    """원문자 짝이 안 맞아 `\\textcircled{\\text{七}}` 가 남아도, 그 속 한자를 한글 낱말 자리로 세지 않는다."""
    layer("x=1 또는 x=2  yy`㉢ ㉣")
    assert (MR._restore_formula_layer(None, BBOX, r"x = 1 \text {王亡} x = 2 \quad \dots \dots \textcircled {\text {七}}")
            == r"x = 1 \text{또는} x = 2 \quad \dots \dots \textcircled {\text {七}}")


def test_표_칸_한글_치환은_한글끼리만():
    """#1440 첫 판이 새 정규식을 표 칸 판정과 같은 이름(`_HANGUL_RUN_RE`, 통째 한글)으로 지어 덮었다. 생활과 윤리 본문 26쪽
    표의 `진리의 길이다.` 가 층 창 `스승님,` 으로 바뀌었다 — 문장부호가 낀 자리는 한글끼리 치환이 아니다."""
    assert MR._hangul_substitutions("거룩한 진리의 길이다.", "거룩한 진리의 스승님,") == []


def test_괄호_숫자는_원문자로_안_센다(layer):
    """본문 29쪽 `⑴ a^f(x) < a^g(x) ⟺ f(x) < g(x)` — 층의 ⑴(U+2474)을 원문자로 세어 `\\tag{1}` 을 ⑴ 로 바꾸면,
    번역기가 ⑴ 의 점형을 안 내 `(1)` 이 사라진다. 괄호 · 마침표 꼴은 원문자가 아니다."""
    latex = r"a ^ {f (x)} <   a ^ {g (x)} \Longleftrightarrow f (x) <   g (x) \tag {1}"
    layer("⑴ a  f(x)<a  g(x) HjK f(x)<g(x)")
    assert MR._restore_formula_layer(None, BBOX, latex) == latex


def test_써넣는_원문자는_번역기가_찍는_글자만():
    """층에서 가져와 써넣는 원문자 집합 전체를 수식 이름표 자리에 넣어 번역기에 통과시킨다 — 빈 출력이 하나라도 있으면
    되살린 자리가 사라진다(⑴ · Ⓐ · ㉼ 이 그랬다). #1435 자모 전수와 같은 방식(pm 17:0x)."""
    from app.ai.braille.kor_math_rules import convert_latex
    base = convert_latex(r"x = 1 \quad \dots \dots")
    chars = [chr(c) for c in range(0x2400, 0x3300) if MR._FORMULA_CIRCLED_RE.fullmatch(chr(c))]
    assert len(chars) == 74
    empty = [ch for ch in chars if not convert_latex(rf"x = 1 \quad \dots \dots {ch}")[len(base):].strip("⠀ ")]
    assert empty == []


def test_한자_자리의_문장부호는_남긴다(layer):
    """수학 II 해설 32쪽 `즉, 3/2 …` 를 MinerU 가 `\\text {卍,}` 로 읽었다 — 한자 덩이만 층 낱말로 바꾸고 쉼표는 둔다."""
    layer("즉, 3  2")
    assert MR._restore_formula_layer(None, BBOX, r"\text {卍,} \frac {3}{2}") == r"\text{즉,} \frac {3}{2}"
