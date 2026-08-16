"""수학 점자 규정(제1~9장) 원문 예시 대조.

`regulation_pairs/`는 한글 점자 1~14장뿐이고 **수학 점자 쌍이 없었다**(2026-08-16 신설).
수식 축이 게이트 최약(66.0%)이라 여기부터 채운다.

기대값은 규정 원문의 BRF-ASCII 예시를 그대로 옮긴 것이고 묵자는 조항 문구에서 읽었다 —
생산 코드로 만들지 않았다(test_guide 원칙 1 순환검증 금지).

⚠ 예시를 잘못 읽으면 없는 불일치가 생긴다. `#j`는 10이 아니라 0이고 `#gb`는 62가 아니라
   72다(2026-08-16 실수). 쌍을 늘릴 때는 디코드 결과를 한 건씩 눈으로 확인할 것.
"""
import json
from pathlib import Path

import pytest

from app.ai.braille.kor_math_rules import convert_latex
from app.utils.braille_ascii import ascii_to_unicode

_DATA = Path(__file__).parent.parent.parent / "test_data" / "regulation_pairs" / "section_15_math.json"
_PAIRS = json.loads(_DATA.read_text(encoding="utf-8"))["pairs"]
_IDS = [f"{p['rule_id']}:{p['latex']}" for p in _PAIRS]


@pytest.mark.parametrize("pair", _PAIRS, ids=_IDS)
def test_규정_예시대로_점역된다(pair):
    assert convert_latex(pair["latex"]) == pair["braille_unicode"], pair["item"]


@pytest.mark.parametrize("pair", _PAIRS, ids=_IDS)
def test_기록된_점형이_원문_ASCII와_일치한다(pair):
    """데이터 자체의 무결성 — 손으로 옮긴 BRF-ASCII와 유니코드가 어긋나면 안 된다."""
    assert ascii_to_unicode(pair["brf_ascii"], backtick="cell") == pair["braille_unicode"]


# ── 중괄호 없는 한 글자 인자 (LaTeX 허용 표기) ────────────────────────────────
# 실측 전 코퍼스 23건. 드물지만 고치기 전에는 **조용히 틀린 수가 나갔다** —
# `\frac 1 2`가 분수를 잃고 `12`로 붙었다.
@pytest.mark.parametrize("bare,braced", [
    ("\\sqrt3", "\\sqrt{3}"),
    ("\\sqrt x", "\\sqrt{x}"),
    ("\\frac 1 2", "\\frac{1}{2}"),
])
def test_중괄호_없는_인자도_같게_점역된다(bare, braced):
    assert convert_latex(bare) == convert_latex(braced)


def test_제곱근_기호가_사라지지_않는다():
    assert convert_latex("\\sqrt3").startswith("⠜")


def test_n제곱근은_대괄호라_안_걸린다():
    assert convert_latex("\\sqrt[3]{8}") == "⠼⠉⠻⠼⠓"
