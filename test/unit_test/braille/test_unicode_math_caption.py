"""QA 10번 — 캡션이 유니코드로 쓴 수식이 LaTeX과 같은 점형으로 나가는지.

대표님 QA 실측(job_260807155800 p002): 캡션이 `곡선: y = x² + 3`이라 적어 왔다.
수식 OCR 경로는 `$y=x^{2}+3$`를 낸다 — 같은 식인데 표기가 두 갈래다.

두 가지를 지킨다.
  (1) C5 — 유니코드 첨자 안의 숫자도 수표(⠼)를 달아야 한다. **규칙으로** 달아야 한다:
      종전에는 규칙이 아니라 마지막 안전망(kor_math_rules._w2c_sweep_residue)이
      braillify에게 `²`를 통째로 넘겨 우연히 맞혔다. 그 훅은 braillify가 없으면
      None이라 그대로 통과하고(`x²` → `⠭²`), 그러면 숫자 2가 사라져 C5가 된다.
  (2) 유니코드형과 LaTeX형의 점형이 같아야 한다 — 다르면 같은 쪽 안에서 같은 식이
      두 모양으로 나가 점역사가 둘 다 고쳐야 한다.
"""
from __future__ import annotations

import re

import pytest

from app.ai.braille.kor_math_rules import convert_latex, unicode_scripts_to_latex
from app.ai.braille.translator import translate_with_breaks

_NON_BRAILLE = re.compile(r"[^⠀-⣿\n ]")


def _braille(text: str) -> str:
    return "\n".join(translate_with_breaks(text)[0])


class TestC5첨자수표:
    """유니코드 첨자 안의 숫자도 수표(⠼)를 달고 나온다 — C5 배포 블로커."""

    @pytest.mark.parametrize("latex_uni,expect", [
        ("x²", "⠭⠘⠼⠃"),          # 제18항 위첨자표 ⠘ + 수표 ⠼ + 2
        ("x₁", "⠭⠰⠼⠁"),          # 제19항 아래첨자표 ⠰
        ("10⁴", "⠼⠁⠚⠘⠼⠙"),
    ])
    def test_첨자_숫자에_수표가_붙는다(self, latex_uni: str, expect: str) -> None:
        got = convert_latex(latex_uni)
        assert got == expect, got
        assert "⠼" in got, f"C5: 수표 누락 {got}"

    @pytest.mark.parametrize("src", ["x²", "Ca²⁺", "aₙ₊₁", "3²+4²=5²", "y = x² + 3"])
    def test_점자에_원문자가_남지_않는다(self, src: str) -> None:
        got = convert_latex(src)
        assert not _NON_BRAILLE.search(got), f"비점자 잔류: {got!r}"


class TestUnicode대LaTeX동치:
    """캡션 표기(유니코드)와 OCR 표기(LaTeX)가 같은 점형으로 수렴한다."""

    @pytest.mark.parametrize("uni,tex", [
        ("y = x² + 3", "y=x^{2}+3"),          # ★ 대표님 QA 실물
        ("a² + b² = c²", "a^{2}+b^{2}=c^{2}"),
        ("Ca²⁺", "Ca^{2+}"),
        ("y = 2ˣ", "y=2^{x}"),
        ("aₙ₊₁", "a_{n+1}"),
        ("f′(x)", "f'(x)"),
        ("H₂O", "H_{2}O"),
        ("cm³", "cm^{3}"),
    ])
    def test_같은_점형(self, uni: str, tex: str) -> None:
        # 캡션 한 줄 꼴로 감싼다 — 문항번호 규칙(_QNUM_RE)에 걸리지 않게 라벨을 붙인다.
        got_uni = _braille(f"식: {uni}")
        got_tex = _braille(f"식: ${tex}$")
        assert got_uni == got_tex, f"\n유니코드 {got_uni}\nLaTeX    {got_tex}"


class TestNormalizer:
    def test_멱등(self) -> None:
        once = unicode_scripts_to_latex("Ca²⁺와 aₙ₊₁")
        assert once == "Ca^{2+}와 a_{n+1}"
        assert unicode_scripts_to_latex(once) == once

    def test_연속_첨자는_한_덩이(self) -> None:
        """`²⁺`가 `^{2}^{+}`로 쪼개지면 제18항 첨자 묶음이 깨진다."""
        assert unicode_scripts_to_latex("Ca²⁺") == "Ca^{2+}"


class TestOverdetect방지:
    """수식이 아닌 것을 수식으로 삼키지 않는다 — 삼키면 문장이 통째로 깨진다."""

    def test_화살표는_수식이_아니다(self) -> None:
        """캡셔닝 프롬프트가 흐름을 →로 적으라 지시한다(지침 6.1.4(6))."""
        from app.ai.braille import inline_math
        src = "Client → WebBrowser: 요청"
        assert "<!수식>" not in inline_math.wrap(src)

    def test_숨김표_삼각형은_수식이_아니다(self) -> None:
        """△△도서관 = 제57항 숨김표. 수식 삼각형으로 보면 래퍼가 깨진다."""
        got = _braille("△△도서관")
        assert got.startswith("⠸⠬⠬⠇"), got
