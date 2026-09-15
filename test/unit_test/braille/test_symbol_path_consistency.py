"""같은 기호가 경로에 따라 다른 점형으로 나가지 않는지 회귀.

기호는 두 경로로 들어온다. 수식이면 `convert_latex`, 본문이면 `translate_tagged_text`
(그 안의 `substitute_symbols`)다. **같은 기호가 두 점형으로 갈리면 점역사는 같은 책에서
같은 기호를 두 모양으로 본다.**

★ 이 결함은 **채점기로 검출되지 않는다**(2026-08-15 eval 확인). 어긋나는 기호들이 지금
용례가 0에 가까워 총편집도 축도 안 움직인다. 추출을 고쳐 용례가 늘면 그제야 터진다.
그래서 단위 테스트로 잡아 둔다.

⚠ **갈리는 것이 전부 결함은 아니다.** 규정이 수식과 본문에서 다른 점형을 정한 기호가
있다. 아래 EXPECTED_SPLIT이 그 목록이고, 근거를 함께 적었다 — 다음 사람이 이 대조를
다시 할 때 무엇이 의도인지 알 수 있어야 한다.
"""
import pytest

from app.ai.braille.kor_math_rules import convert_latex
from app.ai.braille.translator import translate_tagged_text

# 수식 경로와 본문 경로가 **의도적으로** 다른 기호. (기호, 수식, 본문, 근거)
EXPECTED_SPLIT = [
    ("·", "⠐", "⠐⠆",
     "제2항 [붙임] 점곱셈은 ⠐ 한 칸. 한글 가운뎃점 ⠐⠆와 분리한다"),
    ("△", "⠸⠬", "⠸⠬⠇",
     "제40항 도형 △는 ⠸⠬. 지침의 텍스트 세모 문자 ⠸⠬⠇와 분리한다"),
    ("□", "⠸⠶", "⠸⠶⠇",
     "제40항 도형 □는 ⠸⠶. 지침의 텍스트 네모 문자 ⠸⠶⠇와 분리한다"),
]

# ★ 2026-08-22 — ∼(물결표)를 이 표에서 뺐다(원장 B-11). 종전에는 "본문은 줄표 ⠤⠤"가
#   의도된 분리였고 근거가 "정답 물결표 0회 / 줄표 2,004회"였는데, 그 실측이 **구판
#   수능특강**이다. 신규 2027 코퍼스는 정반대다 — gold 물결 dev 1,039·val 587 대
#   줄표 dev 21·val 0. 규정 문장부호표도 물결표를 ⠈⠔로 따로 싣는다.
#   이제 두 경로가 같으므로 아래 MUST_MATCH로 옮겼다.

# ★ 2026-08-27 — ∴·↔·⇔를 MUST_MATCH에 넣었다(원장 M-05). 종전에는 수식 경로가 관행형
#   ∴ ⠌⠄ · ⇔ ⠪⠒⠕를 냈고 본문 경로는 규정형이라 갈렸다. 관행 근거가 재현되지 않아
#   (kor_math_rules `_THEREFORE`·`_IFF_CELLS` 주석) 규정형으로 고정했고 이제 두 경로가 같다.

# 두 경로가 같아야 하는 기호. 하나라도 어긋나면 결함이다.
MUST_MATCH = ["∼", "≠", "≤", "≥", "±", "∞", "√", "∈", "⊂", "∠", "⊥", "∥", "→",
              "∴", "∵", "↔", "⇔"]


class TestIntentionalSplits:
    """의도된 분리는 유지되어야 한다 — 한쪽만 바꾸면 다른 쪽이 조용히 깨진다."""

    @pytest.mark.parametrize("sym,math,text,why", EXPECTED_SPLIT)
    def test_분리가_유지된다(self, sym, math, text, why):
        assert convert_latex(sym) == math, f"수식 경로가 바뀌었다 — {why}"
        assert translate_tagged_text(sym) == text, f"본문 경로가 바뀌었다 — {why}"


class TestPathConsistency:
    """나머지는 두 경로가 같은 점형이어야 한다."""

    @pytest.mark.parametrize("sym", MUST_MATCH)
    def test_두_경로가_같다(self, sym):
        m, t = convert_latex(sym), translate_tagged_text(sym)
        assert m == t, (
            f"{sym!r}가 경로에 따라 갈린다: 수식 {m!r} vs 본문 {t!r}. "
            "의도한 분리면 EXPECTED_SPLIT에 근거와 함께 옮길 것."
        )


