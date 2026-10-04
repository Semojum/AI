"""로그 진수 · 밑 묶음 괄호 (#1074, 「수학 점자」 제46항).

규정 BRF 는 `한국 점자 규정_재추출.txt` 행 번호, gold 는 2027 수학 I(EBS-E26-009, 비홀드아웃) 쪽.
규정 원문은 칸 띄우기 관례라 backtick="space" 로 읽는다(규정 예문에는 백틱이 없다).
"""
import pytest

from app.ai.braille.kor_math_rules import convert_latex
from app.utils.braille_ascii import ascii_to_unicode

CASES = [
    # 1호 · 2호 — 진수는 바로 이어 적는다
    (r"\log_{5} 2",              "_,5#b",          "3810"),
    (r"\log (x+1)",              "_8x5#a0",        "3814 밑 없는 괄호 진수는 안 묶음"),
    (r"\log_a n",                "_;an",           "3818"),
    (r"\log_a x",                "_;ax",           "3818 꼴, MinerU 칸(`\\log_a x`)이 빈칸 셀로 남지 않음"),
    # [붙임 1] 밑이 분수 · 소수
    (r"\log_{\frac{1}{3}} 9",    "_;(#c/#a)#i",    "3824"),
    (r"\log_{0.2} N",            "_;(#j4b),n",     "3826"),
    # [붙임 2] 진수가 분수 · 곱 · 괄호
    (r"\log_a \frac{u}{v}",      "_;a(v/u)",       "3834"),
    (r"\log_2 (x+1)",            "_,2(8x5#a0)",    "3836"),
    # [다만] 밑이 문자이고 진수가 괄호면 안 묶음
    (r"\log_e (2+h)",            "_;e8#b5h0",      "3841"),
    # 2027 gold 꼴
    (r"\log _{3} 2 \sqrt{3}",    "_,3(#b>#c)",     "gold 009 p0002 곱"),
    (r"\log_{2} a\sqrt{b}",      "_,2(a>b)",       "gold 009 p0005 곱"),
    (r"\log_{2} \frac{1}{4}",    "_,2(#d/#a)",     "gold 009 p0002 분수"),
    (r"\log_3 \sqrt{6}",         "_,3>#f",         "gold 009 p0002 근호 하나는 안 묶음"),
]


@pytest.mark.parametrize("latex,brf,src", CASES, ids=[c[0] for c in CASES])
def test_log_grouping(latex, brf, src):
    assert convert_latex(latex) == ascii_to_unicode(brf, backtick="space"), src


@pytest.mark.parametrize("latex", [r"\log_2 3x^{2}", r"\log_2 x^{2}", r"\log_2 x=3", r"\log_{3} 27"])
def test_not_grouped_when_argument_end_unclear_or_single(latex):
    # 진수 뒤에 ^ 가 붙으면 곱의 끝을 모르고, 단일 수 · 글자는 묶지 않는다.
    assert "⠷" not in convert_latex(latex)
