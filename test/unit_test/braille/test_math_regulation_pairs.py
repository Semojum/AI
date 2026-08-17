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
    # ★ 백틱 규약이 **문서마다 반대**다 — 규정 원문은 공백, 정답 코퍼스는 셀(⠈=ㄱ).
    #   이 세트는 규정 원문에서 옮긴 것이라 space로 읽어야 한다. cell로 읽으면 화살표·
    #   일반연산 예시의 띄어쓰기가 ⠈로 둔갑한다(2026-08-16 실측).
    assert ascii_to_unicode(pair["brf_ascii"], backtick="space") == pair["braille_unicode"]


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


# ── 그리스 명령의 곱 판정 (2026-08-17) ────────────────────────────────────────
# 코퍼스의 '수+그리스' 분수 인자 284건은 **전부 명령 꼴**이다(유니코드 0건).
# gold는 묶는다 — eval 실물 대조 [009 p0018] ⠨⠏⠌⠷⠼⠃⠨⠏⠾.
@pytest.mark.parametrize("latex,expected", [
    ("\\frac{2\\pi}{b}", "⠃⠌⠷⠼⠃⠨⠏⠾"),
    ("\\frac{2π}{b}", "⠃⠌⠷⠼⠃⠨⠏⠾"),
])
def test_명령_꼴_그리스도_곱으로_본다(latex, expected):
# ── 기호 명령 뒤 종료 공백 (LaTeX 문법이지 내용이 아니다) ──────────────────────
# 규정 제52항 변화율 예시가 `,.dx/,.dy`(= ⠠⠨⠙⠭⠌⠠⠨⠙⠽)로 붙여 적는다.
# 실측 전 코퍼스 412건(`\Delta ` 357 · `\cdot ` 23 · `\pi ` 17 · `\mu ` 13).
@pytest.mark.parametrize("latex,expected", [
    ("\\frac{\\Delta y}{\\Delta x}", "⠠⠨⠙⠭⠌⠠⠨⠙⠽"),   # 제52항
    ("\\Delta x", "⠠⠨⠙⠭"),
    ("a\\cdot b", "⠁⠐⠃"),                            # 제2항 붙임
    ("2\\pi r", "⠼⠃⠨⠏⠗"),
])
def test_기호_명령_뒤_공백은_붙여_적는다(latex, expected):
    assert convert_latex(latex) == expected


@pytest.mark.parametrize("latex,expected", [
    ("\\chi^{2}", "⠨⠯⠘⠼⠃"),
    ("\\alpha^{2}", "⠨⠁⠘⠼⠃"),
])
def test_그리스_위첨자가_깨지지_않는다(latex, expected):
    """판정 때문에 문자열을 미리 바꾸면 뒤 단계의 위첨자 파싱이 깨진다.

    한 번 깨뜨렸다 — 위첨자표 ⠘가 사라지고 ⠈⠢⠦⠂ 잔재가 나갔다(eval 실측
    001 p0012·p0047). 그래서 판정 입력만 정규화하고 문자열은 안 건드린다.
    """
    ("x \\oplus y", "⠭⠀⠸⠢⠀⠽"),      # 제15항 "기호의 앞뒤를 한 칸씩 띄어 쓴다"
    ("A \\cap B", "⠠⠁⠀⠩⠀⠠⠃"),
])
def test_일반연산_관계기호의_한_칸은_지킨다(latex, expected):
    """붙임 규칙을 넓히다 이쪽을 깨뜨리면 안 된다 — 규정이 띄우라고 하는 자리다."""
    assert convert_latex(latex) == expected