class TestLogicArrowsAreDistinct:
    """★ 제61항 5호(↔ = [3O)와 6호(⇔ = [33O)는 **다른 점형**이다.

    ⚠ **본문 경로만 검사하면 지금도 통과한다** — symbol_table은 처음부터 갈라져 있었다.
    갈리지 않던 곳은 **수식 경로의 LaTeX 매크로**다(`\\iff`가 ↔와 같은 셀을 냈다).
    그래서 이 검사는 반드시 매크로를 태워야 한다(원장 M-05, desk D042·D043).
    """

    # (매크로, 기대 점형, 조항)
    MACROS = [
        (r"\leftrightarrow", "⠪⠒⠕", "제61항 5호 쌍조건문 [3O"),
        (r"\Leftrightarrow", "⠪⠒⠒⠕", "제61항 6호 필요충분 [33O"),
        (r"\iff", "⠪⠒⠒⠕", "제61항 6호 필요충분 [33O"),
        (r"\Longleftrightarrow", "⠪⠒⠒⠕", "제61항 6호 필요충분 [33O"),
    ]

    @pytest.mark.parametrize("macro,cells,rule", MACROS)
    def test_매크로가_조항대로_나간다(self, macro, cells, rule):
        out = convert_latex(f"p {macro} q")
        assert cells in out, f"{macro} 가 {rule}({cells})로 안 나갔다: {out!r}"

    def test_수식_안에서_두_화살표가_겹치지_않는다(self):
        bicond = convert_latex(r"p \leftrightarrow q")
        iff = convert_latex(r"p \iff q")
        assert bicond != iff, (
            f"↔와 ⇔가 수식에서 같은 셀로 나간다: {bicond!r}. "
            "제61항 5호·6호가 다른 점형을 정한다."
        )


def test_therefore_두_경로가_같다():
    """원장 M-05 — 2026-08-27 규정형(⠠⠡, 제65항 2호)으로 고정해 닫았다."""
    assert convert_latex("∴") == translate_tagged_text("∴") == "⠠⠡"


# ── #715 · 홑 기호 수식 토막의 칸수 ────────────────────────────────────────────
# 같은 기호가 묵자에 그냥 `→` 로 오면 한 칸, MinerU 가 `$\to$` 로 싸서 보내면 두 칸이
# 나갔다. 점형이 아니라 **칸수**가 경로에 따라 갈린 자리다.
# 제11항(재추출 3235~3237행)의 '수학적 표기'는 "분수·무한소수·순환소수·첨자·제곱근·
# 절댓값 등이 포함된 표현"이라 기호 하나는 해당이 없고, 그 기호들은 저마다 한 칸을
# 정한 조항이 따로 있다 — 제70항(2773행) 화살표 · 제60항 5호(4119·4122행) ∪ ∩ ·
# 제15항(3485행) 일반연산.
# ★ 이 축은 CER 이 못 본다(채점기·재점역 하네스가 빈칸 U+2800 을 지운다). 그래서 시험으로 박는다.

@pytest.mark.parametrize("bare,wrapped", [
    ("가 → 나", r"가 $\to$ 나"),
    ("가 ← 나", r"가 $\leftarrow$ 나"),
    ("가 ↔ 나", r"가 $\leftrightarrow$ 나"),
])
def test_홑_기호는_수식으로_싸여도_같게_나간다(bare, wrapped):
    """묵자 그대로 온 것과 `$…$` 로 싸여 온 것이 한 글자도 다르면 안 된다."""
    from app.ai.braille.translator import translate_body
    assert translate_body(wrapped)[0] == translate_body(bare)[0]


@pytest.mark.parametrize("wrapped,cell", [
    (r"가 $\to$ 나", "⠒⠕"),          # 제70항 화살표
    (r"A $\cup$ B 는", "⠬"),         # 제60항 5호 가 합집합
    (r"A $\cap$ B 는", "⠩"),         # 제60항 5호 나 교집합
    (r"x $\oplus$ y 는", "⠸⠢"),      # 제15항 1호 동그라미 덧셈표
])
def test_홑_기호_앞뒤는_한_칸이다(wrapped, cell):
    """앞뒤 두 칸이면 제11항을 잘못 적용한 것이다.

    ∪·∩ 는 피연산자가 로마자라 로마자표 ⠴·종료표 ⠲ 가 함께 움직인다. 그 축은 이 건과
    별개라 여기서는 **기호 양옆 칸수만** 본다.
    """
    from app.ai.braille.translator import translate_body
    out = "\n".join(translate_body(wrapped)[0])
    i = out.index(cell)
    before = len(out[:i]) - len(out[:i].rstrip("⠀"))
    after = len(out[i + len(cell):]) - len(out[i + len(cell):].lstrip("⠀"))
    assert (before, after) == (1, 1), f"앞 {before}칸 · 뒤 {after}칸: {out!r}"


def test_진짜_수식은_제11항_두_칸을_지킨다():
    """홑 기호 예외가 수식 전체로 번지면 제11항이 무너진다."""
    from app.ai.braille.translator import translate_body
    out = "\n".join(translate_body(r"$x ^ { 2 } + 1$ 은")[0])
    assert "⠀⠀" in out, f"수식 경계 두 칸이 사라졌다: {out!r}"
