"""MinerU 가 수식 토큰 사이에 넣은 칸이 점자에 그대로 실리던 문제 (2026-09-08).

MinerU 는 수식 LaTeX 을 토큰마다 띄어 낸다(`x = - 24` · `\\sin 70 ^ {\\circ}` ·
`3 a x ^ {2}` · `\\{1, 2 \\}`). 엔진은 그 칸을 묵자에 있는 칸으로 읽어 점자에 실었다.
**같은 수식을 칸 없이 주면 엔진이 이미 규정대로 붙여 낸다** — 결함은 엔진이 아니라
정규화가 그 자리를 안 지운 것이다. 그래서 이 테스트는 "칸 있는 꼴과 칸 없는 꼴의
점자가 같다" 로 잡는다.

근거 조항과 gold
  · 부호  「한국 점자 규정」 제45항(수식 안 연산 기호 붙임, 예시 `9-3=6`)·제46항(한글
    사이에서만 한 칸). gold `corpus/pages/braille/.../수학2 p002` = ⠭⠒⠒⠔⠼⠃⠙
  · 도    제50항. gold 수학2 p009 에 ⠴⠙ 24자리, 앞이 전부 붙어 있다
  · 낱자 곱  「수학 점자」 제12항 [붙임 2](AB → ⠠⠁⠠⠃)
  · 집합 묶음표  제54항 "닫는 따옴표와 닫는 괄호 앞은 붙여 쓴다"

CER 은 빈칸 셀을 지우고 견주므로 이 결함을 못 잰다. 칸수 일치율에만 보인다
(코퍼스 1,131쪽 재점역: dev 99.0246% → 99.0557%, val 99.1431% → 99.1567%).
"""
import pytest

from app.ai.braille.kor_math_rules import convert_latex

# (칸 낀 MinerU 꼴, 칸 없는 같은 수식)
SAME = [
    (r"x = - 24",                 r"x = -24"),                 # 제45·46항
    (r"x \neq - 1",               r"x \neq -1"),
    (r"\sin 70 ^ {\circ}",        r"\sin 70^{\circ}"),         # 제50항
    (r"f ^ {\prime} (x) = 3 a x", r"f^{\prime}(x) = 3ax"),      # 수학 제12항 [붙임 2]
    (r"A = \{1, 2 \}",            r"A = \{1, 2\}"),            # 제54항
]

# 손대면 안 되는 것 — 칸을 지우면 뜻이 바뀌거나 명령이 깨진다
KEEP = [
    (r"\sin x",    "⠖⠎⠭"),        # 명령 꼬리에 붙이면 \sinx 가 되어 통째로 사라진다
    (r"\log_a x",  "⠸⠰⠁⠀⠭"),      # 밑과 진수가 붙으면 제46항 로그 판정이 갈린다
    (r"9 - 3 = 6", "⠼⠊⠔⠼⠉⠒⠒⠼⠋"),  # 이항 뺄셈은 종전 단계가 이미 붙인다
]


@pytest.mark.parametrize("spaced,tight", SAME)
def test_mineru_token_gap_does_not_reach_braille(spaced, tight):
    assert convert_latex(spaced) == convert_latex(tight)


@pytest.mark.parametrize("latex,want", KEEP)
def test_meaningful_spacing_survives(latex, want):
    assert convert_latex(latex) == want


def test_negative_number_matches_gold():
    """gold(수학2 p002) 는 음수 부호를 수에 붙인다 — 제45항."""
    assert convert_latex("x = - 24") == "⠭⠒⠒⠔⠼⠃⠙"
