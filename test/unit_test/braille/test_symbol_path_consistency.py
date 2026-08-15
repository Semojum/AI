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
    ("∼", "⠈⠔", "⠤⠤",
     "본문 물결표는 줄표로 적는다(정답 물결표 0회 / 줄표 2,004회). 수식 상사는 ⠈⠔"),
]

# 두 경로가 같아야 하는 기호. 하나라도 어긋나면 결함이다.
MUST_MATCH = ["≠", "≤", "≥", "±", "∞", "√", "∈", "⊂", "∠", "⊥", "∥", "→"]


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


@pytest.mark.xfail(reason="원장 M-05 — ∴가 수식 ⠌⠄ · 본문 ⠠⠡로 갈린다. "
                          "용례가 0에 가까워 A/B로 못 재고 채점기에도 안 잡힌다. "
                          "추출을 고쳐 용례가 늘기 전에 정리해야 한다.",
                   strict=True)
def test_therefore_아직_갈린다():
    assert convert_latex("∴") == translate_tagged_text("∴")
